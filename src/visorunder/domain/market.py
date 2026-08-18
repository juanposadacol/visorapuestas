"""Modelo de mercado y lineas (requisitos 5, 6, 14).

Dos ideas centrales:

1) UNA LINEA SIEMPRE VA ATADA A SU MERCADO.
   Nunca se asume que la linea visible corresponde al cuarto que se juega.
   Si el partido va Q2 00:04 y la casa muestra "3.er cuarto - Total de puntos
   40.5", esa linea queda registrada con quarter=3 y jamas se usa para Q2.

2) EL MERCADO DECIDE QUE SE ACUMULA Y QUE TIEMPO QUEDA.
   `MarketScope` es la capa generica: dado un mercado devuelve el acumulador
   de puntos y los segundos restantes aplicables. Anadir un mercado nuevo
   (mitad, prorroga...) es anadir un caso aqui, no tocar las metricas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class MarketType(str, Enum):
    """Tipos de mercado soportados. Extensible sin romper el resto."""

    QUARTER_TOTAL = "QUARTER_TOTAL"  # "3.er cuarto - Total de puntos"
    HALF_TOTAL = "HALF_TOTAL"        # "1.a mitad - Total de puntos"
    GAME_TOTAL = "GAME_TOTAL"        # "Partido - Total de puntos"

    @property
    def display_name(self) -> str:
        return {
            MarketType.QUARTER_TOTAL: "Total de puntos (cuarto)",
            MarketType.HALF_TOTAL: "Total de puntos (mitad)",
            MarketType.GAME_TOTAL: "Total de puntos (partido)",
        }[self]


class Side(str, Enum):
    OVER = "OVER"
    UNDER = "UNDER"


@dataclass(frozen=True)
class MarketKey:
    """Identidad de un mercado concreto.

    period: numero de cuarto (1..4, >4 prorroga) para QUARTER_TOTAL.
    half:   1 o 2 para HALF_TOTAL.
    Ambos None para GAME_TOTAL.
    """

    market_type: MarketType
    period: Optional[int] = None
    half: Optional[int] = None

    def __post_init__(self) -> None:
        if self.market_type is MarketType.QUARTER_TOTAL and self.period is None:
            raise ValueError("QUARTER_TOTAL requiere periodo")
        if self.market_type is MarketType.HALF_TOTAL and self.half is None:
            raise ValueError("HALF_TOTAL requiere mitad")

    @property
    def label(self) -> str:
        if self.market_type is MarketType.QUARTER_TOTAL:
            return f"Q{self.period} - Total de puntos"
        if self.market_type is MarketType.HALF_TOTAL:
            return f"{self.half}.a mitad - Total de puntos"
        return "Partido - Total de puntos"

    @staticmethod
    def quarter(period: int) -> "MarketKey":
        return MarketKey(MarketType.QUARTER_TOTAL, period=period)

    @staticmethod
    def half_market(half: int) -> "MarketKey":
        return MarketKey(MarketType.HALF_TOTAL, half=half)

    @staticmethod
    def game() -> "MarketKey":
        return MarketKey(MarketType.GAME_TOTAL)


@dataclass(frozen=True)
class MarketLine:
    """Una linea concreta ofrecida por la casa.

    Campos minimos exigidos por el requisito 6: sportsbook, event, market_type,
    quarter, line, over_odds, under_odds, timestamp.
    """

    sportsbook: str
    event: str
    key: MarketKey
    line: float
    over_odds: Optional[float] = None
    under_odds: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    confirmed: bool = False
    raw_text: str = ""

    @property
    def market_type(self) -> MarketType:
        return self.key.market_type

    @property
    def quarter(self) -> Optional[int]:
        return self.key.period

    def identity(self) -> tuple:
        """Identidad estable de la linea dentro de un mercado (sin cuotas)."""
        return (self.sportsbook, self.event, self.key, round(self.line, 2))

    def describe_under(self) -> str:
        odds = f"{self.under_odds:.2f}" if self.under_odds is not None else "--"
        return f"UNDER {self.line:g} @ {odds}"

    def describe_over(self) -> str:
        odds = f"{self.over_odds:.2f}" if self.over_odds is not None else "--"
        return f"OVER {self.line:g} @ {odds}"


@dataclass
class MarketSnapshot:
    """Conjunto de lineas leidas en un instante para un mercado.

    Una casa puede ofrecer una unica linea o varias simultaneas; el modelo
    siempre es una lista (requisito 6).
    """

    key: Optional[MarketKey] = None
    lines: List[MarketLine] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    suspended: bool = False
    raw_text: str = ""

    def under_lines(self) -> List[MarketLine]:
        return [ln for ln in self.lines if ln.under_odds is not None]

    def find(self, line_value: float) -> Optional[MarketLine]:
        for ln in self.lines:
            if abs(ln.line - line_value) < 1e-6:
                return ln
        return None

    def sorted_lines(self) -> List[MarketLine]:
        return sorted(self.lines, key=lambda ln: ln.line)

    @property
    def is_empty(self) -> bool:
        return not self.lines
