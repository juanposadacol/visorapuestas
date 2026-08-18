"""Contrato comun de los parsers.

Un parser convierte TEXTO OCR en un valor tipado, y ademas explica lo que ha
hecho. El requisito 22 obliga a poder diagnosticar por que algo se leyo mal,
por eso todo parser devuelve el texto bruto, el normalizado, el valor y el
motivo del rechazo si lo hubo.

Requisito 21: los valores dudosos NO se corrigen en silencio. Se marcan como
`suspicious=True` y el estabilizador se niega a confirmarlos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ParseResult(Generic[T]):
    value: Optional[T] = None
    raw: str = ""
    normalized: str = ""
    confidence: float = 0.0
    suspicious: bool = False
    reason: str = ""
    hint: str = ""

    @property
    def ok(self) -> bool:
        """Lectura utilizable como candidata (todavia no confirmada)."""
        return self.value is not None and not self.suspicious

    @staticmethod
    def fail(raw: str, reason: str, normalized: str = "") -> "ParseResult[Any]":
        return ParseResult(value=None, raw=raw, normalized=normalized, reason=reason)
