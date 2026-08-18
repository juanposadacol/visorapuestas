"""Parser del reloj (requisito 21).

Formato esperado MM:SS con segundos 00-59. En el ultimo minuto se acepta la
notacion con decimas ("28.4"). Si el OCR devuelve algo que no encaja, se
rechaza: preferimos "--" a un reloj inventado.
"""

from __future__ import annotations

import re
from typing import Optional

from ..domain.time_utils import ClockFormatError, clock_to_seconds
from .base import ParseResult
from .normalize import clean, normalize_digits

#: "10 00", "10.00", "1000" son variantes que el OCR produce al perder los ":".
_SPACED = re.compile(r"^(\d{1,2})[ .](\d{2})$")
_GLUED = re.compile(r"^(\d{3,4})$")


def parse_clock(text: str, *, max_period_seconds: int = 12 * 60,
                confidence: float = 0.0) -> ParseResult:
    """Convierte texto OCR en segundos restantes del periodo."""
    raw = clean(text)
    norm = normalize_digits(raw)
    if not norm:
        return ParseResult.fail(raw, "sin texto", norm)

    # Caso normal MM:SS
    try:
        seconds = clock_to_seconds(norm)
        if seconds > max_period_seconds:
            return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                               reason=f"reloj {norm} supera la duracion del periodo")
        return ParseResult(value=seconds, raw=raw, normalized=norm, confidence=confidence)
    except ClockFormatError:
        pass

    # El OCR perdio el separador: "10 00" / "10.00"
    m = _SPACED.match(norm)
    if m:
        minutes, secs = int(m.group(1)), int(m.group(2))
        if secs <= 59:
            value = minutes * 60 + secs
            if value <= max_period_seconds:
                return ParseResult(value=value, raw=raw, normalized=f"{minutes:02d}:{secs:02d}",
                                   confidence=confidence)

    # "0528" -> 05:28, pero es una lectura degradada: sospechosa.
    m = _GLUED.match(norm)
    if m:
        digits = m.group(1).zfill(4)
        minutes, secs = int(digits[:2]), int(digits[2:])
        if secs <= 59:
            value = minutes * 60 + secs
            if value <= max_period_seconds:
                return ParseResult(value=value, raw=raw, normalized=f"{minutes:02d}:{secs:02d}",
                                   confidence=confidence, suspicious=True,
                                   reason="separador ausente",
                                   hint=f"{minutes:02d}:{secs:02d}")

    return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                       reason="formato de reloj no reconocido")


def looks_like_period_change(previous: Optional[int], current: int, period_seconds: int) -> bool:
    """Detecta el patron 00:02 -> 00:01 -> 00:00 -> 10:00 (requisito 21).

    Un salto hacia arriba desde un valor muy bajo hasta (casi) la duracion
    completa del periodo indica que ha empezado un cuarto nuevo.
    """
    if previous is None:
        return False
    if current <= previous:
        return False
    return previous <= 5 and current >= period_seconds - 5
