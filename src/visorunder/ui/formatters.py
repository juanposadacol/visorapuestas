"""Formateo para la interfaz (requisito 33).

Regla unica y estricta: si un dato no es fiable, se escribe "--".
Aqui no se redondea nada que pueda confundir ni se rellena con ceros.
"""

from __future__ import annotations

import math
from typing import Optional

from ..calculations.metrics import HALFTIME_PASSED, IMPOSSIBLE
from ..domain.time_utils import seconds_to_clock

UNKNOWN = "--"
HALFTIME_TEXT = "YA PASO"
NOT_AVAILABLE = "NO DISPONIBLE"


def num(value: Optional[float], decimals: int = 0, suffix: str = "") -> str:
    if value is None:
        return UNKNOWN
    if isinstance(value, float) and math.isinf(value):
        return "IMPOSIBLE"
    text = f"{value:.{decimals}f}" if decimals else f"{int(round(value))}"
    return f"{text}{suffix}"


def integer(value: Optional[int]) -> str:
    return UNKNOWN if value is None else str(int(value))


def clock(seconds: Optional[int]) -> str:
    return UNKNOWN if seconds is None else seconds_to_clock(seconds)


def pace(value: Optional[float]) -> str:
    """Puntos por minuto con dos decimales."""
    if value is None:
        return UNKNOWN
    if math.isinf(value):
        return "IMPOSIBLE"
    return f"{value:.2f} pts/min"


def odds(value: Optional[float]) -> str:
    return UNKNOWN if value is None else f"{value:.2f}"


def line(value: Optional[float]) -> str:
    return UNKNOWN if value is None else f"{value:g}"


def halftime(seconds: Optional[int]) -> str:
    """Requisito 15: puede ser desconocido, un tiempo, o 'YA PASO'."""
    if seconds is None:
        return UNKNOWN
    if seconds == HALFTIME_PASSED:
        return HALFTIME_TEXT
    return seconds_to_clock(seconds)


def text(value: Optional[str]) -> str:
    return value if value else UNKNOWN


def points_to_lose(value: Optional[int], exceeded: Optional[bool]) -> str:
    if value is None:
        return UNKNOWN
    if exceeded:
        return "0"
    return str(int(value))
