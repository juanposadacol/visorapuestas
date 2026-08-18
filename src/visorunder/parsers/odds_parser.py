"""Parser de cuotas y lineas (requisito 21).

Cuotas: decimales razonables, tipicamente 1.01 - 20.00.
Un "187" probablemente sea "1.87", pero NO se corrige en silencio: se devuelve
marcado como sospechoso, con la correccion propuesta en `hint`, y el
estabilizador no lo confirmara.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import ParseResult
from .normalize import clean, decimal_separator_to_dot, normalize_digits

MIN_ODDS = 1.01
MAX_ODDS = 20.00

#: Cota inferior para considerar que un numero es una LINEA de total y no una
#: cuota. Un total de baloncesto (cuarto entero incluido) nunca baja de aqui.
MIN_LINE = 8.0
MAX_LINE = 400.0

_ODDS_RE = re.compile(r"^(\d{1,2})[.](\d{1,3})$")
_GLUED_ODDS_RE = re.compile(r"^(\d{3,4})$")


def parse_odds(text: str, *, confidence: float = 0.0) -> ParseResult:
    """Convierte texto OCR en una cuota decimal."""
    raw = clean(text)
    norm = decimal_separator_to_dot(normalize_digits(raw, keep=".,"))
    if not norm:
        return ParseResult.fail(raw, "sin texto", norm)

    m = _ODDS_RE.match(norm)
    if m:
        value = float(norm)
        if MIN_ODDS <= value <= MAX_ODDS:
            return ParseResult(value=round(value, 3), raw=raw, normalized=norm, confidence=confidence)
        return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                           reason=f"cuota fuera de rango [{MIN_ODDS}, {MAX_ODDS}]: {value}")

    m = _GLUED_ODDS_RE.match(norm)
    if m:
        digits = m.group(1)
        candidate = float(f"{digits[0]}.{digits[1:]}")
        if MIN_ODDS <= candidate <= MAX_ODDS:
            # Lectura dudosa: se propone, no se impone.
            return ParseResult(value=candidate, raw=raw, normalized=norm, confidence=confidence,
                               suspicious=True, reason="falta el separador decimal",
                               hint=f"{candidate:.2f}")

    return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                       reason="cuota no reconocida")


def parse_line(text: str, *, confidence: float = 0.0) -> ParseResult:
    """Convierte texto OCR en una linea de total (37.5, 153.5, ...)."""
    raw = clean(text)
    norm = decimal_separator_to_dot(normalize_digits(raw, keep=".,"))
    norm = re.sub(r"^[+-]", "", norm)
    if not norm:
        return ParseResult.fail(raw, "sin texto", norm)
    try:
        value = float(norm)
    except ValueError:
        return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                           reason="linea no numerica")
    if not (MIN_LINE <= value <= MAX_LINE):
        return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                           reason=f"linea fuera de rango [{MIN_LINE}, {MAX_LINE}]: {value}")
    # Las lineas de total son casi siempre X.5 o enteras; otro decimal es raro.
    fraction = round(value - int(value), 2)
    suspicious = fraction not in (0.0, 0.5)
    return ParseResult(value=round(value, 2), raw=raw, normalized=norm, confidence=confidence,
                       suspicious=suspicious,
                       reason="decimal atipico en una linea" if suspicious else "")


def looks_like_odds(value: float) -> bool:
    return MIN_ODDS <= value <= MAX_ODDS


def looks_like_line(value: float) -> bool:
    return MIN_LINE <= value <= MAX_LINE
