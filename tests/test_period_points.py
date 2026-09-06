"""Requisito 9: nunca inventar los puntos del cuarto."""

import pytest

from visorunder.domain.game_state import GameState, PeriodPointsTracker, PointsSource
from visorunder.domain.rules import FIBA
from visorunder.domain.values import Observed


def _state(score_a, score_b, period, clock=300):
    s = GameState(rules=FIBA)
    s.score_a = Observed.confirmed(score_a)
    s.score_b = Observed.confirmed(score_b)
    s.period = Observed.confirmed(period)
    s.clock_seconds = Observed.confirmed(clock)
    return s


def test_arrancar_a_mitad_del_cuarto_no_asume_puntos():
    """Los 43-31 observados al abrir la app NO son los puntos del Q3."""
    s = _state(43, 31, 3)
    ps = s.current_period_score()
    assert ps.total is None
    assert ps.source is PointsSource.UNKNOWN


def test_desglose_de_la_casa_tiene_prioridad():
    s = _state(43, 31, 3)
    s.tracker.set_breakdown(3, 10, 9)
    ps = s.current_period_score()
    assert ps.total == 19
    assert ps.source is PointsSource.BREAKDOWN


def test_entrada_manual_del_marcador_al_empezar_el_cuarto():
    s = _state(43, 31, 3)
    s.tracker.set_manual_baseline(3, 33, 22)
    ps = s.current_period_score()
    assert (ps.points_a, ps.points_b, ps.total) == (10, 9, 19)
    assert ps.source is PointsSource.MANUAL


def test_historial_al_cambiar_de_cuarto():
    tracker = PeriodPointsTracker(FIBA)
    tracker.set_baseline(2, 20, 18)
    # El Q2 termina 45-40 y empieza el Q3
    tracker.on_period_change(2, 3, 45, 40)
    q2 = tracker.period_score(2, 3, 45, 40)
    assert q2.total == (45 - 20) + (40 - 18)
    assert q2.closed is True
    # El Q3 arranca con baseline 45-40; tras anotar 10-9:
    q3 = tracker.period_score(3, 3, 55, 49)
    assert q3.total == 19
    assert q3.source is PointsSource.HISTORY


def test_baseline_manual_no_se_pisa_por_uno_automatico():
    tracker = PeriodPointsTracker(FIBA)
    tracker.set_manual_baseline(3, 33, 22)
    tracker.set_baseline(3, 40, 30, PointsSource.HISTORY)
    assert tracker.baselines[3] == (33, 22, PointsSource.MANUAL)


def test_cuarto_futuro_tiene_cero_puntos_de_hecho():
    s = _state(40, 38, 2)
    ps = s.period_score(3)
    assert ps.total == 0


def test_mitad_desconocida_si_falta_un_cuarto():
    s = _state(40, 38, 2)
    s.tracker.set_breakdown(1, 20, 19)
    # Sin datos del Q2 en curso la primera mitad es desconocida
    assert s.half_score(1).total is None
    s.tracker.set_baseline(2, 20, 19)
    assert s.half_score(1).total == (20 + 19) + (20 + 19)


def test_tiempos_del_estado():
    s = _state(43, 31, 3, clock=328)
    assert s.elapsed_period_seconds == 272
    assert s.elapsed_game_seconds == 1200 + 272
    assert s.remaining_game_seconds == 328 + 600
    assert s.remaining_to_halftime_seconds == -1
    assert s.label() == "Q3"


def test_estado_sin_datos_devuelve_none_en_todo():
    s = GameState(rules=FIBA)
    assert s.total_points is None
    assert s.elapsed_period_seconds is None
    assert s.remaining_game_seconds is None
    assert s.label() == "--"


def test_puntos_de_un_cuarto_pasado_a_partir_de_dos_marcadores_base():
    """Conocer el marcador al empezar Q3 y Q4 determina los puntos del Q3.

    Es un hecho, no una suposicion, y es lo que permite evaluar el mercado de
    la segunda mitad cuando ya se juega el Q4 habiendo entrado a mitad del Q3.
    """
    tracker = PeriodPointsTracker(FIBA)
    tracker.set_manual_baseline(3, 50, 44)
    tracker.set_manual_baseline(4, 62, 55)
    q3 = tracker.period_score(3, current_period=4, score_a=70, score_b=62)
    assert (q3.points_a, q3.points_b, q3.total) == (12, 11, 23)
    assert q3.closed is True


def test_sin_la_base_del_cuarto_siguiente_no_se_deduce_nada():
    tracker = PeriodPointsTracker(FIBA)
    tracker.set_manual_baseline(3, 50, 44)
    assert tracker.period_score(3, current_period=4, score_a=70, score_b=62).total is None


def test_la_mitad_se_completa_con_cuartos_pasados_deducidos():
    s = _state(70, 62, 4, clock=300)
    s.tracker.set_manual_baseline(3, 50, 44)
    s.tracker.set_manual_baseline(4, 62, 55)
    assert s.half_score(2).total == (70 - 50) + (62 - 44)
