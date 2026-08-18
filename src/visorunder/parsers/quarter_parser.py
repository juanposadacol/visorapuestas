"""Deteccion del cuarto/periodo (requisito 21).

Acepta las variantes habituales: 1, Q1, 1Q, "1er cuarto", "3.er Cuarto",
"Periodo 2", ademas de descanso y prorroga.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import ParseResult
from .normalize import clean, normalize_label

HALFTIME = "HALFTIME"
GAME_OVER = "GAME_OVER"

_PATTERNS = [
    re.compile(r"\bq\s*([1-4])\b"),
    re.compile(r"\b([1-4])\s*q\b"),
    re.compile(r"\b([1-4])\s*[.ºoª]?\s*(?:er|do|ro|to|a)?\s*(?:cuarto|periodo|parcial|quarter)\b"),
    re.compile(r"\b(?:cuarto|periodo|parcial|quarter)\s*([1-4])\b"),
    re.compile(r"^([1-4])$"),
]

_OT_PATTERNS = [
    re.compile(r"\bot\s*([1-9])?\b"),
    re.compile(r"\b(?:prorroga|overtime|suplementario)\s*([1-9])?\b"),
]

_HALFTIME_WORDS = ("descanso", "medio tiempo", "halftime", "half time", "intermedio", "ht")
_END_WORDS = ("final", "finalizado", "terminado", "full time", "ft")


def parse_period(text: str, *, regulation_quarters: int = 4,
                 confidence: float = 0.0) -> ParseResult:
    """Devuelve el numero de periodo (1..4, 5+ para prorrogas)."""
    raw = clean(text)
    norm = normalize_label(raw)
    if not norm:
        return ParseResult.fail(raw, "sin texto", norm)

    for pattern in _OT_PATTERNS:
        m = pattern.search(norm)
        if m:
            index = int(m.group(1)) if m.group(1) else 1
            return ParseResult(value=regulation_quarters + index, raw=raw,
                               normalized=f"OT{index}", confidence=confidence)

    for pattern in _PATTERNS:
        m = pattern.search(norm)
        if m:
            period = int(m.group(1))
            return ParseResult(value=period, raw=raw, normalized=f"Q{period}", confidence=confidence)

    if any(w in norm for w in _HALFTIME_WORDS):
        return ParseResult(value=None, raw=raw, normalized=HALFTIME, confidence=confidence,
                           reason="descanso")
    if any(w in norm for w in _END_WORDS):
        return ParseResult(value=None, raw=raw, normalized=GAME_OVER, confidence=confidence,
                           reason="partido terminado")

    return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                       reason="cuarto no reconocido")
