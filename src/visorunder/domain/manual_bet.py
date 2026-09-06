"""Modelo de apuestas introducidas manualmente por el usuario.

Estas apuestas son independientes del lector OCR: sirven para registrar lo que
realmente se apuesta en cualquier casa, incluso si esa casa no esta abierta en
el perfil activo. Se persisten y se pueden liquidar como ganadas, perdidas,
nulas o dejarlas pendientes.

Lo IMPORTANTE de una apuesta manual es su seguimiento en vivo (mercado, linea,
puntos, margen y proyeccion), que calcula `calculations.manual_tracking`. El
monto es opcional justamente por eso: se puede seguir una apuesta sin haber
dicho cuanto se jugo. Si se indica, ademas entra en el conteo de utilidad y
ROI, que es informacion complementaria.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .market import MarketKey, Side


class ManualBetStatus(str, Enum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"

    @property
    def label(self) -> str:
        return {
            ManualBetStatus.PENDING: "PENDIENTE",
            ManualBetStatus.WON: "GANADA",
            ManualBetStatus.LOST: "PERDIDA",
            ManualBetStatus.VOID: "NULA",
        }[self]


@dataclass(frozen=True)
class ManualBet:
    sportsbook: str
    event: str
    key: MarketKey
    side: Side
    line: float
    odds: float
    #: Opcional. 0 significa "no lo dije", no "aposte cero".
    stake: float = 0.0
    status: ManualBetStatus = ManualBetStatus.PENDING
    placed_at: float = field(default_factory=time.time)
    settled_at: Optional[float] = None
    notes: str = ""
    session_id: Optional[int] = None
    bet_id: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.sportsbook.strip():
            raise ValueError("La casa de apuestas es obligatoria.")
        if self.odds <= 1.0:
            raise ValueError("La cuota debe ser mayor que 1.00.")
        if self.stake < 0:
            raise ValueError("El monto apostado no puede ser negativo.")
        if self.line < 0:
            raise ValueError("La linea no puede ser negativa.")

    @property
    def has_stake(self) -> bool:
        """True si se indico un monto. Sin monto no hay utilidad que contar."""
        return self.stake > 0

    @property
    def profit(self) -> Optional[float]:
        """Ganancia neta. Pendiente o sin monto -> None; nula -> 0."""
        if self.status is ManualBetStatus.PENDING or not self.has_stake:
            return None
        if self.status is ManualBetStatus.WON:
            return self.stake * (self.odds - 1.0)
        if self.status is ManualBetStatus.LOST:
            return -self.stake
        return 0.0

    @property
    def description(self) -> str:
        return f"{self.side.value} {self.line:g} @ {self.odds:.2f}"


@dataclass(frozen=True)
class ManualBetSummary:
    total: int = 0
    pending: int = 0
    won: int = 0
    lost: int = 0
    void: int = 0
    total_staked: float = 0.0
    resolved_stake: float = 0.0
    net_profit: float = 0.0

    @property
    def hit_rate(self) -> Optional[float]:
        decisions = self.won + self.lost
        return (self.won / decisions * 100.0) if decisions else None

    @property
    def roi(self) -> Optional[float]:
        return (self.net_profit / self.resolved_stake * 100.0) if self.resolved_stake else None
