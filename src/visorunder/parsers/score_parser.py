"""Parser del marcador (requisito 21).

El marcador normalmente no baja y sube de a pocos puntos. Aqui solo se
convierte texto a numero; la coherencia temporal (no decrecer, rechazar 86
entre lecturas de 36) la impone el estabilizador.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from .base import ParseResult
from .normalize import clean, dropped_characters, extract_integers, normalize_digits

MAX_REASONABLE_SCORE = 250

#: "43 - 31", "43-31", "43 31": marcador de los dos equipos en un solo ROI.
_PAIR = re.compile(r"^(\d{1,3})\s*[-:vsVS ]{0,3}\s*(\d{1,3})$")


def parse_score(text: str, *, confidence: float = 0.0) -> ParseResult:
    """Parsea el marcador de UN equipo."""
    raw = clean(text)
    norm = normalize_digits(raw, keep="")
    digits = re.sub(r"\D", "", norm)
    if not digits:
        return ParseResult.fail(raw, "sin digitos", norm)
    if len(digits) > 3:
        return ParseResult(value=None, raw=raw, normalized=norm,
                           confidence=confidence, reason="demasiados digitos")
    value = int(digits)
    if value > MAX_REASONABLE_SCORE:
        return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                           reason=f"marcador inverosimil: {value}")
    basura = dropped_characters(raw, keep="")
    if basura:
        # El OCR vio simbolos que no son digitos: es probable que ademas haya
        # perdido alguna cifra. No se confirma (requisitos 21 y 37).
        return ParseResult(value=value, raw=raw, normalized=digits, confidence=confidence,
                           suspicious=True,
                           reason=f"caracteres no numericos en el recorte: {basura!r}")
    return ParseResult(value=value, raw=raw, normalized=digits, confidence=confidence)


def parse_score_pair(text: str, *, confidence: float = 0.0) -> ParseResult:
    """Parsea un ROI que contiene los dos marcadores: devuelve (a, b)."""
    raw = clean(text)
    norm = normalize_digits(raw, keep="-: ")
    basura = dropped_characters(raw, keep="-: ")
    suspicious = bool(basura)
    reason = f"caracteres no numericos en el recorte: {basura!r}" if basura else ""

    m = _PAIR.match(norm.replace(":", "-"))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= MAX_REASONABLE_SCORE and b <= MAX_REASONABLE_SCORE:
            return ParseResult(value=(a, b), raw=raw, normalized=f"{a}-{b}",
                               confidence=confidence, suspicious=suspicious, reason=reason)
    numbers = extract_integers(norm)
    if len(numbers) == 2 and all(n <= MAX_REASONABLE_SCORE for n in numbers):
        return ParseResult(value=(numbers[0], numbers[1]), raw=raw,
                           normalized=f"{numbers[0]}-{numbers[1]}", confidence=confidence,
                           suspicious=suspicious, reason=reason)
    return ParseResult.fail(raw, "no se reconocen dos marcadores", norm)


def parse_breakdown(text: str, *, expected_periods: int = 4,
                    confidence: float = 0.0) -> ParseResult:
    """Parsea una fila de desglose por cuartos: "24 18 19 22" -> [24,18,19,22]."""
    raw = clean(text)
    norm = normalize_digits(raw, keep=" ")
    numbers = extract_integers(norm)
    if not numbers:
        return ParseResult.fail(raw, "sin numeros", norm)
    if len(numbers) > expected_periods:
        # Algunas casas anaden el total al final de la fila.
        if len(numbers) == expected_periods + 1 and numbers[-1] == sum(numbers[:-1]):
            numbers = numbers[:-1]
        else:
            return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                               reason="numero de cuartos inesperado")
    if any(n > 99 for n in numbers):
        return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                           reason="puntos por cuarto inverosimiles")
    return ParseResult(value=list(numbers), raw=raw, normalized=" ".join(str(n) for n in numbers),
                       confidence=confidence)
