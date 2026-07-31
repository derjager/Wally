"""Expresiones de la cara de Wally.

Las expresiones son **geometría con parámetros**, no sprites en disco. Eso
permite interpolar entre dos estados de ánimo y obtener una transición suave —
con sprites habría que dibujar cada fotograma intermedio a mano — y además
mantiene el proyecto sin archivos binarios que versionar.

El estilo pixel art sale del tamaño del lienzo: se dibuja en 160×106 y se
escala por un factor entero, así que cada "píxel" acaba siendo un bloque
nítido de 3×3 en la pantalla de 3.5 pulgadas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

# Paleta. Pocos colores, muy contrastados: es lo que hace legible una cara a
# esta resolución y a un metro de distancia.
BG = (12, 14, 20)
EYE = (90, 220, 255)
EYE_DIM = (40, 110, 135)
# El brillo es lo que más "vida" añade por píxel gastado: sin él los ojos
# parecen bloques de color; con él, algo que mira.
EYE_SHINE = (215, 248, 255)
MOUTH = (90, 220, 255)
ACCENT = (255, 140, 60)


@dataclass(frozen=True)
class Expression:
    """Parámetros geométricos de una cara.

    Todos son proporciones (0..1) o factores relativos, de modo que la cara se
    adapta si cambia la resolución lógica.
    """

    eye_width: float = 0.17      # anchura del ojo respecto al lienzo
    eye_height: float = 0.26     # altura del ojo
    eye_gap: float = 0.18        # separación entre ojos
    eye_y: float = 0.40          # centro vertical de los ojos
    lid: float = 0.0             # 0 = abierto, 1 = cerrado del todo
    lid_angle: float = 0.0       # inclinación del párpado; negativo = enfadado
    curve: float = 0.0           # curvatura inferior; >0 = ojos sonrientes
    pupil: float = 0.0           # 0 = ojo lleno, 1 = pupila pequeña
    # Asimetría entre ojos. Una ceja levantada dice "curiosidad" mucho mejor
    # que dos ojos idénticos con el párpado torcido.
    asym: float = 0.0
    shine: float = 1.0           # brillo del ojo; 0 lo apaga
    mouth_width: float = 0.0     # 0 = sin boca
    mouth_open: float = 0.0
    mouth_curve: float = 0.0     # >0 sonrisa, <0 tristeza
    tilt: float = 0.0            # inclinación de la cara entera


# El nombre del estado es lo que viaja por MQTT en wally/cmd/mood.
EXPRESSIONS: dict[str, Expression] = {
    # Reposo atento: ojos grandes y tranquilos.
    "idle": Expression(),

    # Contento: ojos arqueados hacia arriba, el gesto universal de alegría.
    "happy": Expression(
        eye_height=0.17, curve=0.95, shine=0.0,
        mouth_width=0.26, mouth_curve=1.0,
    ),

    # Curioso: un ojo bastante más abierto que el otro, cabeza ladeada.
    "curious": Expression(
        eye_height=0.27, asym=0.45, tilt=0.05, pupil=0.3,
        mouth_width=0.10, mouth_curve=0.3,
    ),

    # Alerta: ojos muy abiertos, pupila contraída.
    "alert": Expression(
        eye_width=0.20, eye_height=0.32, pupil=0.5,
        mouth_width=0.14, mouth_open=0.45,
    ),

    # Adormilado: párpados a media asta.
    "sleepy": Expression(
        eye_height=0.24, lid=0.66, shine=0.0,
        mouth_width=0.10, mouth_curve=-0.15,
    ),

    # Teleoperado: mirada de foco, ojos algo estrechos.
    "teleop": Expression(eye_width=0.15, eye_height=0.21, pupil=0.45),

    # Enfadado o error: párpados inclinados hacia el centro.
    "grumpy": Expression(
        eye_height=0.24, lid=0.36, lid_angle=-0.7, shine=0.0,
        mouth_width=0.22, mouth_curve=-0.75,
    ),

    # Sorpresa.
    "surprised": Expression(
        eye_width=0.21, eye_height=0.34, pupil=0.18,
        mouth_width=0.13, mouth_open=0.95,
    ),
}

DEFAULT_MOOD = "idle"


def get(mood: str) -> Expression:
    return EXPRESSIONS.get(mood, EXPRESSIONS[DEFAULT_MOOD])


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ease(t: float) -> float:
    """Suavizado en ambos extremos.

    Una transición lineal entre expresiones se ve mecánica; arrancar y frenar
    despacio es lo que la hace parecer un gesto y no un salto de valores.
    """
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def blend(a: Expression, b: Expression, t: float) -> Expression:
    """Mezcla dos expresiones. `t=0` devuelve `a`; `t=1`, `b`."""
    t = ease(t)
    return Expression(
        eye_width=lerp(a.eye_width, b.eye_width, t),
        eye_height=lerp(a.eye_height, b.eye_height, t),
        eye_gap=lerp(a.eye_gap, b.eye_gap, t),
        eye_y=lerp(a.eye_y, b.eye_y, t),
        lid=lerp(a.lid, b.lid, t),
        lid_angle=lerp(a.lid_angle, b.lid_angle, t),
        curve=lerp(a.curve, b.curve, t),
        pupil=lerp(a.pupil, b.pupil, t),
        asym=lerp(a.asym, b.asym, t),
        shine=lerp(a.shine, b.shine, t),
        mouth_width=lerp(a.mouth_width, b.mouth_width, t),
        mouth_open=lerp(a.mouth_open, b.mouth_open, t),
        mouth_curve=lerp(a.mouth_curve, b.mouth_curve, t),
        tilt=lerp(a.tilt, b.tilt, t),
    )


def with_blink(expr: Expression, amount: float) -> Expression:
    """Aplica un parpadeo sobre cualquier expresión.

    Se compone en vez de sustituir para que el robot pueda parpadear estando
    contento o alerta sin perder ese gesto.
    """
    return replace(expr, lid=max(expr.lid, amount))


def with_speech(expr: Expression, phase: float, speaking: bool) -> Expression:
    """Anima la boca mientras habla.

    Es una oscilación, no sincronía real con los fonemas: a esta resolución la
    diferencia no se aprecia, y evita tener que analizar el audio.
    """
    if not speaking:
        return expr
    openness = 0.35 + 0.45 * abs(math.sin(phase * math.pi * 2.0))
    return replace(
        expr,
        mouth_width=max(expr.mouth_width, 0.16),
        mouth_open=openness,
    )


def blink_curve(t: float) -> float:
    """Perfil de un parpadeo, con `t` de 0 a 1 a lo largo del gesto.

    Baja rápido y sube algo más lento, como un párpado de verdad.
    """
    if t <= 0.0 or t >= 1.0:
        return 0.0
    if t < 0.45:
        return t / 0.45
    return 1.0 - (t - 0.45) / 0.55
