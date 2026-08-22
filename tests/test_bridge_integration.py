"""De extremo a extremo: la extension envia y la aplicacion lo usa.

Se comprueba el criterio de exito de esta etapa: con la extension conectada,
poder empezar SIN dibujar ninguna region.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visorunder.app import AppController
from visorunder.bridge.server import BRIDGE_HEADER, BridgeSettings
from visorunder.bridge.source import LinkState, SourceKind
from visorunder.capture.roi import Rect, RoiKind
from visorunder.capture.screen_capture import NullCapture
from visorunder.config.profiles import SportsbookProfile
from visorunder.domain.market import MarketKey
from visorunder.domain.event_markets import FreshnessState


def payload(**cambios):
    base = {
        "protocol": 1, "source": "betplay",
        "observedAt": "2026-08-19T02:00:00.000Z",
        "event": {"id": "9876543", "name": "Equipo A vs Equipo B"},
        "visibleMarket": {"marketType": "QUARTER_TOTAL", "period": 4, "half": None,
                          "confidence": 0.95, "rawTitle": "Total de puntos - Cuarto 4",
                          "sidesConfirmed": True},
        "lines": [{"line": 44.5, "overOdds": 1.75, "underOdds": 1.90}],
        "gameState": None,
    }
    base.update(cambios)
    return base


@pytest.fixture()
def app(tmp_path):
    controlador = AppController(db_path=str(tmp_path / "test.db"), capture=NullCapture())
    controlador.settings.log_to_file = False
    controlador.settings.bridge = BridgeSettings(port=0)
    controlador.bridge.settings = controlador.settings.bridge
    yield controlador
    controlador.shutdown()


def enviar(controlador, cuerpo):
    peticion = urllib.request.Request(
        f"{controlador.bridge.url}/v1/browser-state",
        data=json.dumps(cuerpo).encode("utf-8"), method="POST")
    peticion.add_header("Content-Type", "application/json")
    peticion.add_header(BRIDGE_HEADER, "1")
    peticion.add_header("Origin", "chrome-extension://abcdefghijklmnopabcdefghijklmnop")
    with urllib.request.urlopen(peticion, timeout=5) as respuesta:
        return respuesta.status


# --------------------------------------------------------------- arranque
def test_la_aplicacion_abre_aunque_no_haya_extension(app):
    assert app.link_state is LinkState.DISCONNECTED
    assert app.dom_fields() == []
    # y sigue pudiendo trabajar con OCR o en modo demo
    assert app.browser_profile().name


def test_el_puente_arranca_y_responde(app):
    assert app.start_bridge()
    with urllib.request.urlopen(f"{app.bridge.url}/health", timeout=5) as respuesta:
        cuerpo = json.loads(respuesta.read().decode("utf-8"))
    assert cuerpo["app"] == "VisorApuestas"


def test_un_paquete_real_llega_hasta_la_fuente(app):
    assert app.start_bridge()
    assert enviar(app, payload()) == 200
    assert app.link_state is LinkState.LIVE
    snapshot = app.browser.snapshot()
    assert snapshot.key == MarketKey.quarter(4)
    assert snapshot.lines[0].under_odds == 1.90


# ------------------------------------------------- regiones ya no obligatorias
def test_sin_extension_y_sin_perfil_faltan_todos_los_datos(app):
    faltan = app.missing_requirements(None)
    assert "mercado y lineas" in faltan
    assert "reloj" in faltan and "cuarto" in faltan and "marcador" in faltan


def test_con_mercado_por_DOM_deja_de_hacer_falta_esa_region(app):
    app.start_bridge()
    enviar(app, payload())
    faltan = app.missing_requirements(None)
    assert "mercado y lineas" not in faltan      # lo aporta el DOM
    assert "reloj" in faltan                     # esto todavia no


def test_con_todo_por_DOM_no_hace_falta_ninguna_region(app):
    app.start_bridge()
    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}))
    assert app.missing_requirements(None) == []


def test_arranca_una_sesion_sin_dibujar_ninguna_region(app):
    """Criterio de exito de la etapa."""
    app.start_bridge()
    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}))

    lector = app.start_session(None)      # sin perfil y sin regiones
    assert lector is not None
    assert lector.roi_manager.profile.rois == {}
    lector.stop()

    snapshot = lector.tick()
    assert snapshot.markets.visible_key == MarketKey.quarter(4)
    assert snapshot.state.score_a_value == 58
    assert snapshot.state.clock_value == 384
    assert snapshot.state.period_value == 4


def test_las_fuentes_quedan_registradas(app):
    app.start_bridge()
    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}))
    lector = app.start_session(None)
    lector.stop()
    snapshot = lector.tick()

    assert snapshot.field_sources["market"] == SourceKind.BROWSER_DOM.value
    assert snapshot.field_sources["score_a"] == SourceKind.BROWSER_DOM.value
    assert snapshot.field_sources["clock_seconds"] == SourceKind.BROWSER_DOM.value


def test_una_region_a_medias_se_combina_con_el_DOM(app):
    """DOM para mercado, ROI para reloj y cuarto: tambien es valido."""
    perfil = SportsbookProfile(name="Mixto", sportsbook="BetPlay", frame=Rect(0, 0, 1920, 1080))
    perfil.set_roi(RoiKind.CLOCK, Rect(10, 10, 100, 40))
    perfil.set_roi(RoiKind.PERIOD, Rect(120, 10, 60, 40))
    perfil.set_roi(RoiKind.SCORE_PAIR, Rect(200, 10, 200, 40))

    app.start_bridge()
    enviar(app, payload())                        # solo mercado por DOM
    assert app.missing_requirements(perfil) == []


def test_el_radar_recibe_las_lineas_del_DOM(app):
    app.start_bridge()
    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}))
    lector = app.start_session(None)
    lector.stop()
    lector.tick()

    vista = app.build_view_model(lector.last_snapshot)
    bloques = [b for b in vista.blocks if b.key == MarketKey.quarter(4)]
    assert bloques, "el mercado del DOM no llego al radar"
    evaluacion = bloques[0].evaluations[0]
    assert evaluacion.line_value == 44.5
    assert evaluacion.under_odds == 1.90
    assert vista.link_state is LinkState.LIVE


# ------------------------------------------------------------- conflictos
def test_un_conflicto_entre_DOM_y_OCR_no_se_resuelve_en_silencio(app):
    app.start_bridge()
    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}))
    lector = app.start_session(None)
    lector.stop()

    # El OCR habia confirmado otro cuarto. Se alimenta el estabilizador, que
    # es de donde sale el valor del OCR en cada ciclo.
    lector.period.set_manual(2)
    lector.tick()

    assert any(c["field"] == "period" for c in lector.source_conflicts)
    conflicto = [c for c in lector.source_conflicts if c["field"] == "period"][0]
    assert conflicto["dom"] == 4 and conflicto["ocr"] == 2
    # se prefiere el DOM, pero queda registrado
    assert lector.state.period_value == 4


# ------------------------------------------------------------- desconexion
def test_si_dejan_de_llegar_paquetes_el_enlace_caduca(app):
    app.start_bridge()
    enviar(app, payload())
    assert app.browser.link_state() is LinkState.LIVE
    futuro = time.time() + 30
    assert app.browser.link_state(futuro) is LinkState.DISCONNECTED
    assert app.browser.snapshot(futuro) is None
    # pero se conserva para poder decir ULTIMA LINEA OBSERVADA
    assert app.browser.last_snapshot_any_age() is not None


def test_cerrar_la_aplicacion_libera_el_puerto(tmp_path):
    controlador = AppController(db_path=str(tmp_path / "t.db"), capture=NullCapture())
    controlador.settings.log_to_file = False
    controlador.settings.bridge = BridgeSettings(port=0)
    controlador.bridge.settings = controlador.settings.bridge
    controlador.start_bridge()
    assert controlador.bridge.is_running
    controlador.shutdown()
    assert not controlador.bridge.is_running


# ------------------------------------- la extension conectada, aunque sin mercado
#
# El caso REAL que dio origen a esto: `Invoke-RestMethod http://127.0.0.1:8765/health`
# respondia `status: ok` y el panel decia EXTENSION DESCONECTADA, porque la
# aplicacion solo se enteraba de la extension cuando llegaba un mercado. La
# extension consulta /health cada pocos segundos aunque no tenga nada que enviar.

def _health(app):
    peticion = urllib.request.Request(f"{app.bridge.url}/health", method="GET")
    peticion.add_header(BRIDGE_HEADER, "1")
    with urllib.request.urlopen(peticion, timeout=5) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def test_un_latido_de_health_ya_cuenta_como_extension_conectada(app):
    from visorunder.app import SessionState
    from visorunder.bridge.source import ExtensionState

    app.start_bridge()
    assert app.browser.extension_state() is ExtensionState.DISCONNECTED

    cuerpo = _health(app)
    assert cuerpo["status"] == "ok"

    assert app.browser.extension_state() is ExtensionState.CONNECTED, \
        "la extension esta ahi aunque todavia no haya reconocido ningun mercado"
    assert app.browser.link_state() is LinkState.DISCONNECTED, \
        "pero los datos siguen sin llegar, y eso se dice aparte"
    assert app.session_state is SessionState.WAITING_FOR_DATA
    assert "mercado y lineas" in app.missing_requirements(None)


def test_health_sin_la_cabecera_del_protocolo_no_cuenta_como_extension(app):
    from visorunder.bridge.source import ExtensionState

    app.start_bridge()
    with urllib.request.urlopen(f"{app.bridge.url}/health", timeout=5) as respuesta:
        assert respuesta.status == 200
    assert app.browser.extension_state() is ExtensionState.DISCONNECTED, \
        "cualquiera puede pedir /health; solo la extension manda la cabecera"


def test_el_puente_cuenta_los_latidos(app):
    app.start_bridge()
    _health(app)
    _health(app)
    assert app.bridge.stats.health_checks == 2
    assert app.bridge.stats.last_extension_contact_at is not None


# ------------------------------------------------------- arranque por estados
def test_los_estados_del_arranque(app):
    from visorunder.app import SessionState

    app.start_bridge()
    assert app.session_state is SessionState.WAITING_FOR_DATA
    assert app.session_state.label == "ESPERANDO DATOS"

    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52,
                                   "period": 4, "clock": "06:24"}))
    assert app.session_state is SessionState.READY

    lector = app.start_session(app.profile)
    assert lector is not None
    assert app.session_state is SessionState.RUNNING
    lector.stop()


def test_un_mercado_sin_marcador_deja_la_sesion_esperando_pero_no_la_rompe(app):
    from visorunder.app import SessionState
    from visorunder.bridge.source import ExtensionState

    app.start_bridge()
    enviar(app, payload(gameState=None))

    # El mercado SI llega: que falte el marcador no lo bloquea.
    assert app.browser.snapshot() is not None
    assert app.browser.snapshot().lines[0].under_odds == 1.90
    assert app.dom_fields() == ["market", "lines"]

    # Y el arranque espera, diciendo exactamente que falta.
    assert app.extension_state is ExtensionState.CONNECTED
    assert app.session_state is SessionState.WAITING_FOR_DATA
    faltan = app.missing_requirements(None)
    assert "marcador" in faltan and "reloj" in faltan and "cuarto" in faltan
    assert "mercado y lineas" not in faltan


def test_un_gameState_parcial_reduce_lo_que_falta(app):
    app.start_bridge()
    enviar(app, payload(gameState={"period": 4, "clock": "06:24"}))
    faltan = app.missing_requirements(None)
    assert "marcador" in faltan
    assert "reloj" not in faltan and "cuarto" not in faltan


# ------------------------- el reloj de Kambi: "Q4 - 33:52" es tiempo jugado
#
# Caso real de BetPlay. 33:52 no puede ser el restante de un cuarto. Con FIBA
# (4x10) el cuarto 4 va de 30:00 a 40:00, asi que quedan 06:08. Con NBA (4x12)
# ese mismo valor no cae dentro del cuarto 4: el mismo numero, dos respuestas.
# Por eso convierte quien conoce las reglas, y no la extension.

def _payload_kambi(**cambios):
    estado = {"scoreA": 76, "scoreB": 69, "period": 4,
              "clockRaw": "33:52", "clockSemantics": "GAME_ELAPSED",
              "teamA": "Dallas Wings (F)", "teamB": "Indiana Fever (F)"}
    estado.update(cambios)
    return payload(gameState=estado)


def test_el_tiempo_jugado_se_convierte_a_restante_del_cuarto(app):
    from visorunder.domain.rules import FIBA

    app.start_bridge()
    enviar(app, _payload_kambi())
    lector = app.start_session(app.profile)
    assert lector is not None
    lector.rules = FIBA
    lector.stop()
    lector.tick()

    # 40:00 - 33:52 = 06:08
    assert lector.state.clock_value == 6 * 60 + 8
    assert lector.state.score_a.usable_value() == 76
    assert lector.state.score_b.usable_value() == 69
    assert lector.field_sources["clock_seconds"] is SourceKind.BROWSER_DOM


def test_con_reglas_que_no_cuadran_se_prefiere_quedarse_sin_reloj(app):
    from visorunder.domain.rules import NBA

    app.start_bridge()
    enviar(app, _payload_kambi())
    lector = app.start_session(app.profile)
    lector.rules = NBA           # 4x12: el cuarto 4 empieza en 36:00
    lector.stop()
    lector.tick()

    assert lector.state.clock_value is None, \
        "33:52 no cae dentro del cuarto 4 con NBA: mejor sin reloj que equivocado"
    # Pero el marcador SI llega: un reloj dudoso no bloquea el resto.
    assert lector.state.score_a.usable_value() == 76


def test_el_restante_directo_sigue_funcionando_igual(app):
    app.start_bridge()
    enviar(app, payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4,
                                   "clock": "06:24"}))
    lector = app.start_session(app.profile)
    lector.stop()
    lector.tick()
    assert lector.state.clock_value == 6 * 60 + 24


def test_el_reloj_acumulado_no_bloquea_el_arranque(app):
    from visorunder.app import SessionState

    app.start_bridge()
    enviar(app, _payload_kambi())
    assert app.session_state is SessionState.READY, \
        "el DOM da marcador, cuarto y reloj: no falta nada para empezar"
    assert app.missing_requirements(None) == []


def test_fixture_real_llega_hasta_metricas_sin_marcador_manual(app):
    from visorunder.calculations.metrics import compute_general_metrics

    app.start_bridge()
    enviar(app, payload(gameState={
        "scoreA": 65, "scoreB": 47, "period": 3,
        "clockRaw": "24:42", "clockSemantics": "GAME_ELAPSED",
        "teamA": {"name": "Baréin", "total": 65,
                  "periods": {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0}},
        "teamB": {"name": "Arabia Saudí", "total": 47,
                  "periods": {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 0}},
    }))
    reader = app.start_session(app.profile)
    assert reader is not None
    reader.stop()
    snapshot = reader.tick()
    general = compute_general_metrics(snapshot.state)

    assert snapshot.state.team_a.usable_value() == "Baréin"
    assert snapshot.needs_period_baseline is False
    assert general.period_points == 22
    assert general.period_pace == pytest.approx(22 / 4.7)
    assert general.half_points == 22
    assert general.first_half_points == 90


def test_regresion_real_llega_al_cuadro_metricas_y_vs_mitad(app):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from visorunder.ui.entry_board import COL_HALF
    from visorunder.ui.main_window import MainWindow

    app.start_bridge()
    enviar(app, payload(
        visibleMarket={"marketType": "GAME_TOTAL", "period": None, "half": None,
                       "confidence": 0.95,
                       "rawTitle": "Total de puntos - Prórroga incluida",
                       "sidesConfirmed": True},
        lines=[{"line": 170.5, "overOdds": 1.67, "underOdds": 2.00}],
        gameState={
            "scoreA": 65, "scoreB": 47, "period": 3,
            "clockRaw": "24:42", "clockSemantics": "GAME_ELAPSED",
            "teamA": {"name": "Baréin", "total": 65,
                      "periods": {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0}},
            "teamB": {"name": "Arabia Saudí", "total": 47,
                      "periods": {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 0}},
        },
    ))
    reader = app.start_session(app.profile)
    reader.stop()
    snapshot = reader.tick()
    view = app.build_view_model(snapshot)

    qapp = QApplication.instance() or QApplication([])
    window = MainWindow(app)
    window.timer.stop()
    window.hotkeys.stop()
    window._refresh()
    panel = window.metrics_panel
    board = window.entry_board

    table = panel.results_table
    assert [[table.item(row, column).text() for column in range(1, 6)]
            for row in range(3)] == [
        ["21", "25", "19", "0", "65"],
        ["26", "18", "3", "0", "47"],
        ["47", "43", "22", "0", "112"],
    ]
    assert table.item(0, 0).text() == "Baréin"
    assert table.item(1, 0).text() == "Arabia Saudí"
    assert panel.period_points_title.text() == "PUNTOS Q3"
    assert panel.period_points_label.text() == "22   (19 - 3)"
    assert panel.period_pace_label.text() == "4.68 pts/min"
    assert panel.half_points_title.text() == "PUNTOS 2H"
    assert panel.half_points_label.text() == "19 - 3   ·   22 pts"
    assert panel.half_pace_label.text() == "4.68 pts/min"
    assert panel.first_half_points_label.text() == "46 - 44   ·   90 pts"
    assert panel.first_half_pace_label.text() == "4.50 pts/min"
    assert panel.game_pace_label.text() == "4.53 pts/min"
    assert panel.baseline_button.isHidden(), \
        "el DOM completo no debe pedir marcador inicial manual"
    assert window.baseline_button.isHidden(), \
        "la barra superior tampoco debe pedir el marcador inicial"

    block = board.block_for(MarketKey.game())
    assert block is not None and block.table.rowCount() == 1
    assert block.table.item(0, COL_HALF).text() == \
        f"{view.focus.margin_vs_half_pace:+.2f}"
    window.deleteLater()
    qapp.processEvents()


def test_evento_nuevo_solo_con_mercado_limpia_parciales_y_metricas_anteriores(app):
    from visorunder.calculations.metrics import compute_general_metrics

    app.start_bridge()
    enviar(app, payload(gameState={
        "scoreA": 65, "scoreB": 47, "period": 3,
        "clockRaw": "24:42", "clockSemantics": "GAME_ELAPSED",
        "teamA": {"name": "Baréin", "total": 65,
                  "periods": {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0}},
        "teamB": {"name": "Arabia Saudí", "total": 47,
                  "periods": {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": 0}},
    }))
    reader = app.start_session(app.profile)
    reader.stop()
    assert reader.tick().state.current_period_score().total == 22

    # El primer paquete del evento nuevo puede traer solo mercado. Ni durante
    # ese intervalo se pueden conservar nombres, parciales o ritmos de Baréin.
    enviar(app, payload(
        event={"id": "nuevo-evento", "name": "Equipo C vs Equipo D"},
        visibleMarket={"marketType": "GAME_TOTAL", "period": None, "half": None,
                       "confidence": 0.95, "rawTitle": "Total del partido",
                       "sidesConfirmed": True},
        lines=[{"line": 151.5, "overOdds": 1.85, "underOdds": 1.90}],
        gameState=None,
    ))
    nuevo = reader.tick()
    general = compute_general_metrics(nuevo.state)

    assert nuevo.state.team_a.usable_value() is None
    assert nuevo.state.team_b.usable_value() is None
    assert nuevo.state.score_a_value is None and nuevo.state.score_b_value is None
    assert nuevo.state.tracker.dom_breakdown == {}
    assert general.total_points is None
    assert general.period_points is None
    assert general.half_points is None and general.half_pace is None
    assert general.first_half_points is None and general.first_half_pace is None
    assert nuevo.markets.get(MarketKey.game()).lines[0].line == 151.5


def test_lineas_suspendidas_no_detienen_scoreboard_ni_rejuvenecen_la_ultima_cuota(app):
    app.start_bridge()
    estado_89 = {
        "scoreA": 89, "scoreB": 66, "period": 4, "clock": "08:00",
        "teamA": {"name": "Alemania", "total": 89,
                  "periods": {"Q1": 24, "Q2": 26, "Q3": 36, "Q4": 3}},
        "teamB": {"name": "República Checa", "total": 66,
                  "periods": {"Q1": 21, "Q2": 28, "Q3": 17, "Q4": 0}},
    }
    enviar(app, payload(
        visibleMarket={"marketType": "GAME_TOTAL", "period": None, "half": None,
                       "confidence": 0.95,
                       "rawTitle": "Total de puntos - Prórroga incluida",
                       "sidesConfirmed": True},
        lines=[{"line": 195.5, "overOdds": 1.67, "underOdds": 2.00}],
        gameState=estado_89))

    lector = app.start_session(None)
    lector.stop()
    primero = lector.tick()
    assert primero.state.score_a_value == 89
    assert primero.markets.get(MarketKey.game()).freshness(
        app.freshness_criteria, primero.ts) is FreshnessState.LIVE

    estado_91 = {**estado_89, "scoreA": 91,
                 "teamA": {**estado_89["teamA"], "total": 91,
                           "periods": {**estado_89["teamA"]["periods"], "Q4": 5}}}
    enviar(app, payload(
        visibleMarket={"marketType": "GAME_TOTAL", "period": None, "half": None,
                       "confidence": 0.95,
                       "rawTitle": "Total de puntos - Prórroga incluida",
                       "sidesConfirmed": True},
        lines=[], gameState=estado_91))
    segundo = lector.tick()
    mercado = segundo.markets.get(MarketKey.game())

    assert segundo.state.score_a_value == 91
    assert [line.line for line in mercado.lines] == [195.5], "se conserva la ultima buena"
    assert mercado.freshness(app.freshness_criteria, segundo.ts) is FreshnessState.STALE
    assert segundo.field_sources["score_a"] == SourceKind.BROWSER_DOM.value
    assert "lines" not in segundo.field_sources, "la linea vieja no figura como actual"

    enviar(app, payload(
        visibleMarket={"marketType": "GAME_TOTAL", "period": None, "half": None,
                       "confidence": 0.95,
                       "rawTitle": "Total de puntos - Prórroga incluida",
                       "sidesConfirmed": True},
        lines=[{"line": 197.5, "overOdds": 2.06, "underOdds": 1.62}],
        gameState=None))
    tercero = lector.tick()
    mercado = tercero.markets.get(MarketKey.game())
    assert [line.line for line in mercado.lines] == [197.5]
    assert mercado.freshness(app.freshness_criteria, tercero.ts) is FreshnessState.LIVE
    assert tercero.state.score_a_value == 91, "el market update no borra el gameState"


def test_payload_multi_llega_hasta_el_radar_con_game_h2_y_q4_independientes(app):
    def entry(tipo, lineas, *, period=None, half=None, section=""):
        return {
            "marketType": tipo, "period": period, "half": half,
            "confidence": 0.95, "rawTitle": f"Total {tipo}",
            "sidesConfirmed": True,
            "observedAt": "2026-08-19T02:00:00.000Z",
            "section": section, "source": "CANONICAL_SECTION",
            "lines": [{"line": line, "overOdds": over, "underOdds": under}
                      for line, over, under in lineas],
        }

    app.start_bridge()
    enviar(app, payload(
        visibleMarket=None,
        lines=[],
        markets=[
            entry("GAME_TOTAL", [(182.5, 1.68, 1.98), (183.5, 1.86, 1.78),
                                  (184.5, 2.08, 1.61)], section="Partido"),
            entry("HALF_TOTAL", [(84.5, 1.91, 1.74)], half=2,
                  section="Second Half"),
            entry("QUARTER_TOTAL", [(38.5, 1.76, 1.88)], period=4,
                  section="4º cuarto"),
        ],
        gameState={"scoreA": 91, "scoreB": 66, "period": 4, "clock": "05:32"},
    ))
    lector = app.start_session(None)
    lector.stop()
    snapshot = lector.tick()

    assert [line.line for line in snapshot.markets.get(MarketKey.game()).lines] == [
        182.5, 183.5, 184.5]
    assert [line.line for line in snapshot.markets.get(MarketKey.half_market(2)).lines] == [84.5]
    assert [line.line for line in snapshot.markets.get(MarketKey.quarter(4)).lines] == [38.5]
    assert all(snapshot.markets.get(key).freshness(app.freshness_criteria, snapshot.ts)
               is FreshnessState.LIVE for key in (
                   MarketKey.game(), MarketKey.half_market(2), MarketKey.quarter(4)))
    assert snapshot.state.score_a_value == 91 and snapshot.state.clock_value == 332
