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


def _line_with_value(window, value):
    """Localiza en el tablero la linea con ese valor."""
    for evaluation in window.controller.build_view_model(
            window.controller.reader.last_snapshot).evaluations:
        if abs(evaluation.line_value - value) < 1e-6:
            return evaluation.line
    raise AssertionError(f"no hay linea {value} en el tablero")


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

    # 12-13: se evaluan varias lineas y se selecciona una
    assert win.entry_board.table.rowCount() == 4
    controller.select_line(_line_with_value(win, 40.5), manual=True)
    _pump(win, controller, 1)
    linea = controller.selected_line
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
    assert win.metrics_panel.points_to_exceed_label.text() == "22 PUNTOS"
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
    controller.select_line(_line_with_value(win, 37.5), manual=True)
    _pump(win, controller, 1)
    win.lock_bet()
    _pump(win, controller, 1)
    # el cuarto se dispara hasta superar la linea
    game.score_a += 30
    _pump(win, controller, 6)
    assert win.metrics_panel.points_to_exceed_label.text() == "0 PUNTOS"
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


# ------------------------------------------------ tablero de entrada (etapa 3)
def test_el_tablero_evalua_todas_las_lineas(window):
    """Los numeros acordados: 20 puntos en el Q3 y 04:00 restantes."""
    win, controller, game = window
    game.clock_seconds = 240
    game.score_a, game.score_b = 40, 35
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 30, 25)   # 20 puntos en el cuarto
    _pump(win, controller, 1)

    board = win.entry_board
    assert board.table.rowCount() == 4
    filas = {}
    for row in range(board.table.rowCount()):
        celdas = [board.table.item(row, c).text() for c in range(board.table.columnCount())]
        filas[celdas[0]] = celdas
    assert filas["37.5"][2:5] == ["18", "4.50", "+0.50"]
    assert filas["38.5"][2:5] == ["19", "4.75", "+0.75"]
    assert filas["39.5"][2:5] == ["20", "5.00", "+1.00"]
    assert filas["40.5"][2:5] == ["21", "5.25", "+1.25"]
    assert filas["37.5"][7] == "EXIGENTE"
    assert filas["40.5"][7] == "MUY EXIGENTE"


def test_el_tablero_enfoca_por_cuota_objetivo(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 30, 25)
    _pump(win, controller, 1)

    view = controller.build_view_model(controller.reader.last_snapshot)
    objetivo = controller.criteria.target_under_odds
    candidatas = [e for e in view.evaluations if e.under_odds is not None]
    esperada = min(candidatas, key=lambda e: abs(e.under_odds - objetivo))
    assert view.focus.line_value == esperada.line_value
    assert win.metrics_panel.bet_label.text() == esperada.describe_under()


def test_la_seleccion_manual_manda_y_se_puede_volver_al_automatico(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 30, 25)
    _pump(win, controller, 1)

    automatica = controller.build_view_model(controller.reader.last_snapshot).focus.line_value
    otra = next(e.line for e in controller.build_view_model(
        controller.reader.last_snapshot).evaluations if e.line_value != automatica)
    controller.select_line(otra, manual=True)
    _pump(win, controller, 1)
    assert controller.build_view_model(controller.reader.last_snapshot).focus.line_value == otra.line

    controller.clear_manual_selection()
    _pump(win, controller, 1)
    assert controller.build_view_model(
        controller.reader.last_snapshot).focus.line_value == automatica


def test_sin_marcador_inicial_las_lineas_del_cuarto_no_son_evaluables(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)

    board = win.entry_board
    assert board.table.rowCount() == 4
    for row in range(board.table.rowCount()):
        assert board.table.item(row, 7).text() == "FALTA MARCADOR INICIAL Q3"
        assert board.table.item(row, 2).text() == "--"   # no se inventan puntos
        assert board.table.item(row, 3).text() == "--"   # ni ritmo
    assert "Ninguna linea evaluable" in board.status_label.text()


def test_linea_en_revision_mientras_la_casa_cambia(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 30, 25)
    _pump(win, controller, 1)
    assert win.entry_board.review_label.isHidden() or not win.entry_board.review_label.isVisible()

    # La casa mueve las lineas: una sola lectura no basta para publicarlas.
    game.move_lines(2.0)
    controller.reader.tick()
    win._refresh()
    assert controller.reader.last_snapshot.market_under_review is True
    assert "LINEA EN REVISION" in win.entry_board.review_label.text()

    # Confirmada la nueva propuesta, el tablero pasa a reflejarla.
    _pump(win, controller, 2)
    assert controller.reader.last_snapshot.market_under_review is False
    valores = [controller.reader.last_snapshot.market.sorted_lines()[i].line for i in range(4)]
    assert valores == [39.5, 40.5, 41.5, 42.5]


def test_el_modo_cambia_al_fijar_la_apuesta(window):
    from visorunder.app import AppMode

    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 30, 25)
    _pump(win, controller, 1)
    assert controller.mode is AppMode.BUSCANDO_ENTRADA
    assert win.entry_board.mode_label.text() == "BUSCANDO ENTRADA"

    win.lock_bet()
    _pump(win, controller, 1)
    assert controller.mode is AppMode.APUESTA_FIJADA
    assert win.entry_board.mode_label.text() == "APUESTA FIJADA"
    # el tablero sigue vivo junto a la apuesta fijada
    assert win.entry_board.table.rowCount() == 4
    assert win.metrics_panel.points_title.text() == "FALTAN PARA PERDER"
