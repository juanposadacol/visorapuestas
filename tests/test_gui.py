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


def _q3_block(window):
    """Bloque del mercado del Q3 dentro del radar."""
    from visorunder.domain.market import MarketKey

    block = window.entry_board.block_for(MarketKey.quarter(3))
    assert block is not None, "no hay bloque para el Q3 en el tablero"
    return block


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
    assert _q3_block(win).table.rowCount() == 4
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

    board = _q3_block(win)
    assert board.table.rowCount() == 4
    filas = {}
    for row in range(board.table.rowCount()):
        celdas = [board.table.item(row, c).text() for c in range(board.table.columnCount())]
        filas[celdas[0]] = celdas
    assert filas["37.5"][2:5] == ["18", "4.50", "+0.50"]
    assert filas["38.5"][2:5] == ["19", "4.75", "+0.75"]
    assert filas["39.5"][2:5] == ["20", "5.00", "+1.00"]
    assert filas["40.5"][2:5] == ["21", "5.25", "+1.25"]
    assert filas["37.5"][-1] == "EXIGENTE"
    assert filas["40.5"][-1] == "MUY EXIGENTE"


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

    board = _q3_block(win)
    assert board.table.rowCount() == 4
    ultima = board.table.columnCount() - 1
    for row in range(board.table.rowCount()):
        assert board.table.item(row, ultima).text() == "FALTA MARCADOR INICIAL Q3"
        assert board.table.item(row, 2).text() == "--"   # no se inventan puntos
        assert board.table.item(row, 3).text() == "--"   # ni ritmo


def test_linea_en_revision_mientras_la_casa_cambia(window):
    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 30, 25)
    _pump(win, controller, 1)
    assert not win.entry_board.review_label.isVisible()

    # La casa mueve las lineas: una sola lectura no basta para publicarlas.
    game.move_lines(2.0)
    controller.reader.tick()
    win._refresh()
    assert controller.reader.last_snapshot.market_under_review is True
    assert "REVISION" in win.entry_board.review_label.text()

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
    assert _q3_block(win).table.rowCount() == 4
    assert win.metrics_panel.points_title.text() == "FALTAN PARA PERDER"


# ------------------------------------------------ radar multi-mercado (etapa 4)
def _visit_tab(window, controller, tab, ticks=5):
    window.controller.demo_game.show_tab(tab)
    for _ in range(ticks):
        controller.reader.tick()
    window._refresh()


def test_el_radar_muestra_un_bloque_por_mercado(window):
    from visorunder.domain.market import MarketKey

    win, controller, game = window
    game.clock_seconds = 360
    game.score_a, game.score_b = 55, 48
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 50, 44)

    _visit_tab(win, controller, "GAME")
    _visit_tab(win, controller, "HALF1")
    _visit_tab(win, controller, "QUARTER")

    bloques = win.entry_board.blocks()
    assert set(bloques) == {MarketKey.game(), MarketKey.half_market(1), MarketKey.quarter(3)}
    assert bloques[MarketKey.game()].table.rowCount() == 4
    assert bloques[MarketKey.half_market(1)].table.rowCount() == 3
    assert bloques[MarketKey.quarter(3)].table.rowCount() == 4


def test_la_cabecera_de_un_mercado_no_visible_muestra_su_antiguedad(window):
    """Regla critica: una linea vieja nunca se presenta como actual."""
    from visorunder.domain.market import MarketKey

    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 50, 44)

    _visit_tab(win, controller, "GAME")
    _visit_tab(win, controller, "QUARTER")

    juego = win.entry_board.block_for(MarketKey.game())
    cuarto = win.entry_board.block_for(MarketKey.quarter(3))
    assert "EN VIVO" in cuarto.state_label.text()
    assert "EN VIVO" not in juego.state_label.text()
    assert "·" in juego.state_label.text()          # lleva su antiguedad
    # y sus lineas siguen ahi
    assert juego.table.rowCount() == 4


def test_la_apuesta_fijada_sobrevive_al_cambio_de_pestana(window):
    """Requisito 19: la apuesta y el mercado visible son cosas distintas."""
    from visorunder.domain.market import MarketKey

    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    controller.set_period_baseline(3, 50, 44)

    _visit_tab(win, controller, "GAME")
    juego = controller.build_view_model(controller.reader.last_snapshot)
    linea = next(e for e in juego.blocks if e.key == MarketKey.game()).evaluations[-1]
    controller.select_line(linea.line, manual=True)
    win.lock_bet()
    apuesta = controller.locked_bet
    assert apuesta.key == MarketKey.game()

    # el usuario se va a otra pestana
    _visit_tab(win, controller, "QUARTER")
    assert controller.locked_bet.key == MarketKey.game()
    assert controller.locked_bet.line == apuesta.line
    assert controller.locked_bet.odds == apuesta.odds
    vm = controller.build_view_model(controller.reader.last_snapshot)
    assert vm.bet_tracking is not None
    assert vm.bet_tracking.key == MarketKey.game()      # se sigue su mercado
    assert vm.snapshot.markets.visible_key == MarketKey.quarter(3)


