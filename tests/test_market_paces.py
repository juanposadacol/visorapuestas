"""Promedios actual y faltante resueltos por el ambito de cada mercado."""

import math
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visorunder.calculations.entry import evaluate_line
from visorunder.calculations.metrics import compute_bet_metrics, compute_general_metrics
from visorunder.config.criteria import EntryCriteria
from visorunder.domain.event_markets import FreshnessState
from visorunder.domain.game_state import GameState
from visorunder.domain.market import MarketKey, MarketLine
from visorunder.domain.rules import FIBA, NBA
from visorunder.domain.values import Observed
from visorunder.ui.entry_board import COL_CURRENT_PACE, COL_MISSING_PACE, COL_POINTS


def _state(*, rules=FIBA, period, remaining, periods):
    state = GameState(rules=rules)
    state.period = Observed.confirmed(period)
    state.clock_seconds = Observed.confirmed(remaining)
    labels_a = {}
    labels_b = {}
    for number, (points_a, points_b) in periods.items():
        label = rules.label(number)
        labels_a[label] = points_a
        labels_b[label] = points_b
    state.tracker.replace_dom_breakdown(labels_a, labels_b)
    state.score_a = Observed.confirmed(sum(pair[0] for pair in periods.values()))
    state.score_b = Observed.confirmed(sum(pair[1] for pair in periods.values()))
    return state


def _line(key, value=42.5):
    return MarketLine(
        sportsbook="BetPlay", event="A vs B", key=key, line=value,
        over_odds=1.90, under_odds=1.90, confirmed=True,
    )


def test_regresion_fiba_q1_separa_promedio_actual_y_faltante():
    state = _state(period=1, remaining=400, periods={1: (7, 8)})

    metrics = compute_bet_metrics(state, MarketKey.quarter(1), 42.5)

    assert metrics.scope_points == 15
    assert metrics.scope_elapsed_seconds == 200
    assert metrics.scope_remaining_seconds == 400
    assert metrics.current_pace == pytest.approx(4.50)
    assert metrics.exceed_threshold == 43
    assert metrics.points_to_exceed == 28
    assert metrics.required_pace == pytest.approx(4.20)


@pytest.mark.parametrize(
    ("period", "remaining", "key", "periods", "points", "elapsed", "pace"),
    [
        (2, 400, MarketKey.quarter(2), {1: (20, 20), 2: (7, 8)}, 15, 200, 4.50),
        (3, 318, MarketKey.quarter(3), {1: (20, 20), 2: (19, 21), 3: (10, 12)},
         22, 282, 22 / 4.7),
        (4, 300, MarketKey.quarter(4),
         {1: (20, 20), 2: (19, 21), 3: (18, 22), 4: (11, 9)}, 20, 300, 4.0),
        (2, 400, MarketKey.half_market(1), {1: (20, 20), 2: (7, 8)},
         55, 800, 55 / (800 / 60)),
        (4, 300, MarketKey.half_market(2),
         {1: (20, 20), 2: (19, 21), 3: (18, 22), 4: (11, 9)},
         60, 900, 4.0),
    ],
)
def test_promedio_actual_de_cuartos_y_mitades_usa_su_scope(
        period, remaining, key, periods, points, elapsed, pace):
    metrics = compute_bet_metrics(
        _state(period=period, remaining=remaining, periods=periods), key, 90.5)

    assert metrics.scope_points == points
    assert metrics.scope_elapsed_seconds == elapsed
    assert metrics.current_pace == pytest.approx(pace)
    assert metrics.required_pace == pytest.approx(
        (91 - points) / (metrics.scope_remaining_seconds / 60))


