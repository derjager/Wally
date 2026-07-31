"""Cajas de detección dibujadas sobre el frame.

Se dibuja en el servidor, antes de comprimir a JPEG, en lugar de superponer
SVG en el navegador. Dos motivos: el frame ya se va a codificar de todos modos,
así que dibujar encima sale casi gratis; y así el overlay aparece también en
`/snapshot.jpg` y en cualquier cliente, sin depender de que el visor sepa
alinear coordenadas con el vídeo.
"""

from __future__ import annotations

from services.vision.detector import Detection

# La gata se marca distinta del resto: es lo que se busca, no un mueble.
CAT_COLOR = (255, 138, 61)
OTHER_COLOR = (90, 220, 255)
TEXT_COLOR = (12, 14, 20)


def draw(rgb, detections: list[Detection], highlight: str = "cat"):
    """Dibuja las cajas sobre el array y lo devuelve.

    Recibe y devuelve un array RGB. Modifica una copia: el array original
    puede estar siendo leído por el hilo de inferencia.
    """
    if not detections:
        return rgb

    import numpy as np
    from PIL import Image, ImageDraw

    img = Image.fromarray(np.array(rgb))
    d = ImageDraw.Draw(img)
    w, h = img.size

    for det in detections:
        color = CAT_COLOR if det.label == highlight else OTHER_COLOR
        x0 = int(det.x * w)
        y0 = int(det.y * h)
        x1 = int((det.x + det.w) * w)
        y1 = int((det.y + det.h) * h)

        grosor = 3 if det.label == highlight else 2
        d.rectangle([x0, y0, x1, y1], outline=color, width=grosor)

        etiqueta = f"{det.label} {det.score:.0%}"
        tw = len(etiqueta) * 6 + 6
        # Si la caja está pegada al borde superior, la etiqueta va por dentro
        # para que no se salga del frame.
        ty = y0 - 12 if y0 >= 12 else y0 + 1
        d.rectangle([x0, ty, x0 + tw, ty + 11], fill=color)
        d.text((x0 + 3, ty + 1), etiqueta, fill=TEXT_COLOR)

    return np.asarray(img)
