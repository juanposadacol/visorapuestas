"""Estado de TODOS los mercados de un mismo partido.

La casa reparte sus mercados en pestanas: Partido, 1.a mitad, 2.a mitad, Q1..Q4.
Como la aplicacion lee la pantalla, en cada instante solo puede observar la
pestana visible. Este modulo reune todo en un unico radar SIN mentir sobre la
frescura de cada pieza.

Estructura, tal y como se acordo:

    EVENTO
      -> MERCADOS   (uno por MarketKey)
           -> MULTIPLES LINEAS

Cada mercado conserva su ultima lectura con su marca de tiempo. Una linea vieja
nunca se presenta como actual: se muestra con su antiguedad y su estado.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional

from ..config.freshness import FreshnessCriteria
from .market import MarketKey, MarketLine, MarketSnapshot, MarketType


class FreshnessState(str, Enum):
    """Cuanto se puede confiar en que lo mostrado es lo que ofrece la casa."""

    LIVE = "LIVE"                # visible y confirmado ahora mismo
    RECENT = "RECENT"            # no visible, pero leido hace muy poco
    STALE = "STALE"              # hace demasiado que no se observa
    REVIEWING = "REVIEWING"      # visible con una lectura pendiente de confirmar
    UNAVAILABLE = "UNAVAILABLE"  # sin datos suficientes

    @property
    def label(self) -> str:
        return {
            FreshnessState.LIVE: "EN VIVO",
            FreshnessState.RECENT: "RECIENTE",
            FreshnessState.STALE: "DESACTUALIZADO",
            FreshnessState.REVIEWING: "EN REVISION",
            FreshnessState.UNAVAILABLE: "NO DISPONIBLE",
        }[self]

    @property
    def is_trustworthy_now(self) -> bool:
        """True solo si lo mostrado puede tomarse como la oferta actual."""
        return self is FreshnessState.LIVE


@dataclass
class MarketState:
    """Un mercado del evento con su ultima lectura y su frescura."""

    key: MarketKey
    snapshot: Optional[MarketSnapshot] = None
    visible: bool = False
    under_review: bool = False
    pending_lines: tuple = ()
    #: Ultima vez que la casa mostro este mercado y se pudo leer.
    last_seen_at: Optional[float] = None
    #: Ultima vez que su conjunto de lineas quedo confirmado.
    last_confirmed_at: Optional[float] = None
    suspended: bool = False

    # ------------------------------------------------------------- consultas
    @property
    def lines(self) -> List[MarketLine]:
        return self.snapshot.sorted_lines() if self.snapshot else []

    @property
    def has_lines(self) -> bool:
        return bool(self.lines)

    @property
    def label(self) -> str:
        return self.key.label

    def age_seconds(self, now: Optional[float] = None) -> Optional[float]:
        """Antiguedad de la ultima observacion, en segundos."""
        if self.last_seen_at is None:
            return None
        return max(0.0, (now if now is not None else time.time()) - self.last_seen_at)

    def freshness(self, criteria: FreshnessCriteria,
                  now: Optional[float] = None) -> FreshnessState:
        """Estado DERIVADO de la visibilidad y de la antiguedad.

        No se almacena: se calcula, para que no pueda quedar desincronizado.
        """
        now = now if now is not None else time.time()
        if self.under_review:
            return FreshnessState.REVIEWING
        if not self.has_lines:
            return FreshnessState.UNAVAILABLE
        age = self.age_seconds(now)
        if age is None:
            return FreshnessState.UNAVAILABLE
        if criteria.forget_after_seconds and age > criteria.forget_after_seconds:
            return FreshnessState.UNAVAILABLE
        # Se conserva la ultima lectura para mostrar su antiguedad, pero una
        # observacion explicita de `lines=[]` significa que ya no es actual.
        if self.suspended:
            return FreshnessState.STALE
        if self.visible and age <= criteria.recent_after_seconds:
            return FreshnessState.LIVE
        if age <= criteria.stale_after_seconds:
            return FreshnessState.RECENT
        return FreshnessState.STALE

    def describe_age(self, now: Optional[float] = None) -> str:
        age = self.age_seconds(now)
        if age is None:
            return "sin lecturas"
        if age < 1.5:
            return "ahora"
        if age < 90:
            return f"hace {int(age)} s"
        return f"hace {int(age // 60)} min"


@dataclass
class EventMarkets:
    """Registro de todos los mercados observados del partido en curso."""

    markets: Dict[MarketKey, MarketState] = field(default_factory=dict)
    #: Mercado que la casa esta mostrando ahora, si se conoce.
    visible_key: Optional[MarketKey] = None

    # ------------------------------------------------------------ escritura
    def get(self, key: MarketKey) -> Optional[MarketState]:
        return self.markets.get(key)

    def ensure(self, key: MarketKey) -> MarketState:
        state = self.markets.get(key)
        if state is None:
            state = MarketState(key=key)
            self.markets[key] = state
        return state

    def observe(self, key: MarketKey, snapshot: Optional[MarketSnapshot], *,
                confirmed: bool, under_review: bool = False,
                pending_lines: tuple = (), now: Optional[float] = None,
                set_as_only_visible: bool = True) -> MarketState:
        """Registra que se ha observado `key` en pantalla.

        `snapshot` solo se guarda cuando la lectura esta CONFIRMADA: asi una
        lectura a medio validar no puede sustituir a la que ya se publicaba.
        """
        now = now if now is not None else time.time()
        state = self.ensure(key)
        state.last_seen_at = now
        state.under_review = under_review
        state.pending_lines = pending_lines
        if confirmed and snapshot is not None:
            state.snapshot = snapshot
            state.last_confirmed_at = now
            state.suspended = snapshot.suspended
        if set_as_only_visible:
            self.set_visible(key)
        return state

    def set_visible(self, key: Optional[MarketKey]) -> None:
        """Marca que mercado esta a la vista. Solo puede haber uno."""
        self.visible_key = key
        for market_key, state in self.markets.items():
            state.visible = (market_key == key)
            if not state.visible:
                # Un mercado que ya no se ve no puede estar 'en revision':
                # nadie lo esta validando.
                state.under_review = False
                state.pending_lines = ()

    def set_visible_many(self, keys: Iterable[MarketKey],
                         primary: Optional[MarketKey] = None) -> None:
        """Marca varias ofertas visibles a la vez en la vista TODO."""
        visibles = set(keys)
        self.visible_key = primary if primary in visibles else next(iter(visibles), None)
        for market_key, state in self.markets.items():
            state.visible = market_key in visibles
            if not state.visible:
                state.under_review = False
                state.pending_lines = ()

    def mark_suspended(self, key: MarketKey, now: Optional[float] = None,
                       set_as_only_visible: bool = True) -> MarketState:
        """Mercado visible sin lineas actuales; preserva la ultima buena."""
        state = self.ensure(key)
        state.suspended = True
        state.under_review = False
        state.pending_lines = ()
        state.last_seen_at = now if now is not None else time.time()
        if set_as_only_visible:
            self.set_visible(key)
        return state

    def clear(self) -> None:
        self.markets.clear()
        self.visible_key = None

    # ------------------------------------------------------------- consultas
    @property
    def visible(self) -> Optional[MarketState]:
        return self.markets.get(self.visible_key) if self.visible_key else None

    def all_states(self) -> List[MarketState]:
        """Mercados ordenados de forma estable para la interfaz."""
        return sorted(self.markets.values(), key=lambda s: _ordering(s.key))

    def with_lines(self) -> List[MarketState]:
        return [state for state in self.all_states() if state.has_lines]

    def total_lines(self) -> int:
        return sum(len(state.lines) for state in self.markets.values())

    def keys(self) -> Iterable[MarketKey]:
        return self.markets.keys()

    def __len__(self) -> int:
        return len(self.markets)

    def __contains__(self, key: object) -> bool:
        return key in self.markets


def _ordering(key: MarketKey) -> tuple:
    """Orden de presentacion: partido, mitades y luego cuartos."""
    if key.market_type is MarketType.GAME_TOTAL:
        return (0, 0)
    if key.market_type is MarketType.HALF_TOTAL:
        return (1, key.half or 0)
    return (2, key.period or 0)
