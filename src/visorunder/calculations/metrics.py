"""Motor matematico. Funciones puras, independientes y testeables (requisito 11).

Ninguna funcion de este modulo predice nada. Todas describen el ESTADO
MATEMATICO REAL a partir de datos observados. Si un dato de entrada es
desconocido, la salida es None (nunca un valor inventado).

Todo el tiempo entra en SEGUNDOS. Solo se convierte a minutos decimales
dentro de los ratios.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ..domain.bet import LockedBet
from ..domain.game_state import GameState, PointsSource
from ..domain.market import MarketKey, Side
from ..domain.time_utils import seconds_to_clock, seconds_to_decimal_minutes
from . import market_scope

#: Valor devuelto cuando queda tiempo cero pero aun faltan puntos: perder es
#: matematicamente imposible dentro del ambito del mercado.
IMPOSSIBLE = math.inf


# --------------------------------------------------------------------------
# Bloque A: tiempo
# --------------------------------------------------------------------------
def elapsed_period_seconds(period_duration_seconds: int, remaining_seconds: int) -> int:
    """Requisito 11.A -- tiempo jugado del cuarto.

    tiempo_jugado = duracion_cuarto - tiempo_restante

    >>> elapsed_period_seconds(600, 328)   # 10:00 - 05:28
    272
    >>> seconds_to_clock(elapsed_period_seconds(600, 328))
    '04:32'
    """
    return max(0, int(period_duration_seconds) - int(remaining_seconds))


# --------------------------------------------------------------------------
# Bloque B/C: puntos
# --------------------------------------------------------------------------
def total_points(points_a: int, points_b: int) -> int:
    """Requisito 11.B -- puntos del partido = A + B."""
    return int(points_a) + int(points_b)


def period_points(points_a_in_period: int, points_b_in_period: int) -> int:
    """Requisito 11.C -- puntos del cuarto."""
    return int(points_a_in_period) + int(points_b_in_period)


# --------------------------------------------------------------------------
# Bloque D/E: promedios
# --------------------------------------------------------------------------
def points_per_minute(points: Optional[int], seconds_played: Optional[int]) -> Optional[float]:
    """Puntos por minuto. Devuelve None si no se puede calcular.

    Convierte los segundos a minutos DECIMALES correctamente:
    4:32 -> 4 + 32/60 = 4.5333 minutos (nunca 4.32).

    >>> round(points_per_minute(19, 272), 4)   # 19 pts en 04:32
    4.1912
    >>> points_per_minute(19, 0) is None
    True
    """
    if points is None or seconds_played is None:
        return None
    minutes = seconds_to_decimal_minutes(seconds_played)
    if minutes <= 0:
        return None
    return points / minutes


# --------------------------------------------------------------------------
# Bloque 12: cuanto falta para SUPERAR la linea
# --------------------------------------------------------------------------
# VOCABULARIO: el dominio habla de "superar la linea", nunca de "perder".
# Superar la linea es un hecho del partido, independiente del lado apostado:
# para un UNDER superarla significa perder y para un OVER significa ganar.
# La traduccion a "faltan para perder" ocurre solo en la interfaz y solo
# cuando existe una apuesta UNDER fijada. Asi el motor sirve igual para OVER
# el dia que haga falta, sin reescribir nada.
# --------------------------------------------------------------------------
def exceed_threshold(line: float, side: Side = Side.UNDER) -> int:
    """Total de puntos con el que la linea queda SUPERADA.

        limite = floor(linea) + 1

    >>> exceed_threshold(40.5)
    41
    >>> exceed_threshold(153.5)
    154
    >>> exceed_threshold(40.0)     # linea entera: 40 es empate, 41 la supera
    41

    El umbral no depende del lado: es el mismo numero para UNDER y para OVER.
    `side` se acepta para que la firma sea estable si en el futuro algun
    mercado necesita resolverse de otra forma.
    """
    return math.floor(float(line)) + 1


def points_to_exceed(line: float, current_points: Optional[int], side: Side = Side.UNDER) -> Optional[int]:
    """Puntos que faltan, DESDE AHORA, para que la linea quede superada.

    >>> points_to_exceed(40.5, 19)
    22
    >>> points_to_exceed(153.5, 116)
    38
    >>> points_to_exceed(40.5, 41)    # ya superada
    0
    >>> points_to_exceed(40.5, None) is None
    True
    """
    if current_points is None:
        return None
    threshold = exceed_threshold(line, side)
    return max(0, threshold - int(current_points))


def line_exceeded(line: float, current_points: Optional[int]) -> Optional[bool]:
    """True si el total del ambito ya alcanzo o supero el limite."""
    if current_points is None:
        return None
    return int(current_points) >= exceed_threshold(line)


# --------------------------------------------------------------------------
# Bloque 13: ritmo necesario para superar la linea
# --------------------------------------------------------------------------
def required_pace_to_exceed(points_needed: Optional[int],
                            remaining_seconds: Optional[int]) -> Optional[float]:
    """Puntos por minuto que harian falta durante TODO el tiempo restante
    para que la linea quede superada.

    Es el nucleo de la deteccion de entrada: responde a "que ritmo tendrian
    que mantener desde este instante para superar esta linea".

        ritmo = puntos_que_faltan / minutos_restantes

    >>> round(required_pace_to_exceed(22, 328), 2)   # 22 pts en 5:28
    4.02
    >>> required_pace_to_exceed(0, 328)              # ya superada
    0.0
    >>> required_pace_to_exceed(22, 0) == IMPOSSIBLE  # no queda tiempo
    True
    >>> required_pace_to_exceed(22, None) is None
    True
    """
    if points_needed is None:
        return None
    if points_needed <= 0:
        return 0.0
    if remaining_seconds is None:
        return None
    if remaining_seconds <= 0:
        return IMPOSSIBLE
    return points_needed / seconds_to_decimal_minutes(remaining_seconds)


# --------------------------------------------------------------------------
# Bloques 15/16: tiempos de referencia
# --------------------------------------------------------------------------
HALFTIME_PASSED = -1


def seconds_to_halftime(rules, period: Optional[int], remaining_seconds: Optional[int]) -> Optional[int]:
    """Requisito 15. Devuelve HALFTIME_PASSED (-1) si el descanso ya paso."""
    if period is None or remaining_seconds is None:
        return None
    last_first_half = rules.halftime_after_period
    if period > last_first_half:
        return HALFTIME_PASSED
    pending = sum(rules.period_seconds(p) for p in range(period + 1, last_first_half + 1))
    return remaining_seconds + pending


def seconds_to_game_end(rules, period: Optional[int], remaining_seconds: Optional[int]) -> Optional[int]:
    """Requisito 16 -- restante del cuarto actual + cuartos no jugados.

    >>> from ..domain.rules import FIBA
    >>> seconds_to_clock(seconds_to_game_end(FIBA, 3, 390))   # Q3, quedan 6:30
    '16:30'
    >>> seconds_to_clock(seconds_to_game_end(FIBA, 1, 260))   # Q1, quedan 4:20
    '34:20'
    """
    if period is None or remaining_seconds is None:
        return None
    if rules.is_overtime(period):
        return remaining_seconds
    pending = sum(rules.period_seconds(p) for p in range(period + 1, rules.regulation_quarters + 1))
    return remaining_seconds + pending


# --------------------------------------------------------------------------
# Agregados que consume la interfaz
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class GeneralMetrics:
    """Metricas del panel principal que no dependen de la apuesta fijada."""

    total_points: Optional[int] = None
    period_points: Optional[int] = None
    period_points_a: Optional[int] = None
    period_points_b: Optional[int] = None
    period_points_source: PointsSource = PointsSource.UNKNOWN
    elapsed_period_seconds: Optional[int] = None
    remaining_period_seconds: Optional[int] = None
    elapsed_game_seconds: Optional[int] = None
    remaining_game_seconds: Optional[int] = None
    seconds_to_halftime: Optional[int] = None
    period_pace: Optional[float] = None
    game_pace: Optional[float] = None


@dataclass(frozen=True)
class BetMetrics:
    """Metricas relativas a la linea seleccionada o fijada."""

    key: Optional[MarketKey] = None
    line: Optional[float] = None
    odds: Optional[float] = None
    side: Side = Side.UNDER
    scope_points: Optional[int] = None
    scope_remaining_seconds: Optional[int] = None
    scope_points_source: PointsSource = PointsSource.UNKNOWN
    exceed_threshold: Optional[int] = None
    points_to_exceed: Optional[int] = None
    required_pace: Optional[float] = None
    exceeded: Optional[bool] = None
    settled: bool = False
    started: bool = True


def compute_general_metrics(state: GameState) -> GeneralMetrics:
    """Calcula el bloque de metricas generales a partir del estado observado."""
    ps = state.current_period_score()
    elapsed_q = state.elapsed_period_seconds
    elapsed_game = state.elapsed_game_seconds
    return GeneralMetrics(
        total_points=state.total_points,
        period_points=ps.total,
        period_points_a=ps.points_a,
        period_points_b=ps.points_b,
        period_points_source=ps.source,
        elapsed_period_seconds=elapsed_q,
        remaining_period_seconds=state.remaining_period_seconds,
        elapsed_game_seconds=elapsed_game,
        remaining_game_seconds=state.remaining_game_seconds,
        seconds_to_halftime=seconds_to_halftime(state.rules, state.period_value, state.clock_value),
        period_pace=points_per_minute(ps.total, elapsed_q),
        game_pace=points_per_minute(state.total_points, elapsed_game),
    )


def compute_bet_metrics(state: GameState, key: MarketKey, line: float,
                        odds: Optional[float] = None, side: Side = Side.UNDER) -> BetMetrics:
    """Calcula las metricas de una linea contra el estado actual del partido.

    El mercado (`key`) decide que puntos y que tiempo restante se usan; esta
    funcion no sabe si es un cuarto, una mitad o el partido entero.
    """
    resolution = market_scope.resolve(state, key)
    threshold = exceed_threshold(line, side)
    needed = points_to_exceed(line, resolution.points, side)
    return BetMetrics(
        key=key,
        line=line,
        odds=odds,
        side=side,
        scope_points=resolution.points,
        scope_remaining_seconds=resolution.remaining_seconds,
        scope_points_source=resolution.points_source,
        exceed_threshold=threshold,
        points_to_exceed=needed,
        required_pace=required_pace_to_exceed(needed, resolution.remaining_seconds),
        exceeded=line_exceeded(line, resolution.points),
        settled=resolution.settled,
        started=resolution.started,
    )


def compute_metrics_for_bet(state: GameState, bet: LockedBet) -> BetMetrics:
    """Metricas de la apuesta FIJADA. Usa siempre la linea congelada."""
    return compute_bet_metrics(state, bet.key, bet.line, bet.odds, bet.side)
