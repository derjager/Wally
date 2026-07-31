"""Síntesis de voz.

Piper (PLAN.md §5) es neural, funciona sin internet y va en tiempo real en una
Pi 4, que es la combinación que hacía falta: `espeak` suena demasiado a robot
de los ochenta y cualquier TTS en la nube deja al robot mudo sin wifi.

Los backends alternativos existen para poder desarrollar en un portátil sin
instalar Piper ni descargar modelos de voz.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

log = logging.getLogger("voice.tts")


class TTSBackend(ABC):
    @abstractmethod
    def say(self, text: str) -> bool:
        """Sintetiza y reproduce. Bloquea hasta terminar."""

    def stop(self) -> None:
        """Interrumpe lo que se esté reproduciendo."""

    @property
    def name(self) -> str:
        return type(self).__name__


class PiperBackend(TTSBackend):
    """Piper canalizado a un reproductor de audio.

    Se usa una tubería en lugar de un archivo temporal para que la voz empiece
    a sonar mientras aún se está sintetizando el resto de la frase.
    """

    def __init__(self, model: str, piper_bin: str = "piper", player: str = "aplay") -> None:
        self._model = Path(model)
        self._piper = piper_bin
        self._player = player
        self._proc: subprocess.Popen | None = None

        if shutil.which(piper_bin) is None:
            raise RuntimeError(f"no se encuentra el ejecutable '{piper_bin}'")
        if not self._model.exists():
            raise RuntimeError(f"no se encuentra el modelo de voz {self._model}")
        if shutil.which(player) is None:
            raise RuntimeError(f"no se encuentra el reproductor '{player}'")

    def say(self, text: str) -> bool:
        try:
            piper = subprocess.Popen(
                [self._piper, "--model", str(self._model), "--output_file", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            player = subprocess.Popen(
                [self._player, "-q", "-"],
                stdin=piper.stdout,
                stderr=subprocess.DEVNULL,
            )
            # Cerrar nuestra copia del extremo de lectura: si no, el
            # reproductor nunca vería el fin de la tubería y se quedaría
            # esperando para siempre.
            if piper.stdout:
                piper.stdout.close()

            self._proc = player
            piper.communicate(input=text.encode("utf-8"))
            player.wait()
            return player.returncode == 0
        except Exception:
            log.exception("fallo al sintetizar")
            return False
        finally:
            self._proc = None

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


class MacSayBackend(TTSBackend):
    """`say` de macOS. Solo para desarrollar en el portátil."""

    def __init__(self, voice: str = "Mónica") -> None:
        if sys.platform != "darwin" or shutil.which("say") is None:
            raise RuntimeError("`say` solo está en macOS")
        self._voice = voice
        self._proc: subprocess.Popen | None = None

    def say(self, text: str) -> bool:
        try:
            self._proc = subprocess.Popen(["say", "-v", self._voice, text])
            self._proc.wait()
            return self._proc.returncode == 0
        except Exception:
            log.exception("fallo en `say`")
            return False
        finally:
            self._proc = None

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


class LogBackend(TTSBackend):
    """Escribe lo que diría, sin sonido. Para pruebas y para servidores mudos."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def say(self, text: str) -> bool:
        self.spoken.append(text)
        log.info("🔊 %s", text)
        return True


def create(cfg, sim: bool = False) -> TTSBackend:
    """Elige el mejor backend disponible.

    Degrada en cascada en vez de fallar: un robot sin voz sigue siendo útil,
    así que nunca vale la pena impedir el arranque por esto.
    """
    if sim:
        try:
            return MacSayBackend()
        except RuntimeError:
            return LogBackend()

    try:
        return PiperBackend(cfg.model, cfg.piper_bin, cfg.player)
    except RuntimeError as exc:
        log.warning("Piper no disponible (%s); Wally se quedará mudo", exc)
        return LogBackend()
