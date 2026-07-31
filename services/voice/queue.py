"""Cola de frases pendientes de decir.

Dos problemas que resuelve, ambos aprendidos de cómo se comportan los robots
parlanchines cuando no se controla esto:

- **Repetición.** Si el robot avisa de un obstáculo a 15 Hz, repetirá la misma
  frase veinte veces mientras se acerca a una pared. Se descartan los
  duplicados recientes.
- **Acumulación.** Si llegan frases más rápido de lo que se tarda en decirlas,
  la cola crece sin fin y el robot va comentando cosas de hace un minuto. Al
  llenarse se tiran las más viejas, no las nuevas: lo reciente es lo relevante.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(order=True)
class Utterance:
    # `urgent` va primero en el orden; se guarda negado para que un valor
    # menor signifique más prioridad.
    _rank: int = field(init=False, repr=False)
    text: str = field(compare=False)
    urgent: bool = field(default=False, compare=False)
    ts: float = field(default=0.0, compare=False)

    def __post_init__(self) -> None:
        self._rank = 0 if self.urgent else 1


class SpeechQueue:
    def __init__(self, max_size: int = 12, dedupe_window_s: float = 8.0) -> None:
        self._items: deque[Utterance] = deque()
        self._max = max_size
        self._window = dedupe_window_s
        self._recent: dict[str, float] = {}
        self.dropped_duplicates = 0
        self.dropped_overflow = 0

    def push(self, text: str, now: float, urgent: bool = False) -> bool:
        """Encola una frase. Devuelve False si se descartó."""
        text = text.strip()
        if not text:
            return False

        last = self._recent.get(text)
        if last is not None and now - last < self._window and not urgent:
            self.dropped_duplicates += 1
            return False

        self._recent[text] = now
        self._prune_recent(now)

        item = Utterance(text=text, urgent=urgent, ts=now)

        if urgent:
            # Lo urgente se salta la cola, pero detrás de otros urgentes ya
            # encolados, para no invertir su orden entre sí.
            insert_at = 0
            while insert_at < len(self._items) and self._items[insert_at].urgent:
                insert_at += 1
            self._items.insert(insert_at, item)
        else:
            self._items.append(item)

        while len(self._items) > self._max:
            # Se descarta lo más antiguo no urgente; si todo es urgente, lo
            # más antiguo a secas. El índice más bajo es el más antiguo: al
            # desbordar hay que perder lo viejo, no lo que acaba de llegar.
            victim = next(
                (i for i in range(len(self._items)) if not self._items[i].urgent),
                0,
            )
            del self._items[victim]
            self.dropped_overflow += 1

        return True

    def pop(self) -> Utterance | None:
        return self._items.popleft() if self._items else None

    def clear(self) -> None:
        self._items.clear()

    def _prune_recent(self, now: float) -> None:
        expirados = [t for t, ts in self._recent.items() if now - ts > self._window]
        for t in expirados:
            del self._recent[t]

    def __len__(self) -> int:
        return len(self._items)
