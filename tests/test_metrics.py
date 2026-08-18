"""Casos minimos exigidos por el requisito 30, mas bordes."""

import math

import pytest

from visorunder.calculations import metrics
from visorunder.calculations.metrics import (
    IMPOSSIBLE,
    compute_bet_metrics,
    compute_general_metrics,
    loss_threshold,
    points_per_minute,
    points_to_lose,
    required_pace_to_lose,
    seconds_to_game_end,
    seconds_to_halftime,
    under_exceeded,
)
from visorunder.domain.game_state import GameState, PointsSource
from visorunder.domain.market import MarketKey, Side
from visorunder.domain.rules import FIBA, NBA
from visorunder.domain.time_utils import seconds_to_clock
from visorunder.domain.values import Observed


# --------------------------------------------------------------- requisito 12
def test_under_40_5_con_19_puntos():
    """UNDER 40.5, puntos actuales 19 -> limite 41, faltan 22."""
    assert loss_threshold(40.5) == 41
    assert points_to_lose(40.5, 19) == 22


def test_under_ya_superado():
    assert points_to_lose(40.5, 41) == 0
    assert points_to_lose(40.5, 55) == 0
    assert under_exceeded(40.5, 41) is True
    assert under_exceeded(40.5, 40) is False


def test_linea_entera_pierde_al_superarla():
    # UNDER 40.0: 40 exactos seria empate (push); pierde en 41.
    assert loss_threshold(40.0) == 41


def test_mercado_de_partido_under_153_5():
    """Requisito 30: UNDER 153.5 con 116 puntos -> limite 154, faltan 38."""
    assert loss_threshold(153.5) == 154
    assert points_to_lose(153.5, 116) == 38


def test_puntos_desconocidos_no_se_inventan():
    assert points_to_lose(40.5, None) is None
    assert under_exceeded(40.5, None) is None


# --------------------------------------------------------------- requisito 13
def test_ritmo_necesario_para_perder():
    """22 puntos en 5:28 restantes -> 4.02 pts/min."""
    pace = required_pace_to_lose(22, 328)
    assert pace == pytest.approx(4.02, abs=0.01)


def test_ritmo_cuando_ya_esta_perdido():
    assert required_pace_to_lose(0, 328) == 0.0


def test_ritmo_sin_tiempo_restante_es_imposible():
    assert required_pace_to_lose(22, 0) == IMPOSSIBLE
    assert math.isinf(required_pace_to_lose(5, 0))


def test_ritmo_sin_datos_es_none():
    assert required_pace_to_lose(None, 328) is None
    assert required_pace_to_lose(22, None) is None


# --------------------------------------------------------------- requisito 11
def test_promedio_cuarto_convierte_bien_los_segundos():
    """19 puntos en 4:32 jugados -> 19 / (4 + 32/60)."""
    pace = points_per_minute(19, 272)
    assert pace == pytest.approx(19 / (4 + 32 / 60), abs=1e-9)
    assert pace == pytest.approx(4.191, abs=0.001)
    # Comprobacion explicita del error clasico: NO es 19/4.32
    assert pace != pytest.approx(19 / 4.32, abs=0.01)


def test_promedio_partido_fiba_q2():
    """Q2 con 6 minutos jugados -> 10 (Q1) + 6 = 16 minutos."""
    elapsed = FIBA.seconds_before_period(2) + 360
    assert elapsed == 960
    assert points_per_minute(48, elapsed) == pytest.approx(3.0)


def test_promedio_sin_tiempo_jugado():
    assert points_per_minute(0, 0) is None


# ------------------------------------------------------------ requisitos 15/16
def test_tiempo_jugado_y_para_final_en_q3():
    """Q3, duracion 10:00, reloj 05:28."""
    jugado = metrics.elapsed_period_seconds(600, 328)
    assert seconds_to_clock(jugado) == "04:32"
    assert seconds_to_clock(seconds_to_game_end(FIBA, 3, 328)) == "15:28"
    assert seconds_to_halftime(FIBA, 3, 328) == metrics.HALFTIME_PASSED


def test_tiempo_para_final_ejemplos_requisito_16():
    assert seconds_to_clock(seconds_to_game_end(FIBA, 1, 260)) == "34:20"
    assert seconds_to_clock(seconds_to_game_end(FIBA, 3, 390)) == "16:30"


