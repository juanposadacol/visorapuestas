"""Resolucion generica de mercado -> (acumulador de puntos, tiempo restante).

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
    remaining_seconds: segundos de juego que todavia pueden sumar puntos
                       a ese mercado.
    Ambos pueden ser None: significa NO DISPONIBLE, nunca cero por defecto.
    """

    key: MarketKey
    points: Optional[int]
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

    remaining: Optional[int]
    settled = False
    started = True
    if current is None:
        remaining = None
    elif period == current:
        remaining = state.remaining_period_seconds
    elif period < current:
        # El cuarto ya termino: no pueden entrar mas puntos.
        remaining = 0
        settled = True
    else:
        # El cuarto todavia no ha empezado. La casa ya ofrece la linea pero el
        # tiempo disponible es el cuarto completo y los puntos son 0 de hecho.
        remaining = state.rules.period_seconds(period)
        started = False

    return ScopeResolution(
        key=key,
        points=points,
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

    remaining: Optional[int]
    settled = False
    started = True
    if current is None or clock is None:
        remaining = None
    elif current > last:
        remaining = 0
        settled = True
    elif current < first:
        remaining = sum(rules.period_seconds(p) for p in range(first, last + 1))
        started = False
    else:
        remaining = clock + sum(rules.period_seconds(p) for p in range(current + 1, last + 1))

    return ScopeResolution(
        key=key,
        points=points,
        remaining_seconds=remaining,
        points_source=hs.source,
        settled=settled,
        started=started,
        label=key.label,
    )
