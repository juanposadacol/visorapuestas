"""Resolucion generica de mercado -> puntos, tiempo jugado y restante.

Requisito 14: "Crea una arquitectura generica donde el mercado determine el
acumulador de puntos utilizado y el tiempo restante utilizado."

Anadir un mercado nuevo consiste en anadir un caso en `resolve`, sin tocar
las metricas ni la interfaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..domain.game_state import GameState, PointsSource
from ..domain.market import MarketKey, MarketType


@dataclass(frozen=True)
class ScopeResolution:
    """Datos que el mercado aporta a las metricas.

    points:            puntos ya anotados dentro del ambito del mercado.
    elapsed_seconds:   segundos realmente jugados dentro del ambito.
    remaining_seconds: segundos de juego que todavia pueden sumar puntos
                       a ese mercado.
    Los tres pueden ser None: significa NO DISPONIBLE, nunca cero por defecto.
    """

    key: MarketKey
    points: Optional[int]
    elapsed_seconds: Optional[int]
    remaining_seconds: Optional[int]
    points_source: PointsSource = PointsSource.UNKNOWN
    settled: bool = False   # el ambito ya termino: no pueden entrar mas puntos
    started: bool = True    # el ambito ya comenzo
    label: str = ""


def resolve(state: GameState, key: MarketKey) -> ScopeResolution:
    """Devuelve puntos y tiempo restante aplicables al mercado `key`."""
    if key.market_type is MarketType.GAME_TOTAL:
        return _resolve_game(state, key)
    if key.market_type is MarketType.QUARTER_TOTAL:
        return _resolve_quarter(state, key)
    if key.market_type is MarketType.HALF_TOTAL:
        return _resolve_half(state, key)
    raise ValueError(f"mercado no soportado: {key.market_type}")


def _resolve_game(state: GameState, key: MarketKey) -> ScopeResolution:
    points = state.total_points
    remaining = state.remaining_game_seconds
    period = state.period_value
    settled = remaining == 0 and period is not None
    return ScopeResolution(
        key=key,
        points=points,
        elapsed_seconds=state.elapsed_game_seconds,
        remaining_seconds=remaining,
        points_source=PointsSource.HISTORY if points is not None else PointsSource.UNKNOWN,
        settled=bool(settled),
        label=key.label,
    )


def _resolve_quarter(state: GameState, key: MarketKey) -> ScopeResolution:
    period = key.period
    current = state.period_value
    ps = state.period_score(period)
    points = ps.total

    elapsed: Optional[int]
    remaining: Optional[int]
    settled = False
    started = True
    if current is None:
        elapsed = None
        remaining = None
    elif period == current:
        elapsed = state.elapsed_period_seconds
        remaining = state.remaining_period_seconds
    elif period < current:
        # El cuarto ya termino: no pueden entrar mas puntos.
        elapsed = state.rules.period_seconds(period)
        remaining = 0
        settled = True
    else:
        # El cuarto todavia no ha empezado. La casa ya ofrece la linea pero el
        # tiempo disponible es el cuarto completo y los puntos son 0 de hecho.
        elapsed = 0
        remaining = state.rules.period_seconds(period)
        started = False

    return ScopeResolution(
        key=key,
        points=points,
        elapsed_seconds=elapsed,
        remaining_seconds=remaining,
        points_source=ps.source,
        settled=settled,
        started=started,
        label=key.label,
    )


def _resolve_half(state: GameState, key: MarketKey) -> ScopeResolution:
    rules = state.rules
    per_half = rules.regulation_quarters // 2
    first = 1 + (key.half - 1) * per_half
    last = first + per_half - 1

    hs = state.half_score(key.half)
    points = hs.total
    current = state.period_value
    clock = state.clock_value

    scope_seconds = sum(rules.period_seconds(p) for p in range(first, last + 1))
    elapsed: Optional[int]
    remaining: Optional[int]
    settled = False
    started = True
    if current is None:
        elapsed = None
        remaining = None
    elif current > last:
        elapsed = scope_seconds
        remaining = 0
        settled = True
    elif current < first:
        elapsed = 0
        remaining = scope_seconds
        started = False
    elif clock is None:
        elapsed = None
        remaining = None
    else:
        remaining = clock + sum(rules.period_seconds(p) for p in range(current + 1, last + 1))
        elapsed = scope_seconds - remaining

    return ScopeResolution(
        key=key,
        points=points,
        elapsed_seconds=elapsed,
        remaining_seconds=remaining,
        points_source=hs.source,
        settled=settled,
        started=started,
        label=key.label,
    )