def test_tiempo_para_descanso():
    # Q1 quedan 4:20 -> 4:20 + 10:00 de Q2
    assert seconds_to_clock(seconds_to_halftime(FIBA, 1, 260)) == "14:20"
    # Q2 quedan 3:00 -> 3:00
    assert seconds_to_halftime(FIBA, 2, 180) == 180
    # Q3/Q4 -> ya paso
    assert seconds_to_halftime(FIBA, 4, 100) == metrics.HALFTIME_PASSED


def test_reglas_nba_12_minutos():
    assert seconds_to_clock(seconds_to_game_end(NBA, 3, 390)) == "18:30"
    assert NBA.regulation_seconds == 48 * 60


def test_prorroga_no_rompe_los_calculos():
    # Q5 = OT1 de 5 minutos: el tiempo para final es solo el restante de la OT.
    assert seconds_to_game_end(FIBA, 5, 120) == 120
    assert FIBA.label(5) == "OT1"
    assert seconds_to_halftime(FIBA, 5, 120) == metrics.HALFTIME_PASSED


# --------------------------------------------------- integracion con el estado
def _state_q3(score_a=43, score_b=31, clock=328, baseline=(24, 22)):
    state = GameState(rules=FIBA)
    state.score_a = Observed.confirmed(score_a)
    state.score_b = Observed.confirmed(score_b)
    state.period = Observed.confirmed(3)
    state.clock_seconds = Observed.confirmed(clock)
    if baseline is not None:
        state.tracker.set_baseline(3, *baseline)
    return state


def test_metricas_generales_ejemplo_del_panel():
    state = _state_q3()
    g = compute_general_metrics(state)
    assert g.total_points == 74
    assert g.period_points == 28  # (43-24) + (31-22)
    assert seconds_to_clock(g.elapsed_period_seconds) == "04:32"
    assert g.game_pace == pytest.approx(74 / ((1200 + 272) / 60), abs=1e-6)


def test_metricas_generales_sin_baseline_no_inventan_puntos_del_cuarto():
    state = _state_q3(baseline=None)
    g = compute_general_metrics(state)
    assert g.period_points is None
    assert g.period_pace is None
    assert g.period_points_source is PointsSource.UNKNOWN
    # el total del partido si se conoce
    assert g.total_points == 74


def test_metricas_de_apuesta_de_cuarto():
    state = _state_q3(score_a=43, score_b=31, clock=328, baseline=(34, 21))
    # puntos del Q3 = (43-34) + (31-21) = 19
    m = compute_bet_metrics(state, MarketKey.quarter(3), 40.5, 1.87, Side.UNDER)
    assert m.scope_points == 19
    assert m.loss_threshold == 41
    assert m.points_to_lose == 22
    assert m.scope_remaining_seconds == 328
    assert m.required_pace == pytest.approx(4.02, abs=0.01)
    assert m.exceeded is False


def test_metricas_de_apuesta_de_partido_usan_total_y_tiempo_total():
    state = GameState(rules=FIBA)
    state.score_a = Observed.confirmed(60)
    state.score_b = Observed.confirmed(56)
    state.period = Observed.confirmed(4)
    state.clock_seconds = Observed.confirmed(510)  # 8:30
    m = compute_bet_metrics(state, MarketKey.game(), 153.5, 1.80, Side.UNDER)
    assert m.scope_points == 116
    assert m.loss_threshold == 154
    assert m.points_to_lose == 38
    assert m.scope_remaining_seconds == 510
    assert m.required_pace == pytest.approx(38 / 8.5, abs=1e-6)


def test_linea_de_cuarto_futuro_no_usa_los_puntos_del_cuarto_actual():
    """Requisito 5: el partido va Q2 00:04 y la casa muestra la linea del Q3."""
    state = GameState(rules=FIBA)
    state.score_a = Observed.confirmed(40)
    state.score_b = Observed.confirmed(38)
    state.period = Observed.confirmed(2)
    state.clock_seconds = Observed.confirmed(4)
    state.tracker.set_baseline(2, 20, 19)
    m = compute_bet_metrics(state, MarketKey.quarter(3), 40.5, 1.87)
    # El Q3 no ha empezado: 0 puntos y el cuarto completo por delante.
    assert m.scope_points == 0
    assert m.points_to_lose == 41
    assert m.scope_remaining_seconds == 600
    assert m.started is False
    # Y NO usa los 39 puntos del Q2 en curso.
    assert m.scope_points != 39
