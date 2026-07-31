"""Banco de pruebas de tracción, sin MQTT ni webapp.

    python tools/drive_test.py --sim          # en el portátil
    python tools/drive_test.py                # en la Pi, con motores

Ejecuta una secuencia de maniobras e imprime lo que llega a los pines. En la
Pi, con la batería conectada, es la comprobación de la Fase 1: verifica que
cada oruga gira en el sentido correcto y que el watchdog frena de verdad.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import load  # noqa: E402
from services.motion import backend as gpio  # noqa: E402
from services.motion.motors import DifferentialDrive, mix_arcade  # noqa: E402

MANIOBRAS = [
    ("adelante", 0.0, 1.0, 2.0),
    ("parar", 0.0, 0.0, 1.0),
    ("atras", 0.0, -1.0, 2.0),
    ("parar", 0.0, 0.0, 1.0),
    ("giro izquierda", -1.0, 0.0, 1.5),
    ("giro derecha", 1.0, 0.0, 1.5),
    ("parar", 0.0, 0.0, 1.0),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--watchdog", action="store_true", help="prueba solo la parada por watchdog")
    args = ap.parse_args()

    cfg = load(args.config)
    io = gpio.create(sim=args.sim)
    drive = DifferentialDrive(io, cfg.motion)

    hz = cfg.motion.control_hz
    dt = 1.0 / hz

    def girar(segundos: float) -> None:
        for _ in range(int(segundos * hz)):
            drive.update(dt)
            time.sleep(dt)

    def mostrar(etiqueta: str) -> None:
        cur = drive.current
        di = io.duties.get(cfg.motion.left.pwm, 0.0) if hasattr(io, "duties") else 0.0
        dd = io.duties.get(cfg.motion.right.pwm, 0.0) if hasattr(io, "duties") else 0.0
        print(f"  {etiqueta:16s} izq={cur.left:+.2f} der={cur.right:+.2f}  duty={di:.0%}/{dd:.0%}")

    try:
        if args.watchdog:
            print("\nPrueba de watchdog: acelerar y luego dejar de dar comandos.\n")
            drive.set_target(1.0, 1.0)
            girar(1.5)
            mostrar("a fondo")

            print(f"\n  ...silencio. El watchdog debe frenar en {cfg.motion.watchdog_ms} ms")
            t0 = time.monotonic()
            drive.stop_target()
            while drive.current.left != 0.0 and time.monotonic() - t0 < 3.0:
                drive.update(dt)
                time.sleep(dt)
            print(f"  detenido en {(time.monotonic() - t0) * 1000:.0f} ms")
            mostrar("tras frenar")
        else:
            print(f"\nSecuencia de maniobras (tope de duty {cfg.motion.duty_cap:.0%})\n")
            for nombre, steer, throttle, dur in MANIOBRAS:
                left, right = mix_arcade(throttle, steer)
                drive.set_target(left, right)
                girar(dur)
                mostrar(nombre)
        print()
    except KeyboardInterrupt:
        print("\ninterrumpido")
    finally:
        drive.shutdown()
        io.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
