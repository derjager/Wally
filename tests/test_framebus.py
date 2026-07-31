"""Pruebas del transporte de frames por memoria compartida."""

from __future__ import annotations

from pathlib import Path

import pytest

from common.framebus import FrameReader, FrameWriter, shm_path


@pytest.fixture
def bus():
    w = FrameWriter(name="wally_test_frame", capacity=64 * 1024)
    r = FrameReader(name="wally_test_frame")
    yield w, r
    r.close()
    w.close()
    shm_path("wally_test_frame").unlink(missing_ok=True)


def test_ida_y_vuelta(bus):
    w, r = bus
    assert w.write(b"\xff\xd8jpeg-falso\xff\xd9")
    item = r.read()
    assert item is not None
    seq, data = item
    assert data == b"\xff\xd8jpeg-falso\xff\xd9"
    assert seq > 0


def test_la_secuencia_avanza_en_cada_frame(bus):
    w, r = bus
    w.write(b"primero")
    seq1, _ = r.read()
    w.write(b"segundo")
    seq2, data = r.read()

    assert seq2 > seq1
    assert data == b"segundo"


def test_leer_dos_veces_sin_escribir_da_la_misma_secuencia(bus):
    """Así el streaming distingue un frame nuevo de la repetición del anterior."""
    w, r = bus
    w.write(b"quieto")
    assert r.read()[0] == r.read()[0]


def test_un_frame_que_no_cabe_se_descarta(bus):
    """Preferible perder un frame a corromper la memoria compartida."""
    w, r = bus
    w.write(b"bueno")
    assert w.write(b"x" * (w.capacity + 1)) is False
    # El frame anterior sigue intacto.
    assert r.read()[1] == b"bueno"


def test_sin_escritor_no_hay_lectura_pero_tampoco_error():
    """La webapp debe seguir sirviendo control aunque wally-vision no exista."""
    r = FrameReader(name="wally_no_existe_en_absoluto")
    assert r.read() is None
    r.close()


def test_lector_antes_del_primer_frame(bus):
    _, r = bus
    assert r.read() is None


def test_frames_de_tamano_variable(bus):
    """Un JPEG grande seguido de uno pequeño no debe dejar cola del anterior."""
    w, r = bus
    w.write(b"A" * 5000)
    assert len(r.read()[1]) == 5000
    w.write(b"B" * 10)
    seq, data = r.read()
    assert data == b"B" * 10
    assert len(data) == 10


def test_un_lector_que_termina_no_destruye_el_buffer(bus):
    """Regresión: con multiprocessing.shared_memory, el resource_tracker hacía
    unlink al morir cualquier proceso que hubiera *leído*. Como wally-web usa
    Restart=always, cada reinicio suyo dejaba a wally-vision escribiendo en un
    segmento huérfano y el vídeo no volvía hasta reiniciar la cámara.
    """
    w, r = bus
    w.write(b"vivo")

    efimero = FrameReader(name="wally_test_frame")
    assert efimero.read()[1] == b"vivo"
    efimero.close()
    del efimero

    # El escritor sigue funcionando y un lector nuevo lo ve.
    w.write(b"sigo-vivo")
    otro = FrameReader(name="wally_test_frame")
    assert otro.read()[1] == b"sigo-vivo"
    otro.close()


def test_age_s_detecta_video_congelado(bus):
    """Distingue "no hay vídeo" de "wally-vision murió y el frame envejece"."""
    w, r = bus
    assert r.age_s() is None  # sin frames todavía

    w.write(b"frame")
    age = r.age_s()
    assert age is not None and age < 1.0


def test_el_buffer_vive_en_memoria_no_en_disco():
    """En la Pi debe ser tmpfs: escribir 15 JPEG por segundo a la SD la
    desgastaría y añadiría latencia."""
    from common.framebus import shm_path

    p = shm_path("cualquiera")
    if Path("/dev/shm").is_dir():
        assert str(p).startswith("/dev/shm")
