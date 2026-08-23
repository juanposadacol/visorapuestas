"""Parciales estructurales del DOM, mitades y cuadro compacto."""

from __future__ import annotations

import os

import pytest

from visorunder.calculations.metrics import compute_general_metrics
from visorunder.domain.game_state import GameState, PointsSource
from visorunder.domain.rules import FIBA, NBA
from visorunder.domain.values import Observed


def _state(rules, period, remaining, score_a, score_b, periods_a, periods_b):
    state = GameState(rules=rules)
    state.score_a = Observed.confirmed(score_a)
    state.score_b = Observed.confirmed(score_b)
    state.period = Observed.confirmed(period)
    state.clock_seconds = Observed.confirmed(remaining)
    state.tracker.replace_dom_breakdown(periods_a, periods_b)
    return state


def test_regresion_real_betplay_q3_24_42():
    state = _state(
        FIBA, 3, 5 * 60 + 18, 65, 47,
        {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0},
        {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 0},
    )
    general = compute_general_metrics(state)

    assert [score.total for score in state.period_grid_scores()] == [47, 43, 22, 0]
    assert state.half_score(1).points_a == 46
    assert state.half_score(1).points_b == 44
    assert state.half_score(1).total == 90
    assert state.half_score(2).points_a == 19
    assert state.half_score(2).points_b == 3
    assert general.period_points == 22
    assert general.period_pace == pytest.approx(22 / (282 / 60), abs=1e-12)
    assert general.half_pace == pytest.approx(22 / (282 / 60), abs=1e-12)
    assert general.first_half_pace == pytest.approx(90 / 20, abs=1e-12)
    assert general.game_pace == pytest.approx(112 / (1482 / 60), abs=1e-12)