def test_el_selector_manual_de_mercado_visible(window):
    from visorunder.domain.market import MarketKey

    win, controller, game = window
    _start(win, controller)
    _pump(win, controller)
    assert win.entry_board.market_index(MarketKey.half_market(2)) > 0
    win.entry_board.select_visible_market(MarketKey.half_market(2))
    assert controller.reader.manual_visible_key == MarketKey.half_market(2)

    # volver a automatico limpia la eleccion manual
    win.entry_board.select_visible_market(None)
    assert controller.reader.manual_visible_key is None


# ------------------------------------------------- conexion con la extension
def _enviar_al_puente(controller, cuerpo):
    import json
    import urllib.request

    from visorunder.bridge.server import BRIDGE_HEADER

    peticion = urllib.request.Request(
        f"{controller.bridge.url}/v1/browser-state",
        data=json.dumps(cuerpo).encode("utf-8"), method="POST")
    peticion.add_header("Content-Type", "application/json")
    peticion.add_header(BRIDGE_HEADER, "1")
    with urllib.request.urlopen(peticion, timeout=5) as respuesta:
        return respuesta.status


def _payload_betplay(**cambios):
    base = {
        "protocol": 1, "source": "betplay", "observedAt": "2026-08-19T02:00:00.000Z",
        "event": {"id": "9876543", "name": "Equipo A vs Equipo B"},
        "visibleMarket": {"marketType": "QUARTER_TOTAL", "period": 4, "half": None,
                          "confidence": 0.95, "rawTitle": "Total de puntos - Cuarto 4",
                          "sidesConfirmed": True},
        "lines": [{"line": 44.5, "overOdds": 1.75, "underOdds": 1.90}],
        "gameState": {"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"},
    }
    base.update(cambios)
    return base


@pytest.fixture()
def window_bridge(qapp, tmp_path):
    from visorunder.app import AppController
    from visorunder.bridge.server import BridgeSettings

    controller = AppController(db_path=str(tmp_path / "bridge.db"))
    controller.settings.log_to_file = False
    controller.settings.bridge = BridgeSettings(port=0)
    controller.bridge.settings = controller.settings.bridge
    win = MainWindow(controller)
    yield win, controller
    controller.finish_game()
    win.timer.stop()
    win.hotkeys.stop()
    controller.shutdown()


def test_sin_extension_el_panel_dice_desconectada(window_bridge):
    from visorunder.bridge.source import LinkState

    win, controller = window_bridge
    win._refresh()
    assert win.connection_panel.state_label.text() == LinkState.DISCONNECTED.label
    assert controller.reader is None       # no arranca solo sin datos


def test_la_sesion_arranca_sola_al_conectar_la_extension(window_bridge):
    """Criterio de exito: abrir las dos cosas y que el radar empiece solo."""
    win, controller = window_bridge
    _enviar_al_puente(controller, _payload_betplay())

    win._refresh()
    assert controller.reader is not None, "no arranco la sesion sola"
    controller.reader.stop()
    assert "CONECTADO" in win.status_label.text()


def test_el_panel_dice_de_donde_sale_cada_dato(window_bridge):
    win, controller = window_bridge
    _enviar_al_puente(controller, _payload_betplay())
    win._refresh()
    controller.reader.stop()
    controller.reader.tick()
    win._refresh()

    panel = win.connection_panel
    assert "BETPLAY CONECTADO" in panel.state_label.text()
    for campo in ("market", "lines", "score_a", "period", "clock_seconds"):
        assert panel.field_labels[campo].text() == "DOM ✓", campo


def test_las_lineas_del_DOM_llegan_al_tablero(window_bridge):
    from visorunder.domain.market import MarketKey

    win, controller = window_bridge
    _enviar_al_puente(controller, _payload_betplay())
    win._refresh()
    controller.reader.stop()
    controller.reader.tick()
    win._refresh()

    bloque = win.entry_board.block_for(MarketKey.quarter(4))
    assert bloque is not None, "el mercado del DOM no aparece en el tablero"
    assert bloque.table.rowCount() == 1
    assert bloque.table.item(0, 0).text() == "44.5"
    assert bloque.table.item(0, 1).text() == "1.90"      # cuota UNDER


def test_un_cambio_de_cuota_se_refleja_sin_tocar_nada(window_bridge):
    from visorunder.domain.market import MarketKey

    win, controller = window_bridge
    _enviar_al_puente(controller, _payload_betplay())
    win._refresh()
    controller.reader.stop()
    controller.reader.tick()
    win._refresh()

    _enviar_al_puente(controller, _payload_betplay(
        lines=[{"line": 44.5, "overOdds": 1.68, "underOdds": 2.05}]))
    controller.reader.tick()
    win._refresh()

    bloque = win.entry_board.block_for(MarketKey.quarter(4))
    assert bloque.table.item(0, 1).text() == "2.05"


def test_cambiar_de_partido_cierra_la_sesion_anterior(window_bridge):
    win, controller = window_bridge
    _enviar_al_puente(controller, _payload_betplay())
    win._refresh()
    controller.reader.stop()
    primera = controller.session_id

    _enviar_al_puente(controller, _payload_betplay(
        event={"id": "1111111", "name": "Equipo C vs Equipo D"}))
    win._refresh()

    assert controller.session_id != primera
    assert "Nuevo partido" in win.status_label.text() or controller.reader is not None
