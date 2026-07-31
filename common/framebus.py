"""Transporte de frames JPEG entre procesos por memoria compartida.

Los frames no viajan por MQTT (PLAN.md §6): a 15 fps serían ~1 MB/s de
serialización y copias inútiles. `wally-vision` escribe aquí y `wally-web`
lee, sin copias intermedias ni broker de por medio.

**Por qué mmap y no multiprocessing.shared_memory.** Esa API registra cada
segmento en el `resource_tracker` de Python, que al terminar el proceso hace
unlink — incluidos los procesos que solo *leen*. Con `Restart=always` en
systemd, cada reinicio de `wally-web` destruiría el buffer de `wally-vision`,
que seguiría escribiendo en un segmento huérfano que ya nadie puede abrir: el
vídeo se pierde hasta reiniciar también la cámara. Un archivo en `/dev/shm`
(tmpfs, sin respaldo en disco) no tiene ese comportamiento y además se puede
inspeccionar con `ls -la /dev/shm/`.

Se sincroniza con un **seqlock**, no con un mutex: un escritor y N lectores,
donde los lectores nunca bloquean al escritor. El contador de secuencia es
impar mientras hay una escritura en curso; un lector que observe un valor
impar, o que vea el contador cambiar entre el inicio y el final de su lectura,
descarta y reintenta. Un lector lento se pierde frames, que es justo lo que
debe pasar con vídeo en vivo.
"""

from __future__ import annotations

import mmap
import os
import struct
import tempfile
import time
from pathlib import Path

DEFAULT_NAME = "wally_frame"
# 640x480 con calidad 80 ronda los 60 KB; 1 MB deja margen para subir la
# resolución sin tocar esto.
DEFAULT_CAPACITY = 1024 * 1024

# secuencia (uint64), longitud (uint32), instante de captura (double).
# El "<" desactiva el relleno de alineación, así el formato es idéntico en
# cualquier arquitectura.
_HEADER = struct.Struct("<QId")
_HEADER_SIZE = _HEADER.size

MAX_READ_RETRIES = 8


def shm_path(name: str = DEFAULT_NAME) -> Path:
    """Ubicación del buffer. En Linux es tmpfs; en macOS, solo para desarrollo."""
    devshm = Path("/dev/shm")
    base = devshm if devshm.is_dir() else Path(tempfile.gettempdir())
    return base / name


class FrameWriter:
    """Extremo escritor. Solo puede haber uno."""

    def __init__(self, name: str = DEFAULT_NAME, capacity: int = DEFAULT_CAPACITY) -> None:
        self._capacity = capacity
        self._path = shm_path(name)
        total = _HEADER_SIZE + capacity

        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            os.ftruncate(fd, total)
            self._mm = mmap.mmap(fd, total, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        finally:
            # El mmap mantiene viva su propia referencia al inode.
            os.close(fd)

        self._seq = 0
        _HEADER.pack_into(self._mm, 0, 0, 0, 0.0)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def path(self) -> Path:
        return self._path

    def write(self, jpeg: bytes) -> bool:
        """Publica un frame. Devuelve False si no cabe (el frame se descarta)."""
        if len(jpeg) > self._capacity:
            return False

        # Impar = escritura en curso.
        self._seq += 1
        _HEADER.pack_into(self._mm, 0, self._seq, 0, 0.0)

        self._mm[_HEADER_SIZE : _HEADER_SIZE + len(jpeg)] = jpeg

        # Par = frame completo y consistente.
        self._seq += 1
        _HEADER.pack_into(self._mm, 0, self._seq, len(jpeg), time.time())
        return True

    def close(self) -> None:
        """Libera el mmap pero **no** borra el archivo.

        Dejarlo permite que un lector conserve su mmap válido y que un
        reinicio del escritor reutilice el mismo inode. Al ser tmpfs, el
        sistema lo limpia solo al reiniciar.
        """
        self._mm.close()


class FrameReader:
    """Extremo lector. Puede haber varios en procesos distintos."""

    def __init__(self, name: str = DEFAULT_NAME) -> None:
        self._path = shm_path(name)
        self._mm: mmap.mmap | None = None

    def _attach(self) -> bool:
        if self._mm is not None:
            return True
        try:
            fd = os.open(self._path, os.O_RDONLY)
        except FileNotFoundError:
            # wally-vision aún no arrancó. No es un error fatal: la webapp
            # debe seguir sirviendo control aunque no haya vídeo.
            return False
        try:
            size = os.fstat(fd).st_size
            if size < _HEADER_SIZE:
                # El escritor creó el archivo pero aún no lo dimensionó.
                return False
            self._mm = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ)
        finally:
            os.close(fd)
        return True

    def read(self) -> tuple[int, bytes] | None:
        """Devuelve (secuencia, jpeg) o None si no hay frame válido."""
        if not self._attach():
            return None
        assert self._mm is not None

        for _ in range(MAX_READ_RETRIES):
            try:
                seq_before, length, _ts = _HEADER.unpack_from(self._mm, 0)
            except (ValueError, BufferError):
                self.detach()
                return None

            if seq_before == 0 or seq_before % 2 == 1 or length == 0:
                # Sin frames todavía, o escritura en curso.
                continue
            if _HEADER_SIZE + length > len(self._mm):
                return None

            data = self._mm[_HEADER_SIZE : _HEADER_SIZE + length]

            seq_after, _, _ = _HEADER.unpack_from(self._mm, 0)
            if seq_after == seq_before:
                return (seq_before, data)
            # El escritor pasó por encima mientras copiábamos: reintentar.

        return None

    def age_s(self) -> float | None:
        """Segundos desde el último frame publicado, o None si no hay ninguno.

        Permite distinguir "no hay vídeo" de "el vídeo se congeló": si crece
        sin parar, `wally-vision` está vivo pero no captura, o murió.
        """
        if not self._attach():
            return None
        assert self._mm is not None
        try:
            seq, length, ts = _HEADER.unpack_from(self._mm, 0)
        except (ValueError, BufferError):
            return None
        if seq == 0 or ts <= 0:
            return None
        return max(0.0, time.time() - ts)

    def detach(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None

    def close(self) -> None:
        self.detach()
