"""Valores observados: distincion RAW vs CONFIRMED (requisitos 20, 33, 37).

La aplicacion NUNCA calcula sobre una lectura dudosa. Cada dato que viene del
OCR viaja envuelto en un `Observed`, que distingue:

    RAW        lectura recien parseada, todavia no confiable
    CONFIRMED  valor que ha superado el estabilizador y las validaciones
    UNKNOWN    no hay valor fiable -> la UI muestra "--"

Preferimos mostrar "--" durante medio segundo antes que un numero incorrecto.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")

UNKNOWN_TEXT = "--"


class ValueStatus(str, Enum):
    UNKNOWN = "UNKNOWN"      # sin dato fiable
    RAW = "RAW"              # leido pero no confirmado
    CONFIRMED = "CONFIRMED"  # estable y validado
    MANUAL = "MANUAL"        # introducido por el usuario: se considera fiable


@dataclass(frozen=True)
class Observed(Generic[T]):
    """Un valor observado con su procedencia y frescura."""

    value: Optional[T] = None
    status: ValueStatus = ValueStatus.UNKNOWN
    confidence: float = 0.0
    raw_text: str = ""
    updated_at: float = field(default_factory=time.time)
    source: str = ""

    @property
    def is_usable(self) -> bool:
        """Solo los valores CONFIRMED o MANUAL alimentan los calculos."""
        return self.value is not None and self.status in (ValueStatus.CONFIRMED, ValueStatus.MANUAL)

    def age(self, now: Optional[float] = None) -> float:
        return (now if now is not None else time.time()) - self.updated_at

    def is_stale(self, ttl_seconds: float, now: Optional[float] = None) -> bool:
        """Un dato confirmado caduca: si el OCR se pierde, deja de ser fiable."""
        return self.age(now) > ttl_seconds

    def usable_value(self) -> Optional[T]:
        return self.value if self.is_usable else None

    @staticmethod
    def unknown() -> "Observed[Any]":
        return Observed(value=None, status=ValueStatus.UNKNOWN)

    @staticmethod
    def manual(value: T, source: str = "usuario") -> "Observed[T]":
        return Observed(value=value, status=ValueStatus.MANUAL, confidence=1.0, source=source)

    @staticmethod
    def confirmed(value: T, confidence: float = 1.0, raw_text: str = "", source: str = "") -> "Observed[T]":
        return Observed(
            value=value,
            status=ValueStatus.CONFIRMED,
            confidence=confidence,
            raw_text=raw_text,
            source=source,
        )

    @staticmethod
    def raw(value: T, confidence: float = 0.0, raw_text: str = "", source: str = "") -> "Observed[T]":
        return Observed(
            value=value,
            status=ValueStatus.RAW,
            confidence=confidence,
            raw_text=raw_text,
            source=source,
        )


def display(observed: Optional[Observed[Any]], formatter=None, placeholder: str = UNKNOWN_TEXT) -> str:
    """Formatea para la UI: si el dato no es utilizable, devuelve '--'."""
    if observed is None or not observed.is_usable:
        return placeholder
    if formatter is None:
        return str(observed.value)
    return formatter(observed.value)