@pytest.mark.parametrize("rules,period,played,periods_a,periods_b,expected_points", [
    (FIBA, 1, 240, {"Q1": 10}, {"Q1": 8}, 18),
    (FIBA, 2, 300, {"Q1": 20, "Q2": 8}, {"Q1": 18, "Q2": 7}, 53),
    (FIBA, 3, 282, {"Q1": 21, "Q2": 25, "Q3": 19},
     {"Q1": 26, "Q2": 18, "Q3": 3}, 22),
    (FIBA, 4, 180, {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 5},
     {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 4}, 31),
    (NBA, 2, 360, {"Q1": 28, "Q2": 12}, {"Q1": 24, "Q2": 10}, 74),
])
def test_ritmo_de_mitad_dinamico_q1_a_q4_y_reglas(
        rules, period, played, periods_a, periods_b, expected_points):
    score_a = sum(value for value in periods_a.values() if value is not None)
    score_b = sum(value for value in periods_b.values() if value is not None)
    state = _state(rules, period, rules.period_seconds(period) - played,
                   score_a, score_b, periods_a, periods_b)
    general = compute_general_metrics(state)
    half_first = 1 if period <= rules.halftime_after_period else 3
    completed_before = sum(rules.period_seconds(p) for p in range(half_first, period))
    assert general.half_points == expected_points
    assert general.half_elapsed_seconds == completed_before + played
    assert general.half_pace == pytest.approx(
        expected_points / ((completed_before + played) / 60), abs=1e-12)
    half_duration = sum(rules.period_seconds(p) for p in range(
        half_first, half_first + rules.regulation_quarters // 2))
    assert general.half_projection == pytest.approx(
        general.half_pace * ((half_duration - general.half_elapsed_seconds) / 60),
        abs=1e-12)


def test_cero_explicito_y_desconocido_no_son_lo_mismo():
    state = _state(
        FIBA, 3, 300, 46, 44,
        {"Q1": 21, "Q2": 25, "Q3": None, "Q4": 0},
        {"Q1": 26, "Q2": 18, "Q3": None, "Q4": 0},
    )
    rows = state.period_grid_scores()
    assert rows[2].points_a is None and rows[2].total is None
    assert rows[3].points_a == 0 and rows[3].total == 0
    assert compute_general_metrics(state).period_points is None


def test_parcial_incompleto_permite_fallback_manual():
    state = _state(
        FIBA, 3, 300, 65, 47,
        {"Q1": 21, "Q2": 25, "Q3": None},
        {"Q1": 26, "Q2": 18, "Q3": None},
    )
    state.tracker.set_manual_baseline(3, 46, 44)
    current = state.current_period_score()
    assert current.total == 22
    assert current.source is PointsSource.MANUAL


def test_actualizacion_en_vivo_reemplaza_el_parcial_anterior():
    state = _state(
        FIBA, 3, 300, 65, 47,
        {"Q1": 21, "Q2": 25, "Q3": 19},
        {"Q1": 26, "Q2": 18, "Q3": 3},
    )
    assert state.current_period_score().total == 22
    state.score_a = Observed.confirmed(67)
    state.tracker.replace_dom_breakdown(
        {"Q1": 21, "Q2": 25, "Q3": 21},
        {"Q1": 26, "Q2": 18, "Q3": 3},
    )
    assert state.current_period_score().total == 24


def test_transicion_q2_descanso_q3_conserva_1h_y_limpia_la_mitad_actual():
    state = _state(
        FIBA, 2, 0, 46, 44,
        {"Q1": 21, "Q2": 25}, {"Q1": 26, "Q2": 18},
    )
    assert compute_general_metrics(state).half_points == 90
    state.period = Observed.confirmed(3)
    state.clock_seconds = Observed.confirmed(600)
    state.tracker.replace_dom_breakdown(
        {"Q1": 21, "Q2": 25, "Q3": 0},
        {"Q1": 26, "Q2": 18, "Q3": 0},
    )
    general = compute_general_metrics(state)
    assert general.half_number == 2 and general.half_points == 0
    assert general.half_pace is None
    assert general.first_half_points == 90
    assert general.first_half_pace == pytest.approx(4.5)


def test_transicion_q3_q4_suma_ambos_cuartos_en_2h():
    state = _state(
        FIBA, 3, 0, 65, 47,
        {"Q1": 21, "Q2": 25, "Q3": 19},
        {"Q1": 26, "Q2": 18, "Q3": 3},
    )
    state.period = Observed.confirmed(4)
    state.clock_seconds = Observed.confirmed(540)
    state.score_a = Observed.confirmed(67)
    state.score_b = Observed.confirmed(48)
    state.tracker.replace_dom_breakdown(
        {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 2},
        {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 1},
    )
    general = compute_general_metrics(state)
    assert general.half_points == 25
    assert general.half_elapsed_seconds == 660
    assert general.half_pace == pytest.approx(25 / 11)


def test_overtime_se_conserva_y_no_inventa_mitad():
    state = _state(
        FIBA, 5, 120, 85, 76,
        {"Q1": 18, "Q2": 24, "Q3": 24, "Q4": 10, "OT1": 9},
        {"Q1": 22, "Q2": 20, "Q3": 19, "Q4": 8, "OT1": 7},
    )
    assert [state.rules.label(row.period) for row in state.period_grid_scores()][-1] == "OT1"
    general = compute_general_metrics(state)
    assert general.half_number is None
    assert general.half_pace is None


def test_cuadro_compacto_admite_nombres_largos_y_celdas_desconocidas():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from visorunder.ui.metrics_panel import MetricsPanel

    app = QApplication.instance() or QApplication([])
    state = _state(
        FIBA, 3, 300, 65, 47,
        {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": None},
        {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": None},
    )
    state.team_a = Observed.confirmed("Club Deportivo Baréin con Nombre Muy Largo")
    state.team_b = Observed.confirmed("Selección Nacional de Arabia Saudí")
    panel = MetricsPanel()
    panel.update_view(state, compute_general_metrics(state))
    table = panel.results_table
    assert table.rowCount() == 3 and table.columnCount() == 6
    assert table.item(0, 0).toolTip() == "Club Deportivo Baréin con Nombre Muy Largo"
    assert table.item(0, 4).text() == "--"
    assert table.item(2, 3).text() == "22"
    assert table.item(2, 5).text() == "112"
    panel.deleteLater()
    app.processEvents()


def test_panel_reordena_metricas_resalta_promedios_y_muestra_proyecciones():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from visorunder.ui.metrics_panel import MetricsPanel

    app = QApplication.instance() or QApplication([])
    state = _state(
        FIBA, 3, 5 * 60 + 18, 65, 47,
        {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0},
        {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 0},
    )
    panel = MetricsPanel()
    panel.update_view(state, compute_general_metrics(state))

    grid = panel.period_pace_label.parentWidget().layout()
    expected_titles = [
        "PROMEDIO ACTUAL Q3",
        "PUNTOS Q3",
        "PROYECCIÓN Q RESTANTE",
        "PROMEDIO ACTUAL 2H",
        "PUNTOS 2H",
        "PROYECCIÓN MITAD RESTANTE",
        "PROMEDIO ACTUAL PARTIDO",
        "PUNTOS DEL PARTIDO",
        "PROYECCIÓN PARTIDO RESTANTE",
        "MI REFERENCIA",
        "MI CUOTA UNDER OBJETIVO",
    ]
    assert [grid.itemAtPosition(row, 0).widget().text()
            for row in range(len(expected_titles))] == expected_titles
    assert panel.period_pace_label.objectName() == "paceHighlight"
    assert panel.half_pace_label.objectName() == "paceHighlight"
    assert panel.game_pace_label.objectName() == "paceHighlight"
    assert panel.required_pace_label.objectName() == "paceValue"
    assert panel.period_projection_label.text() == "24.8 pts"
    assert panel.half_projection_label.text() == "71.6 pts"
    assert panel.game_projection_label.text() == "69.4 pts"

    unknown_state = GameState(rules=FIBA)
    panel.update_view(unknown_state, compute_general_metrics(unknown_state))
    assert panel.period_projection_label.text() == "--"
    assert panel.half_projection_label.text() == "--"
    assert panel.game_projection_label.text() == "--"

    panel.deleteLater()
    app.processEvents()
