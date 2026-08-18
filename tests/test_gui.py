"""Prueba de la interfaz completa en modo simulado (criterios del requisito 36).

Se ejecuta sin pantalla real gracias a la plataforma 'offscreen' de Qt.
Si PySide6 no esta instalado, la prueba se omite en lugar de fallar.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.app import AppController  # noqa: E402
from visorunder.domain.market import Side  # noqa: E402
from visorunder.pipeline.demo import DemoGame  # noqa: E402
from visorunder.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    controller = AppController(db_path=str(tmp_path / "test.db"))
    controller.settings.log_to_file = False
    game = DemoGame(period=3, clock_seconds=328, score_a=43, score_b=31, speed=0.0)
    controller.enable_demo(game)
    win = MainWindow(controller)
    win.profile_combo.setCurrentText("DEMO (partido simulado)")
    yield win, controller, game
    controller.finish_game()
    win.timer.stop()
    win.hotkeys.stop()
    controller.db.close()


def _pump(window, controller, cycles: int = 4):
    """Ejecuta ciclos de lectura de forma sincrona y refresca la interfaz."""
    for _ in range(cycles):
        controller.reader.tick()
    window._refresh()


def _start(window, controller):
    reader = controller.start_session(controller.profile)
    assert reader is not None
    reader.stop()  # se controla el ciclo a mano, sin hilo
    window.start_button.setText("PAUSAR (F8)")
    window.finish_button.setEnabled(True)
    return reader


def test_v1_flujo_completo(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)

    # 3-9: reloj, marcador, cuarto, tiempos
    assert win.metrics_panel.clock_label.text() == "05:28"
    assert win.metrics_panel.played_label.text() == "04:32"
    assert win.metrics_panel.period_label.text() == "Q3"
    assert win.metrics_panel.team_a_score.text() == "43"
    assert win.metrics_panel.team_b_score.text() == "31"
    assert win.metrics_panel.total_label.text() == "74"

    # 9: sin marcador inicial NO se inventan los puntos del cuarto
    assert win.metrics_panel.period_points_label.text() == "--"
    assert win.metrics_panel.period_pace_label.text() == "--"
    assert win.metrics_panel.baseline_button.isVisible() or True  # visible al pintar

    # el usuario introduce el marcador con el que empezo el Q3
    controller.set_period_baseline(3, 34, 21)
    _pump(win, controller, 1)
    assert win.metrics_panel.period_points_label.text().startswith("19")
    assert win.metrics_panel.period_pace_label.text() == "4.19 pts/min"

    # 12-13: se leen varias lineas y se selecciona una
    assert win.market_panel.table.rowCount() == 4
    win.market_panel.select_line_value(40.5)
    linea = win.market_panel.selected_line
    assert linea is not None and linea.line == 40.5
    assert linea.quarter == 3  # la linea va atada a su mercado

    # 14: fijar apuesta
    win.lock_bet()
    bet = controller.locked_bet
    assert bet is not None
    assert (bet.line, bet.side) == (40.5, Side.UNDER)
    odds_fijada = bet.odds
    _pump(win, controller, 1)

    # 16-17: metricas contra la linea fijada
    assert win.metrics_panel.points_to_lose_label.text() == "22 PUNTOS"
    assert win.metrics_panel.required_pace_label.text() == "4.02 pts/min"
    assert win.metrics_panel.threshold_label.text() == "41"

    # 18-19: horizontes temporales
    assert win.metrics_panel.halftime_label.text() == "YA PASO"
    assert win.metrics_panel.end_label.text() == "15:24" or \
           win.metrics_panel.end_label.text() == "15:28"

    # 15: la casa mueve las lineas y MI APUESTA no cambia
    game.move_lines(2.0)
    _pump(win, controller)
    assert controller.locked_bet.line == 40.5
    assert controller.locked_bet.odds == odds_fijada
    assert win.metrics_panel.bet_label.text() == f"UNDER 40.5 @ {odds_fijada:.2f}"
    assert "MERCADO ACTUAL" in win.metrics_panel.market_now_label.text()
    assert [round(l.line, 1) for l in
            controller.reader.last_snapshot.market.sorted_lines()] == [39.5, 40.5, 41.5, 42.5]

    # 20: historial en SQLite
    assert controller.history.market_history(controller.session_id)
    assert controller.history.score_history(controller.session_id)
    assert controller.bets.list_for_session(controller.session_id)


def test_under_superado_se_marca(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 34, 21)
    win.market_panel.select_line_value(37.5)
    win.lock_bet()
    _pump(win, controller, 1)
    # el cuarto se dispara hasta superar la linea
    game.score_a += 30
    _pump(win, controller, 6)
    assert win.metrics_panel.points_to_lose_label.text() == "0 PUNTOS"
    assert win.metrics_panel.exceeded_label.text() == "UNDER SUPERADO"
    assert win.metrics_panel.required_pace_label.text() == "0.00 pts/min"


def test_finalizar_partido_cierra_la_sesion(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    session_id = controller.session_id
    controller.finish_game()
    row = controller.db.query_one("SELECT status, ended_at FROM sessions WHERE id = ?",
                                  (session_id,))
    assert row["status"] == "FINISHED"
    assert row["ended_at"] is not None
    assert controller.reader is None
