"""Estabilizacion del mercado (requisito 20 aplicado a lineas y cuotas).

Las cuotas parpadean continuamente en directo, asi que exigir que se repitan
identicas seria inutil. Lo que se estabiliza es el CONJUNTO DE LINEAS: cuando
el mismo conjunto (por ejemplo 37.5 / 38.5 / 39.5 / 40.5) aparece varias veces
seguidas, el mercado se da por confirmado y se publican las cuotas de la
lectura mas reciente.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..domain.market import MarketKey, MarketSnapshot


def signature(snapshot: MarketSnapshot) -> Tuple:
    return (snapshot.key, tuple(round(ln.line, 2) for ln in snapshot.sorted_lines()))


@dataclass
class MarketChange:
    """Cambio detectado en el mercado, util para el historial (requisito 19)."""

    ts: float = field(default_factory=time.time)
    previous: Optional[MarketSnapshot] = None
    current: Optional[MarketSnapshot] = None
    reason: str = ""


class MarketTracker:
    """Confirma el mercado y detecta cambios de linea."""

    def __init__(self, required: int = 2, ttl: float = 8.0) -> None:
        self.required = max(1, int(required))
        self.ttl = float(ttl)
        self._confirmed: Optional[MarketSnapshot] = None
        self._pending_signature: Optional[Tuple] = None
        self._pending_count: int = 0
        self.last_change: Optional[MarketChange] = None
        self.last_raw: Optional[MarketSnapshot] = None

    @property
    def confirmed(self) -> Optional[MarketSnapshot]:
        return self._confirmed

    @property
    def progress(self) -> str:
        if self._pending_signature is None:
            return ""
        return f"{self._pending_count}/{self.required}"

    def current(self, now: Optional[float] = None) -> Optional[MarketSnapshot]:
        """Mercado vigente; caduca si hace demasiado que no se lee."""
        now = now if now is not None else time.time()
        if self._confirmed is None:
            return None
        if self.ttl > 0 and now - self._confirmed.timestamp > self.ttl:
            self._confirmed = None
        return self._confirmed

    def reset(self) -> None:
        self._confirmed = None
        self._pending_signature = None
        self._pending_count = 0

    def submit(self, snapshot: Optional[MarketSnapshot],
               now: Optional[float] = None) -> Optional[MarketSnapshot]:
        now = now if now is not None else time.time()
        if snapshot is None:
            return self.current(now)
        self.last_raw = snapshot

        if snapshot.is_empty:
            # Mercado desaparecido o suspendido: no se borra al instante, caduca.
            return self.current(now)

        sig = signature(snapshot)
        if self._confirmed is not None and sig == signature(self._confirmed):
            # Mismo conjunto de lineas: se refrescan las cuotas y la frescura.
            snapshot.timestamp = now
            self._confirmed = snapshot
            self._pending_signature = None
            self._pending_count = 0
            return self._confirmed

        if sig == self._pending_signature:
            self._pending_count += 1
        else:
            self._pending_signature = sig
            self._pending_count = 1

        if self._pending_count >= self.required:
            previous = self._confirmed
            snapshot.timestamp = now
            self._confirmed = snapshot
            self._pending_signature = None
            self._pending_count = 0
            self.last_change = MarketChange(
                ts=now, previous=previous, current=snapshot,
                reason="mercado inicial" if previous is None else "cambio de lineas",
            )
            return self._confirmed

        return self.current(now)
