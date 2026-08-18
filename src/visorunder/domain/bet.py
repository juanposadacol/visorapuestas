"""Modelo de "MI APUESTA" (requisitos 7 y 28).

Una vez fijada, la apuesta es INMUTABLE. Aunque la casa mueva su linea de
UNDER 40.5 a UNDER 42.5, todos los calculos siguen haciendose contra 40.5.
Por eso la dataclass es `frozen=True`: es imposible mutarla por accidente.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .market import MarketKey, MarketLine, Side


@dataclass(frozen=True)
class LockedBet:
    """Apuesta congelada por el usuario al pulsar FIJAR APUESTA."""

    sportsbook: str
    event: str
    key: MarketKey
    side: Side
    line: float
    odds: Optional[float]
    placed_at: float = field(default_factory=time.time)
    score_a_when_locked: Optional[int] = None
    score_b_when_locked: Optional[int] = None
    clock_when_locked: Optional[int] = None
    period_when_locked: Optional[int] = None
    session_id: Optional[int] = None
    bet_id: Optional[int] = None

    @property
    def market_type(self):
        return self.key.market_type

    @property
    def quarter(self) -> Optional[int]:
        return self.key.period

    def describe(self) -> str:
        odds = f"{self.odds:.2f}" if self.odds is not None else "--"
        return f"{self.side.value} {self.line:g} @ {odds}"

    def describe_full(self) -> str:
        return f"{self.key.label} | {self.describe()}"

    @staticmethod
    def from_line(line: MarketLine, side: Side, *, score_a: Optional[int] = None,
                  score_b: Optional[int] = None, clock_seconds: Optional[int] = None,
                  period: Optional[int] = None, session_id: Optional[int] = None) -> "LockedBet":
        odds = line.under_odds if side is Side.UNDER else line.over_odds
        return LockedBet(
            sportsbook=line.sportsbook,
            event=line.event,
            key=line.key,
            side=side,
            line=float(line.line),
            odds=odds,
            score_a_when_locked=score_a,
            score_b_when_locked=score_b,
            clock_when_locked=clock_seconds,
            period_when_locked=period,
            session_id=session_id,
        )