@pytest.mark.parametrize(
    ("rules", "period", "remaining", "periods", "elapsed"),
    [
        (FIBA, 1, 400, {1: (7, 8)}, 200),
        (FIBA, 2, 400, {1: (20, 20), 2: (7, 8)}, 800),
        (FIBA, 3, 300, {1: (20, 20), 2: (19, 21), 3: (10, 10)}, 1500),
        (FIBA, 4, 300,
         {1: (20, 20), 2: (19, 21), 3: (18, 22), 4: (11, 9)}, 2100),
        (NBA, 2, 520, {1: (28, 27), 2: (9, 8)}, 920),
    ],
)
def test_promedio_actual_de_partido_en_cada_cuarto_y_reglas(
        rules, period, remaining, periods, elapsed):
    state = _state(
        rules=rules, period=period, remaining=remaining, periods=periods)
    metrics = compute_bet_metrics(state, MarketKey.game(), 180.5)
    total = sum(a + b for a, b in periods.values())

    assert metrics.scope_points == total
    assert metrics.scope_elapsed_seconds == elapsed
    assert metrics.current_pace == pytest.approx(total / (elapsed / 60))
    assert metrics.required_pace == pytest.approx(
        (181 - total) / (metrics.scope_remaining_seconds / 60))


def test_overtime_usa_duracion_de_game_rules():
    state = _state(
        period=5, remaining=200,
        periods={1: (20, 20), 2: (20, 20), 3: (20, 20), 4: (20, 20), 5: (4, 6)},
    )

    overtime = compute_bet_metrics(state, MarketKey.quarter(5), 20.5)
    game = compute_bet_metrics(state, MarketKey.game(), 180.5)

    assert overtime.scope_elapsed_seconds == FIBA.overtime_seconds - 200 == 100
    assert overtime.current_pace == pytest.approx(6.0)
    assert overtime.required_pace == pytest.approx(11 / (200 / 60))
    assert game.scope_elapsed_seconds == FIBA.regulation_seconds + 100
    assert game.current_pace == pytest.approx(170 / (2500 / 60))


def test_cero_jugado_y_dato_desconocido_no_inventan_promedio_actual():
    not_started = _state(period=1, remaining=600, periods={1: (0, 0)})
    assert compute_bet_metrics(
        not_started, MarketKey.quarter(1), 42.5).current_pace is None

    unknown = GameState(rules=FIBA)
    metrics = compute_bet_metrics(unknown, MarketKey.game(), 42.5)
    assert metrics.scope_elapsed_seconds is None
    assert metrics.current_pace is None
    assert metrics.required_pace is None


def test_limites_de_promedio_faltante_con_lineas_decimal_y_entera():
    state = _state(period=1, remaining=0, periods={1: (7, 8)})
    decimal = compute_bet_metrics(state, MarketKey.quarter(1), 42.5)
    integer = compute_bet_metrics(state, MarketKey.quarter(1), 42.0)

    assert decimal.exceed_threshold == integer.exceed_threshold == 43
    assert math.isinf(decimal.required_pace)
    assert math.isinf(integer.required_pace)

    exceeded = _state(period=1, remaining=100, periods={1: (22, 22)})
    metrics = compute_bet_metrics(exceeded, MarketKey.quarter(1), 42.5)
    assert metrics.points_to_exceed == 0
    assert metrics.required_pace == 0.0


def test_fixture_fiba_se_muestra_correctamente_en_panel_y_fila():
    from PySide6.QtWidgets import QApplication
    from visorunder.ui.entry_board import MarketBlock
    from visorunder.ui.metrics_panel import MetricsPanel

    app = QApplication.instance() or QApplication([])

    state = _state(period=1, remaining=400, periods={1: (7, 8)})
    criteria = EntryCriteria()
    general = compute_general_metrics(state)
    evaluation = evaluate_line(state, _line(MarketKey.quarter(1)), criteria, general)

    panel = MetricsPanel()
    panel.update_view(state, general, evaluation=evaluation, criteria=criteria)
    assert panel.period_points_label.text().startswith("15")
    assert panel.period_pace_label.text() == "4.50 pts/min"
    assert panel.required_pace_label.text() == "4.20 pts/min"
    assert "8.12" not in panel.required_pace_label.text()

    block = MarketBlock(MarketKey.quarter(1))
    data = SimpleNamespace(
        evaluations=[evaluation], freshness=FreshnessState.LIVE,
        label=MarketKey.quarter(1).label, age_text=lambda now=None: "ahora",
    )
    block.update_block(data, criteria)
    assert block.table.item(0, COL_CURRENT_PACE).text() == "4.50"
    assert block.table.item(0, COL_POINTS).text() == "28"
    assert block.table.item(0, COL_MISSING_PACE).text() == "4.20"
    panel.deleteLater()
    block.deleteLater()
    app.processEvents()
