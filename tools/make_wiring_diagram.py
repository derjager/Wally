"""Genera el diagrama de conexión de Wally en SVG.

    python tools/make_wiring_diagram.py

Los pines se leen de `common/config.py`, no se escriben a mano: así el
diagrama no puede desincronizarse del código. Si cambias un pin en la
configuración, regenera y el dibujo se actualiza solo.

Salida: docs/wiring.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.config import MotionConfig  # noqa: E402

# Paleta, coherente con la interfaz web del robot.
BG = "#0f1319"
PANEL = "#19212e"
EDGE = "#2c3648"
TEXT = "#e8ecf2"
MUTED = "#8b97a8"
POWER = "#ff5c5c"      # riel de potencia 4.8 V
LOGIC = "#ffb020"      # riel de lógica 5 V
GND = "#7c8797"
SIGNAL = "#5ac8fa"     # señales GPIO
ACCENT = "#ff8a3d"
WARN = "#ff5c5c"

W, H = 1160, 990

# Pin físico del header por número BCM. Se necesita para cablear contando
# pines en la placa, que es como se hace en la práctica.
BCM_TO_PHYS = {
    2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23,
    12: 32, 13: 33, 14: 8, 15: 10, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38,
    21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13,
}


def esc(s: str) -> str:
    """Escapa texto para XML.

    Hace falta de verdad: las etiquetas usan `->` y `<-` para indicar sentido,
    y un `<` literal rompe el SVG entero.
    """
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Svg:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def box(self, x, y, w, h, title, subtitle="", stroke=EDGE, fill=PANEL, r=10) -> float:
        """Dibuja una caja. Devuelve la Y donde puede empezar el contenido."""
        self.add(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        )
        self.add(
            f'<text x="{x + 14}" y="{y + 25}" fill="{TEXT}" font-size="15" '
            f'font-weight="700" font-family="ui-sans-serif,system-ui,sans-serif">{esc(title)}</text>'
        )
        if subtitle:
            self.add(
                f'<text x="{x + 14}" y="{y + 44}" fill="{MUTED}" font-size="11.5" '
                f'font-family="ui-sans-serif,system-ui,sans-serif">{esc(subtitle)}</text>'
            )
            return y + 68
        return y + 48

    def text(self, x, y, s, fill=TEXT, size=12, weight="400", mono=True, anchor="start"):
        family = (
            "ui-monospace,SFMono-Regular,Menlo,monospace"
            if mono
            else "ui-sans-serif,system-ui,sans-serif"
        )
        self.add(
            f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
            f'font-weight="{weight}" font-family="{family}" text-anchor="{anchor}">{esc(s)}</text>'
        )

    def line(self, pts, stroke, width=2.5, dash=None):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(
            f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
            f'stroke-linecap="round" stroke-linejoin="round"{dash_attr}/>'
        )

    def arrow(self, x, y, stroke, direction="right"):
        if direction == "right":
            pts = f"{x},{y} {x - 7},{y - 4.5} {x - 7},{y + 4.5}"
        else:
            pts = f"{x},{y} {x + 7},{y - 4.5} {x + 7},{y + 4.5}"
        self.add(f'<polygon points="{pts}" fill="{stroke}"/>')

    def label(self, x, y, s, fill):
        """Etiqueta sobre una línea, con fondo para que se lea."""
        w = len(s) * 6.4 + 10
        self.add(
            f'<rect x="{x - w / 2}" y="{y - 9}" width="{w}" height="16" rx="4" '
            f'fill="{BG}" opacity="0.92"/>'
        )
        self.text(x, y + 3, s, fill=fill, size=10.5, anchor="middle")

    def render(self) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}" height="{H}" role="img" '
            f'aria-label="Diagrama de conexión de Wally">\n'
            f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
            + "\n".join(self.parts)
            + "\n</svg>\n"
        )


def pin(bcm: int) -> str:
    return f"GPIO{bcm} (p{BCM_TO_PHYS[bcm]})"


def build() -> str:
    cfg = MotionConfig()
    s = Svg()

    s.text(40, 46, "WALLY · Diagrama de conexión", size=22, weight="700", mono=False)
    s.text(
        40, 68,
        "Pines generados desde common/config.py · Numeración BCM, (pN) = pin físico del header",
        fill=MUTED, size=12, mono=False,
    )

    # ---------------------------------------------------------------- energía
    s.text(40, 108, "ALIMENTACIÓN", fill=MUTED, size=11.5, weight="700", mono=False)

    y0 = s.box(40, 122, 268, 88, "LiPo 2S", "7.4 V nominal · 8.4 V cargada")
    s.text(54, y0, "5500 mAh 35C · corte a 6.6 V", fill=MUTED, size=11)

    s.box(40, 232, 268, 44, "Fusible 10 A  +  Interruptor", "", stroke=EDGE)

    y0 = s.box(40, 300, 268, 86, "BEC / UBEC  ->  5 V", "switching, >=3 A · RIEL DE LÓGICA",
               stroke=LOGIC)
    s.text(54, y0, "cap 470 µF a la salida", fill=MUTED, size=11)

    y0 = s.box(40, 406, 268, 86, "XL4015  ->  4.8 V", "ajustable · RIEL DE POTENCIA",
               stroke=POWER)
    s.text(54, y0, "cap 1000 µF a la salida", fill=MUTED, size=11)

    # Batería -> fusible -> bucks
    s.line([(174, 210), (174, 232)], POWER, 3)
    s.line([(174, 276), (174, 288)], POWER, 3)
    s.line([(100, 288), (248, 288)], POWER, 3)
    s.line([(100, 288), (100, 300)], LOGIC, 3)
    s.line([(248, 288), (248, 400), (174, 400), (174, 406)], POWER, 3)

    # Masa común
    y0 = s.box(40, 512, 268, 112, "MASA COMUN", "obligatoria", stroke=GND)
    for i, txt in enumerate(
        ["LiPo -  ·  BEC -  ·  XL4015 -", "Pi GND  ·  TB6612 GND", "servos GND  ·  HC-SR04 GND"]
    ):
        s.text(54, y0 + i * 17, txt, fill=MUTED, size=11)

    # ------------------------------------------------------------------- Pi 4
    px, py, pw, ph = 372, 122, 316, 590
    content_y = s.box(px, py, pw, ph, "Raspberry Pi 4 Model B",
                      "4 GB · Raspberry Pi OS Bookworm 64-bit", stroke=ACCENT)

    rows = [
        ("5 V  (p2 / p4)", "<- BEC", LOGIC),
        ("GND (p6, p9, p14…)", "<- masa", GND),
        ("3.3 V (p1)", "-> TB6612 VCC", SIGNAL),
        (None, None, None),
        (pin(cfg.left.pwm), "-> PWMA", SIGNAL),
        (pin(cfg.left.in1), "-> AIN1", SIGNAL),
        (pin(cfg.left.in2), "-> AIN2", SIGNAL),
        (pin(cfg.right.pwm), "-> PWMB", SIGNAL),
        (pin(cfg.right.in1), "-> BIN1", SIGNAL),
        (pin(cfg.right.in2), "-> BIN2", SIGNAL),
        (pin(cfg.standby), "-> STBY", SIGNAL),
        (None, None, None),
        (pin(cfg.servo_left), "-> servo izq", SIGNAL),
        (pin(cfg.servo_right), "-> servo der", SIGNAL),
        (None, None, None),
    ]
    for sensor in cfg.rangefinders:
        rows.append((pin(sensor.trig), f"-> TRIG {sensor.name}", SIGNAL))
        rows.append((pin(sensor.echo), f"<- ECHO {sensor.name} (!)", WARN))
    rows.append((None, None, None))
    rows.append(("GPIO24 (p18)", "-> LEDs IR (transistor)", MUTED))
    rows.append(("CSI", "-> cámara OV5647", MUTED))
    rows.append(("micro-HDMI", "-> pantalla 3.5\"", MUTED))
    rows.append(("jack 3.5 mm", "-> audio", MUTED))

    y = content_y
    for left, right, color in rows:
        if left is None:
            s.line([(px + 14, y - 8), (px + pw - 14, y - 8)], EDGE, 1)
            y += 10
            continue
        s.text(px + 14, y, left, fill=TEXT, size=11.5)
        s.text(px + pw - 14, y, right, fill=color, size=11.5, anchor="end")
        y += 17

    # BEC -> Pi
    s.line([(308, 336), (340, 336), (340, 200), (px, 200)], LOGIC, 3)
    s.arrow(px, 200, LOGIC)
    s.label(340, 160, "5 V", LOGIC)

    # ------------------------------------------------------------ periféricos
    bx, bw = 756, 364
    y0 = s.box(bx, 122, bw, 244, "TB6612FNG", "driver dual de motores", stroke=SIGNAL)
    driver_rows = [
        ("VM", "<- 4.8 V (XL4015)", POWER),
        ("VCC", "<- 3.3 V (Pi p1)", SIGNAL),
        ("GND", "<- masa común", GND),
        ("STBY", f"<- {pin(cfg.standby)}", SIGNAL),
        ("PWMA / AIN1 / AIN2", "<- Pi", SIGNAL),
        ("PWMB / BIN1 / BIN2", "<- Pi", SIGNAL),
        ("AO1 · AO2", "-> motor izquierdo", ACCENT),
        ("BO1 · BO2", "-> motor derecho", ACCENT),
    ]
    y = y0
    for left, right, color in driver_rows:
        s.text(bx + 14, y, left, fill=TEXT, size=11.5)
        s.text(bx + bw - 14, y, right, fill=color, size=11.5, anchor="end")
        y += 17

    s.text(bx + 14, 350, "STBY bajo = parada de emergencia por hardware", fill=WARN, size=10.5)

    y0 = s.box(bx, 386, bw, 76, "Motores Tamiya FA-130", "3 V nominales (1.5–3 V)",
               stroke=ACCENT)
    s.text(bx + 14, y0, "tope de duty al 60 % -> ~2.6 V efectivos", fill=MUTED, size=11)

    s.box(bx, 482, bw, 68, "2 x servo (brazos)",
          "<- 4.8 V del XL4015, NO de la Pi", stroke=POWER)

    y0 = s.box(bx, 570, bw, 172, "3 x HC-SR04", "frontal + diagonales a 35° · VCC a 5 V",
               stroke=SIGNAL)
    for sensor in cfg.rangefinders:
        s.text(bx + 14, y0, sensor.name, fill=TEXT, size=11.5)
        s.text(bx + 78, y0, f"TRIG {pin(sensor.trig)}", fill=SIGNAL, size=10.5)
        s.text(bx + bw - 14, y0, f"ECHO {pin(sensor.echo)}", fill=WARN, size=10.5,
               anchor="end")
        y0 += 18
    s.text(bx + 14, y0 + 10, "cada ECHO vía divisor (!)", fill=WARN, size=11)
    s.text(bx + 14, y0 + 27, "disparo secuencial: a la vez hay crosstalk",
           fill=MUTED, size=10.5)

    # XL4015 -> VM del driver, por encima de todo para no cruzar la Pi
    s.line([(308, 442), (336, 442), (336, 96), (bx + 60, 96), (bx + 60, 122)], POWER, 3)
    s.arrow(bx + 60, 122, POWER, "left")
    s.label(700, 96, "4.8 V -> VM y servos", POWER)

    # Pi -> TB6612 (señales)
    s.line([(px + pw, 300), (bx, 300)], SIGNAL, 2.5, dash="6 5")
    s.arrow(bx, 300, SIGNAL)
    s.label(722, 286, "7 señales", SIGNAL)

    # Pi -> sensores
    s.line([(px + pw, 640), (722, 640), (722, 612), (bx, 612)], SIGNAL, 2.5, dash="6 5")
    s.arrow(bx, 612, SIGNAL)

    # TB6612 -> motores
    s.line([(bx + 182, 366), (bx + 182, 386)], ACCENT, 3)

    # ------------------------------------------------------------- divisor (!)
    dx, dy = 372, 764
    s.box(dx, dy, 316, 172, "(!) Divisor en cada ECHO",
          "obligatorio · 3 unidades", stroke=WARN)

    ex, ey = dx + 30, dy + 88
    s.line([(ex, ey), (ex + 70, ey)], WARN, 2.5)
    s.text(ex, ey - 12, "ECHO 5 V", fill=WARN, size=11)
    s.add(f'<rect x="{ex + 70}" y="{ey - 9}" width="46" height="18" rx="3" '
          f'fill="{PANEL}" stroke="{TEXT}" stroke-width="1.5"/>')
    s.text(ex + 93, ey + 4, "1 kΩ", fill=TEXT, size=10, anchor="middle")
    s.line([(ex + 116, ey), (ex + 186, ey)], SIGNAL, 2.5)
    s.text(ex + 190, ey + 4, "-> GPIO 3.3 V", fill=SIGNAL, size=11)

    s.line([(ex + 151, ey), (ex + 151, ey + 26)], GND, 2.5)
    s.add(f'<rect x="{ex + 128}" y="{ey + 26}" width="46" height="18" rx="3" '
          f'fill="{PANEL}" stroke="{TEXT}" stroke-width="1.5"/>')
    s.text(ex + 151, ey + 39, "2 kΩ", fill=TEXT, size=10, anchor="middle")
    s.line([(ex + 151, ey + 44), (ex + 151, ey + 62)], GND, 2.5)
    s.line([(ex + 137, ey + 62), (ex + 165, ey + 62)], GND, 2.5)
    s.line([(ex + 142, ey + 67), (ex + 160, ey + 67)], GND, 2)
    s.line([(ex + 147, ey + 72), (ex + 155, ey + 72)], GND, 2)

    s.text(dx + 14, dy + 156, "5 V x 2k/(1k+2k) = 3.33 V OK", fill=MUTED, size=11)

    # ------------------------------------------------------------------ avisos
    ax, ay = 756, 764
    y0 = s.box(ax, ay, bw, 172, "(!) Antes de conectar nada", "", stroke=WARN)
    avisos = [
        "Ajusta el XL4015 a 4.8 V con multímetro,",
        "desconectado de todo.",
        "",
        "La LiPo da 8.4 V y los motores son de 3 V:",
        "conectarla directa al VM los quema.",
        "",
        "Nunca USB-C y 5 V del header a la vez.",
        "Sin masa común, las señales flotan.",
    ]
    for i, linea in enumerate(avisos):
        if linea:
            s.text(ax + 14, y0 + i * 15, linea, fill=MUTED, size=11)

    # ----------------------------------------------------------------- leyenda
    ly = 764
    y0 = s.box(40, ly, 268, 172, "Leyenda", "")
    leyenda = [
        (POWER, "4.8 V — riel de potencia"),
        (LOGIC, "5 V — riel de lógica"),
        (SIGNAL, "señal GPIO 3.3 V"),
        (GND, "masa"),
        (ACCENT, "salida a motores"),
        (WARN, "requiere atención"),
    ]
    for i, (color, txt) in enumerate(leyenda):
        y = y0 + i * 21
        s.line([(58, y - 4), (92, y - 4)], color, 3)
        s.text(102, y, txt, fill=MUTED, size=11.5)

    s.text(
        40, H - 24,
        "Generado por tools/make_wiring_diagram.py · detalles en PLAN.md §4",
        fill=MUTED, size=11,
    )

    return s.render()


def main() -> int:
    out = Path(__file__).resolve().parent.parent / "docs" / "wiring.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(f"escrito {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
