"""Parser del mercado: etiqueta + bloque de lineas (requisitos 5 y 6).

Dos responsabilidades:

1) `parse_market_label` traduce el titulo que muestra la casa a un `MarketKey`.
   "3.er Cuarto - Total de puntos" -> QUARTER_TOTAL(period=3)
   Esto es lo que impide usar la linea del Q3 para calcular sobre el Q2.

2) `parse_lines_block` extrae TODAS las lineas visibles con sus dos cuotas.
   Soporta el formato horizontal ("37.5 OVER 1.55 UNDER 2.25") y el vertical
   (linea, cuota, cuota en filas sucesivas), que son los dos que usan las
   casas reales.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace
from typing import List, Optional, Tuple

from ..domain.market import MarketKey, MarketLine, MarketSnapshot, MarketType
from .base import ParseResult
from .normalize import clean, decimal_separator_to_dot, normalize_digits, normalize_label
from .odds_parser import MAX_ODDS, MIN_ODDS

#: Un numero por debajo de esto nunca es una linea de total de baloncesto.
LINE_MIN = 15.0
LINE_MAX = 400.0

OVER_WORDS = ("over", "mas", "mas de", "alta", "arriba", "o")
UNDER_WORDS = ("under", "menos", "menos de", "baja", "abajo", "u")
SUSPENDED_WORDS = ("suspendido", "suspended", "cerrado", "bloqueado", "no disponible")

_TOTAL_WORDS = ("total de puntos", "total puntos", "totales", "total")

_QUARTER_LABEL = [
    re.compile(r"\bq\s*([1-4])\b"),
    re.compile(r"\b([1-4])\s*[.ºoª]*\s*(?:er|do|ro|to)?\s*(?:cuarto|periodo|parcial|quarter)\b"),
    re.compile(r"\b(?:cuarto|periodo|parcial|quarter)\s*([1-4])\b"),
]
_HALF_LABEL = [
    re.compile(r"\b([12])\s*[.ºoª]*\s*(?:a|era|da)?\s*(?:mitad|parte|half)\b"),
    re.compile(r"\b(?:mitad|parte|half)\s*([12])\b"),
]
_GAME_WORDS = ("partido", "encuentro", "match", "juego completo", "tiempo reglamentario")

#: Token numerico conservando su forma original (importa cuantos decimales trae).
_NUMBER_TOKEN = re.compile(r"\d+(?:[.,]\d+)?")


def parse_market_label(text: str, *, confidence: float = 0.0) -> ParseResult:
    """Traduce el titulo del mercado a un MarketKey."""
    raw = clean(text)
    norm = normalize_label(raw)
    if not norm:
        return ParseResult.fail(raw, "sin texto", norm)

    is_total = any(w in norm for w in _TOTAL_WORDS)

    for pattern in _QUARTER_LABEL:
        m = pattern.search(norm)
        if m:
            key = MarketKey.quarter(int(m.group(1)))
            return ParseResult(value=key, raw=raw, normalized=key.label, confidence=confidence,
                               suspicious=not is_total,
                               reason="" if is_total else "no se ve 'total de puntos' en la etiqueta")

    for pattern in _HALF_LABEL:
        m = pattern.search(norm)
        if m:
            key = MarketKey.half_market(int(m.group(1)))
            return ParseResult(value=key, raw=raw, normalized=key.label, confidence=confidence,
                               suspicious=not is_total)

    if is_total and any(w in norm for w in _GAME_WORDS):
        key = MarketKey.game()
        return ParseResult(value=key, raw=raw, normalized=key.label, confidence=confidence)

    if is_total:
        # "Total de puntos" a secas: la casa se refiere al partido completo,
        # pero al no ser explicito se marca como sospechoso.
        key = MarketKey.game()
        return ParseResult(value=key, raw=raw, normalized=key.label, confidence=confidence,
                           suspicious=True, reason="mercado sin cuarto explicito")

    return ParseResult(value=None, raw=raw, normalized=norm, confidence=confidence,
                       reason="mercado no reconocido")


@dataclass
class _Token:
    text: str
    value: float
    decimals: int
    role_hint: str = ""  # "over" | "under" | ""

    @property
    def is_odds_shaped(self) -> bool:
        return self.decimals >= 2 and MIN_ODDS <= self.value <= MAX_ODDS

    @property
    def is_line_shaped(self) -> bool:
        if not (LINE_MIN <= self.value <= LINE_MAX):
            return False
        # 40.5 / 153.5 / 40  -> linea.  1.87 -> no.
        return self.decimals in (0, 1)


def _tokenize(row: str) -> List[_Token]:
    """Extrae numeros de una fila conservando la pista OVER/UNDER previa."""
    tokens: List[_Token] = []
    norm = normalize_label(row)
    cursor = 0
    for m in _NUMBER_TOKEN.finditer(norm):
        prefix = norm[cursor:m.start()]
        cursor = m.end()
        hint = ""
        words = [w for w in re.split(r"[^a-z+\-]+", prefix) if w]
        for word in reversed(words):
            if word in UNDER_WORDS or word == "-":
                hint = "under"
                break
            if word in OVER_WORDS or word == "+":
                hint = "over"
                break
        text = decimal_separator_to_dot(m.group(0))
        decimals = len(text.split(".")[1]) if "." in text else 0
        # Una fila como "Menos de 153.5  1.95" solo lleva la palabra al principio:
        # los numeros posteriores de la misma fila heredan esa pista.
        if not hint and tokens:
            hint = tokens[-1].role_hint
        tokens.append(_Token(text=text, value=float(text), decimals=decimals, role_hint=hint))
    return tokens


@dataclass
class _Group:
    line: Optional[float] = None
    over: Optional[float] = None
    under: Optional[float] = None
    raw: str = ""

    def assign_odds(self, token: _Token) -> None:
        if token.role_hint == "over":
            self.over = token.value
        elif token.role_hint == "under":
            self.under = token.value
        elif self.over is None:
            self.over = token.value  # orden visual habitual: OVER antes que UNDER
        elif self.under is None:
            self.under = token.value

    @property
    def complete_enough(self) -> bool:
        return self.line is not None and (self.over is not None or self.under is not None)


def parse_lines_block(text: str, *, sportsbook: str = "", event: str = "",
                      key: Optional[MarketKey] = None,
                      confidence: float = 0.0) -> MarketSnapshot:
    """Extrae todas las lineas del bloque de mercado.

    Nunca se inventa una cuota: si solo se lee la linea, la cuota queda en None
    y la interfaz mostrara "--".
    """
    raw = clean(text)
    snapshot = MarketSnapshot(key=key, raw_text=raw, timestamp=time.time())
    if not raw:
        return snapshot

    if any(w in normalize_label(raw) for w in SUSPENDED_WORDS):
        snapshot.suspended = True

    groups: List[_Group] = []
    current: Optional[_Group] = None
    for row in str(text).splitlines():
        row_tokens = _tokenize(row)
        for token in row_tokens:
            if token.is_line_shaped and not (token.role_hint and token.is_odds_shaped):
                current = _Group(line=token.value, raw=clean(row))
                groups.append(current)
            elif token.is_odds_shaped:
                if current is None:
                    # Cuotas sin linea previa: no se pueden atribuir, se ignoran.
                    continue
                current.assign_odds(token)

    lines: List[MarketLine] = []
    for group in groups:
        if group.line is None:
            continue
        lines.append(
            MarketLine(
                sportsbook=sportsbook,
                event=event,
                key=key if key is not None else MarketKey.game(),
                line=group.line,
                over_odds=group.over,
                under_odds=group.under,
                raw_text=group.raw,
                confirmed=False,
            )
        )

    # Fusiona las lecturas de una misma linea: algunas casas ponen el OVER y
    # el UNDER en filas separadas ("Mas de 153.5 1.80" / "Menos de 153.5 1.95").
    unique = {}
    for ln in lines:
        prev = unique.get(ln.line)
        if prev is None:
            unique[ln.line] = ln
            continue
        merged_raw = prev.raw_text if prev.raw_text == ln.raw_text else f"{prev.raw_text} | {ln.raw_text}"
        unique[ln.line] = replace(
            prev,
            over_odds=prev.over_odds if prev.over_odds is not None else ln.over_odds,
            under_odds=prev.under_odds if prev.under_odds is not None else ln.under_odds,
            raw_text=merged_raw,
        )

    snapshot.lines = sorted(unique.values(), key=lambda x: x.line)
    return snapshot
