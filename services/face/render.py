"""Dibujo de la cara sobre una superficie de pygame.

Todo se dibuja en el lienzo lógico pequeño (160×106) y luego se escala por un
factor **entero** con vecino más cercano. Ese es el truco que produce el pixel
art: escalar por 3.0 exacto da bloques cuadrados nítidos, mientras que un
escalado fraccionario o suavizado emborrona los bordes y arruina el estilo.

Por la misma razón no hay antialiasing en ninguna primitiva: las esquinas se
achaflanan a mano, quitando píxeles, como se haría en un sprite.
"""

from __future__ import annotations

import math

import pygame

from services.face.expressions import BG, EYE, EYE_DIM, EYE_SHINE, MOUTH, Expression


def _chamfer_rect(surf: pygame.Surface, color, x: int, y: int, w: int, h: int,
                  r: int) -> None:
    """Rectángulo con las esquinas recortadas.

    Es el redondeo del pixel art: dos rectángulos cruzados dejan las cuatro
    esquinas vacías sin generar un solo píxel a medio tono.
    """
    if w <= 0 or h <= 0:
        return
    r = max(0, min(r, w // 2, h // 2))
    if r == 0:
        pygame.draw.rect(surf, color, (x, y, w, h))
        return
    pygame.draw.rect(surf, color, (x + r, y, w - 2 * r, h))
    pygame.draw.rect(surf, color, (x, y + r, w, h - 2 * r))


def _eye_metrics(expr: Expression, w: int, h: int, side: int):
    """Geometría de un ojo. `side` es -1 (izquierdo) o +1 (derecho)."""
    # La asimetría encoge un ojo y agranda el otro. Es lo que hace legible la
    # curiosidad: una ceja levantada, no dos párpados torcidos.
    factor = 1.0 + expr.asym * (0.35 if side < 0 else -0.35)

    ew = max(3, int(expr.eye_width * w))
    eh = max(3, int(expr.eye_height * h * factor))
    gap = expr.eye_gap * w
    cx = w / 2 + side * (gap / 2 + ew / 2)
    cy = expr.eye_y * h + expr.tilt * side * h * 0.5
    return int(cx - ew / 2), int(cy - eh / 2), ew, eh


def _draw_eye(surf: pygame.Surface, expr: Expression, w: int, h: int, side: int,
              look_x: float, look_y: float) -> None:
    x, y, ew, eh = _eye_metrics(expr, w, h, side)

    # Desplazamiento de la mirada, acotado para que el ojo no se salga.
    x += int(look_x * ew * 0.22)
    y += int(look_y * eh * 0.18)

    if expr.curve > 0.05:
        # Ojos arqueados. Se dibuja como columnas de altura variable para
        # conservar el escalonado; una elipse suavizada rompería el estilo.
        thickness = max(3, int(eh * 0.62))
        for i in range(ew):
            t = i / max(1, ew - 1)
            dip = math.sin(t * math.pi)
            top = y + int((1.0 - dip) * eh * 0.7 * expr.curve)
            pygame.draw.rect(surf, EYE, (x + i, top, 1, thickness))
        return

    radius = 2 if min(ew, eh) >= 10 else 1
    _chamfer_rect(surf, EYE, x, y, ew, eh, radius)

    if expr.pupil > 0.05:
        # "Pupila": un hueco más oscuro que estrecha la mancha del ojo.
        pw = max(2, int(ew * (1.0 - expr.pupil) * 0.6))
        ph = max(2, int(eh * (1.0 - expr.pupil) * 0.6))
        _chamfer_rect(
            surf, EYE_DIM,
            x + (ew - pw) // 2, y + (eh - ph) // 2, pw, ph,
            1,
        )

    # Brillo arriba a la izquierda. Un par de píxeles que cambian por completo
    # la sensación de que el ojo está vivo.
    if expr.shine > 0.3 and ew >= 8 and eh >= 8:
        sw = max(2, ew // 4)
        sh = max(2, eh // 5)
        pygame.draw.rect(surf, EYE_SHINE, (x + 2, y + 2, sw, sh))

    # Párpado: un bloque de fondo que baja desde arriba.
    if expr.lid > 0.01:
        lid_h = int(eh * min(1.0, expr.lid))
        if lid_h <= 0:
            return
        if abs(expr.lid_angle) < 0.02:
            pygame.draw.rect(surf, BG, (x, y - 1, ew, lid_h + 1))
        else:
            # Párpado inclinado. Con lid_angle negativo, el borde baja hacia
            # el centro de la cara: es la forma en "V" del ceño fruncido.
            for i in range(ew):
                t = i / max(1, ew - 1)
                hacia_dentro = t if side < 0 else (1.0 - t)
                rampa = hacia_dentro if expr.lid_angle < 0 else (1.0 - hacia_dentro)
                extra = int(rampa * abs(expr.lid_angle) * eh)
                pygame.draw.rect(surf, BG, (x + i, y - 1, 1, lid_h + extra + 1))


def _draw_mouth(surf: pygame.Surface, expr: Expression, w: int, h: int) -> None:
    if expr.mouth_width <= 0.01:
        return

    mw = max(3, int(expr.mouth_width * w))
    x = (w - mw) // 2
    y = int(h * 0.70)

    if expr.mouth_open > 0.05:
        mh = max(2, int(expr.mouth_open * h * 0.16))
        _chamfer_rect(surf, MOUTH, x, y, mw, mh, 1)
        return

    # Boca cerrada: una línea gruesa, curvada según el ánimo.
    thickness = 2
    for i in range(mw):
        t = i / max(1, mw - 1)
        dip = math.sin(t * math.pi) * expr.mouth_curve * h * 0.07
        pygame.draw.rect(surf, MOUTH, (x + i, y - int(dip), 1, thickness))


def draw(surface: pygame.Surface, expr: Expression,
         look_x: float = 0.0, look_y: float = 0.0) -> None:
    """Dibuja la cara completa en el lienzo lógico."""
    w, h = surface.get_size()
    surface.fill(BG)
    _draw_eye(surface, expr, w, h, -1, look_x, look_y)
    _draw_eye(surface, expr, w, h, +1, look_x, look_y)
    _draw_mouth(surface, expr, w, h)


def present(screen: pygame.Surface, canvas: pygame.Surface) -> None:
    """Escala el lienzo a la pantalla y lo centra.

    El factor de escala es entero a propósito. Con 480×320 de pantalla y un
    lienzo de 160×106 sale ×3 (480×318), y los 2 píxeles sobrantes quedan como
    borde negro, invisible sobre un fondo oscuro. Estirar hasta llenar daría
    píxeles rectangulares y bordes borrosos.
    """
    sw, sh = screen.get_size()
    cw, ch = canvas.get_size()
    scale = max(1, min(sw // cw, sh // ch))

    scaled = pygame.transform.scale(canvas, (cw * scale, ch * scale))
    screen.fill(BG)
    screen.blit(scaled, ((sw - cw * scale) // 2, (sh - ch * scale) // 2))
    pygame.display.flip()
