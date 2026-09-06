"""De extremo a extremo: la apuesta manual se sigue sola con el partido.

El usuario introduce la apuesta UNA vez. A partir de ahi cada ReaderSnapshot
que llega por el Browser Bridge actualiza su seguimiento sin que haya que
tocar nada, y la ventana principal lo pinta en la tabla.

Es el requisito central: una apuesta manual recibe el MISMO seguimiento
matematico en vivo que una apuesta fijada desde el radar.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.app import AppController  # noqa: E402
from visorunder.bridge.server import BRIDGE_HEADER, BridgeSettings  # noqa: E402
from visorunder.calculations.manual_tracking import TrackingStatus  # noqa: E402
from visorunder.capture.screen_capture import NullCapture  # noqa: E402
from visorunder.domain.market import MarketKey, Side  # noqa: E402
from visorunder.ui.main_window import MainWindow  # noqa: E402
from visorunder.ui.manual_bets_panel import COLUMNS  # noqa: E402


def _column(name: str) -> int:
    return [n for n, _ in COLUMNS].index(name)


def payload(score_a: int, score_b: int, clock: str, period: int = 4, lines=None):
    return {
        "protocol": 1, "source": "betplay",
        "observedAt": "2026-08-19T02:00:00.000Z",
        "event": {"id": "9876543", "name": "Equipo A vs Equipo B"},
        "visibleMarket": {"marketType": "QUARTER_TOTAL", "period": period, "half": None,
                          "confidence": 0.95,
                          "rawTitle": f"Total de puntos - Cuarto {period}",
                          "sidesConfirmed": True},
        "lines": [{"line": 44.5, "overOdds": 1.75, "underOdds": 1.90}]
        if lines is None else lines,
        "gameState": {"scoreA": score_a, "scoreB": score_b,
                      "period": period, "clock": clock},
    }


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def app(tmp_path):
    controlador = AppController(db_path=str(tmp_path / "live.db"), capture=NullCapture())
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


# ---------------------------------------------------------------------------
# 14. Cada ReaderSnapshot actualiza la apuesta manual
# ---------------------------------------------------------------------------
def test_cada_snapshot_actualiza_la_apuesta_manual(app):
    """32 -> 34 -> 36 -> 39 llegando por el puente, sin tocar la apuesta."""
    app.start_bridge()
    enviar(app, payload(score_a=72, score_b=60, clock="10:00"))
    lector = app.start_session(None)
    assert lector is not None
    lector.tick()
    app.set_period_baseline(4, 72, 60)      # el Q4 empieza 72-60

    app.add_manual_bet(sportsbook="Stake", event="Equipo A vs Equipo B",
                       key=MarketKey.quarter(4), side=Side.UNDER,
                       line=40.5, odds=1.80, stake=0.0)

    observado = []
    for puntos, reloj in [(32, "05:00"), (34, "04:00"), (36, "03:00"), (39, "02:00")]:
        enviar(app, payload(score_a=72 + puntos, score_b=60, clock=reloj))
        lector.tick()
        vista = app.build_view_model(lector.last_snapshot)
        seguimiento = vista.manual_tracking[0]
        observado.append((seguimiento.scope_points,
                          seguimiento.margin,
                          seguimiento.points_to_cross,
                          seguimiento.tolerable_points))

    assert observado == [
        (32, 8.5, 9, 8),
        (34, 6.5, 7, 6),
        (36, 4.5, 5, 4),
        (39, 1.5, 2, 1),
    ]
    lector.stop()


def test_cuando_la_linea_queda_superada_el_estado_lo_dice(app):
    app.start_bridge()
    enviar(app, payload(score_a=72, score_b=60, clock="10:00"))
    lector = app.start_session(None)
    lector.tick()
    app.set_period_baseline(4, 72, 60)

    app.add_manual_bet(sportsbook="Stake", event="", key=MarketKey.quarter(4),
                       side=Side.UNDER, line=40.5, odds=1.80, stake=0.0)

    enviar(app, payload(score_a=95, score_b=78, clock="02:00"))   # 23 + 18 = 41
    lector.tick()
    seguimiento = app.build_view_model(lector.last_snapshot).manual_tracking[0]

    assert seguimiento.scope_points == 41
    assert seguimiento.exceeded is True
    assert seguimiento.status is TrackingStatus.EXCEEDED
    assert seguimiento.points_to_cross == 0
    assert seguimiento.margin == pytest.approx(-0.5)
    lector.stop()


def test_tres_apuestas_se_siguen_a_la_vez_desde_el_mismo_partido(app):
    """Dos casas y dos mercados distintos, un solo partido en vivo."""
    app.start_bridge()
    enviar(app, payload(score_a=72, score_b=60, clock="10:00"))
    lector = app.start_session(None)
    lector.tick()
    app.set_period_baseline(4, 72, 60)

    app.add_manual_bet(sportsbook="BetPlay", event="", key=MarketKey.quarter(4),
                       side=Side.UNDER, line=40.5, odds=1.80, stake=0.0)
    app.add_manual_bet(sportsbook="Stake", event="", key=MarketKey.quarter(4),
                       side=Side.UNDER, line=42.5, odds=1.75, stake=0.0)
    app.add_manual_bet(sportsbook="BetPlay", event="", key=MarketKey.game(),
                       side=Side.UNDER, line=185.5, odds=1.90, stake=0.0)

    enviar(app, payload(score_a=90, score_b=74, clock="05:00"))
    lector.tick()
    seguimientos = {(t.sportsbook, t.line): t
                    for t in app.build_view_model(lector.last_snapshot).manual_tracking}

    # El Q4 lleva 32 puntos; el partido, 164.
    assert seguimientos[("BetPlay", 40.5)].scope_points == 32
    assert seguimientos[("Stake", 42.5)].scope_points == 32
    assert seguimientos[("BetPlay", 185.5)].scope_points == 164

    # Y cada linea con su propio margen, sin mezclarse.
    assert seguimientos[("BetPlay", 40.5)].margin == pytest.approx(8.5)
    assert seguimientos[("Stake", 42.5)].margin == pytest.approx(10.5)
    assert seguimientos[("BetPlay", 185.5)].margin == pytest.approx(21.5)
    assert seguimientos[("BetPlay", 40.5)].points_to_cross == 9
    assert seguimientos[("Stake", 42.5)].points_to_cross == 11
    assert seguimientos[("BetPlay", 185.5)].points_to_cross == 22
    lector.stop()


def test_una_apuesta_manual_y_una_fijada_dan_el_mismo_calculo(app):
    """El seguimiento manual NO es una segunda matematica."""
    app.start_bridge()
    enviar(app, payload(score_a=72, score_b=60, clock="10:00"))
    lector = app.start_session(None)
    lector.tick()
    app.set_period_baseline(4, 72, 60)

    enviar(app, payload(score_a=90, score_b=74, clock="05:00"))
    lector.tick()

    # Se fija la linea 44.5 del radar...
    vista = app.build_view_model(lector.last_snapshot)
    assert vista.focus is not None
    fijada = app.lock_bet()
    assert fijada is not None

    # ...y se registra la MISMA linea como apuesta manual.
    app.add_manual_bet(sportsbook="BetPlay", event="", key=fijada.key,
                       side=Side.UNDER, line=fijada.line, odds=1.90, stake=0.0)

    lector.tick()
    vista = app.build_view_model(lector.last_snapshot)
    manual = vista.manual_tracking[0]
    radar = vista.bet_tracking

    assert manual.scope_points == radar.scope_points
    assert manual.points_to_cross == radar.points_to_exceed
    assert manual.exceed_threshold == radar.exceed_threshold
    assert manual.current_pace == pytest.approx(radar.current_pace)
    assert manual.required_pace == pytest.approx(radar.required_pace)
    lector.stop()


# ---------------------------------------------------------------------------
# La ventana principal lo pinta sola
# ---------------------------------------------------------------------------
def test_la_ventana_refresca_la_tabla_de_apuestas_manuales(qapp, app):
    app.start_bridge()
    enviar(app, payload(score_a=72, score_b=60, clock="10:00"))

    ventana = MainWindow(app)
    ventana.timer.stop()          # los ciclos se disparan a mano en la prueba
    try:
        lector = app.start_session(None)
        assert lector is not None
        lector.tick()
        app.set_period_baseline(4, 72, 60)

        app.add_manual_bet(sportsbook="Stake", event="", key=MarketKey.quarter(4),
                           side=Side.UNDER, line=40.5, odds=1.80, stake=0.0)
        ventana.manual_bets_panel.refresh()

        enviar(app, payload(score_a=90, score_b=74, clock="05:00"))
        lector.tick()
        ventana._refresh()

        tabla = ventana.manual_bets_panel.table
        assert tabla.rowCount() == 1
        assert tabla.item(0, _column("CASA")).text() == "Stake"
        assert tabla.item(0, _column("ACTUAL")).text() == "32"
        assert tabla.item(0, _column("MARGEN")).text() == "+8.5"
        assert tabla.item(0, _column("P/CRUZAR")).text() == "9"
        assert tabla.item(0, _column("SEGUIMIENTO")).text() in ("EN RIESGO", "FAVORABLE")

        # Y con el marcador siguiente la tabla cambia sola.
        enviar(app, payload(score_a=93, score_b=75, clock="04:00"))   # 21+15 = 36
        lector.tick()
        ventana._refresh()
        assert tabla.item(0, _column("ACTUAL")).text() == "36"
        assert tabla.item(0, _column("MARGEN")).text() == "+4.5"
        assert tabla.item(0, _column("P/CRUZAR")).text() == "5"
        lector.stop()
    finally:
        # Cerrar la ventana llama a controller.shutdown(); de eso ya se encarga
        # la fixture, asi que aqui solo se sueltan los recursos de la interfaz.
        ventana.hotkeys.stop()
        ventana.setParent(None)


def test_la_seleccion_del_usuario_sobrevive_al_refresco(qapp, app):
    """Refrescar el seguimiento no puede robar la fila seleccionada."""
    app.start_bridge()
    enviar(app, payload(score_a=72, score_b=60, clock="10:00"))
    lector = app.start_session(None)
    lector.tick()
    app.set_period_baseline(4, 72, 60)

    app.add_manual_bet(sportsbook="BetPlay", event="", key=MarketKey.quarter(4),
                       side=Side.UNDER, line=40.5, odds=1.80, stake=0.0)
    app.add_manual_bet(sportsbook="Stake", event="", key=MarketKey.quarter(4),
                       side=Side.UNDER, line=42.5, odds=1.75, stake=0.0)

    from visorunder.ui.manual_bets_panel import ManualBetsPanel

    panel = ManualBetsPanel(app)
    panel.table.selectRow(1)
    elegida = panel._selected_bet_id()

    enviar(app, payload(score_a=90, score_b=74, clock="05:00"))
    lector.tick()
    panel.update_tracking(app.build_view_model(lector.last_snapshot).manual_tracking)

    assert panel._selected_bet_id() == elegida, "el refresco movio la seleccion"
    assert panel.table.item(1, _column("ACTUAL")).text() == "32"
    lector.stop()
