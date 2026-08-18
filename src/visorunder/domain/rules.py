"""Reglas temporales del partido (requisito 10).

El motor temporal esta parametrizado para poder ampliarse: FIBA (4x10),
NBA (4x12) y cualquier variante futura, incluida la PRORROGA (requisito 32).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class GameRules:
    """Duraciones del partido, en SEGUNDOS.

    regulation_quarters: cuartos de tiempo reglamentario (4 en baloncesto).
    quarter_seconds:     duracion de cada cuarto reglamentario.
    overtime_seconds:    duracion de cada prorroga.
    """

    name: str = "FIBA"
    regulation_quarters: int = 4
    quarter_seconds: int = 10 * 60
    overtime_seconds: int = 5 * 60

    @property
    def regulation_seconds(self) -> int:
        """Duracion total del tiempo reglamentario."""
        return self.regulation_quarters * self.quarter_seconds

    @property
    def halftime_after_period(self) -> int:
        """Numero de periodo tras el cual llega el descanso largo."""
        return self.regulation_quarters // 2

    def period_seconds(self, period: int) -> int:
        """Duracion del periodo dado. period 1..N reglamentario, >N prorroga."""
        if period <= 0:
            raise ValueError(f"periodo invalido: {period}")
        if period <= self.regulation_quarters:
            return self.quarter_seconds
        return self.overtime_seconds

    def is_overtime(self, period: int) -> bool:
        return period > self.regulation_quarters

    def seconds_before_period(self, period: int) -> int:
        """Tiempo de juego acumulado ANTES de que empiece el periodo dado."""
        if period <= 0:
            raise ValueError(f"periodo invalido: {period}")
        total = 0
        for p in range(1, period):
            total += self.period_seconds(p)
        return total

    def label(self, period: int) -> str:
        """Etiqueta legible: Q1..Q4, OT1, OT2..."""
        if self.is_overtime(period):
            return f"OT{period - self.regulation_quarters}"
        return f"Q{period}"


FIBA = GameRules(name="FIBA", regulation_quarters=4, quarter_seconds=10 * 60, overtime_seconds=5 * 60)
NBA = GameRules(name="NBA", regulation_quarters=4, quarter_seconds=12 * 60, overtime_seconds=5 * 60)

PRESETS: Dict[str, GameRules] = {"FIBA": FIBA, "NBA": NBA}


def preset_names() -> List[str]:
    return list(PRESETS.keys())


def rules_from_name(name: str) -> GameRules:
    """Devuelve un preset por nombre; FIBA por defecto."""
    return PRESETS.get((name or "").upper(), FIBA)
