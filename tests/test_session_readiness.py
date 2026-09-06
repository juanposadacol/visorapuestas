"""Que hace falta para CREAR la sesion y que solo para EVALUAR una linea.

Dos comportamientos que el usuario pidio explicitamente:

1. Mensajes ESPECIFICOS. Si falta el reloj se dice "Esperando reloj", no
   "revisa el panel de diagnostico: falta el perfil, alguna region
   imprescindible o el motor OCR".

2. Un cambio de Q3 a Q4 con la casa todavia sin publicar lineas NO puede
   dejar la sesion inutilizada. Marcador, reloj y cuarto se siguen leyendo, y
   cuando aparecen las lineas del Q4 el radar las recoge solo.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visorunder.app import AppController, SessionState, StartBlocker
from visorunder.bridge.server import BRIDGE_HEADER, BridgeSettings
from visorunder.capture.roi import Rect, RoiKind
from visorunder.capture.screen_capture import NullCapture
from visorunder.config.profiles import SportsbookProfile
from visorunder.domain.market import MarketKey


GAME_STATE = {"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}


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


# ---------------------------------------------------------------------------
# Mensajes especificos
# ---------------------------------------------------------------------------
def test_sin_perfil_y_sin_extension_se_nombra_el_perfil(app):
    assert app.start_session(None) is None
    assert app.start_blockers == [StartBlocker.PROFILE]
    motivo = app.describe_start_blockers()
    assert "perfil" in motivo.lower()
    assert "revisa el panel de diagnostico" not in motivo.lower()


def test_falta_el_reloj_y_se_dice_reloj(app):
    """Perfil con marcador y cuarto, pero sin reloj."""
    perfil = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    perfil.set_roi(RoiKind.PERIOD, Rect(0, 0, 60, 30))
    perfil.set_roi(RoiKind.SCORE_PAIR, Rect(0, 40, 120, 30))

    assert app.start_session(perfil) is None
    assert app.start_blockers == [StartBlocker.CLOCK]
    assert app.describe_start_blockers() == "Esperando reloj."


def test_falta_el_marcador_y_se_dice_marcador(app):
    perfil = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    perfil.set_roi(RoiKind.CLOCK, Rect(0, 0, 60, 30))
    perfil.set_roi(RoiKind.PERIOD, Rect(0, 40, 60, 30))

    assert app.start_session(perfil) is None
    assert app.start_blockers == [StartBlocker.SCORE]
    assert app.describe_start_blockers() == "Esperando marcador."


def test_falta_el_cuarto_y_se_dice_cuarto(app):
    perfil = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    perfil.set_roi(RoiKind.CLOCK, Rect(0, 0, 60, 30))
    perfil.set_roi(RoiKind.SCORE_PAIR, Rect(0, 40, 120, 30))

    assert app.start_session(perfil) is None
    assert app.start_blockers == [StartBlocker.PERIOD]
    assert "periodo/cuarto" in app.describe_start_blockers().lower()


def test_faltan_varios_datos_y_se_nombran_todos(app):
    perfil = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    perfil.set_roi(RoiKind.CLOCK, Rect(0, 0, 60, 30))

    assert app.start_session(perfil) is None
    motivo = app.describe_start_blockers()
    assert "Esperando periodo/cuarto." in motivo
    assert "Esperando marcador." in motivo
    assert "Esperando reloj." not in motivo, "el reloj SI esta cubierto"


def test_cada_motivo_tiene_su_frase():
    """Ningun motivo puede quedarse sin mensaje propio."""
    for blocker in StartBlocker:
        assert blocker.message, f"{blocker} no tiene mensaje"
        assert blocker.short_label
    assert StartBlocker.MARKET.message == "Esperando lineas del mercado actual."
    assert StartBlocker.CLOCK.message == "Esperando reloj."
    assert StartBlocker.SCORE.message == "Esperando marcador."
    assert StartBlocker.PERIOD.message == "Esperando periodo/cuarto."
    assert "OCR" in StartBlocker.OCR.message
    assert "perfil" in StartBlocker.PROFILE.message.lower()


# ---------------------------------------------------------------------------
# Las lineas no son imprescindibles para CREAR la sesion
# ---------------------------------------------------------------------------
def test_las_lineas_no_bloquean_el_arranque(app):
    """Reloj, cuarto y marcador bastan: las lineas hacen falta despues."""
    perfil = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    perfil.set_roi(RoiKind.CLOCK, Rect(0, 0, 60, 30))
    perfil.set_roi(RoiKind.PERIOD, Rect(0, 40, 60, 30))
    perfil.set_roi(RoiKind.SCORE_PAIR, Rect(0, 80, 120, 30))

    # El mercado sigue apareciendo como "pendiente" en el diagnostico...
    assert "mercado y lineas" in app.missing_requirements(perfil)
    # ...pero no impide arrancar.
    assert app.blocking_requirements(perfil) == []
    assert app.start_blockers == []

    lector = app.start_session(perfil)
    assert lector is not None, "las lineas no pueden impedir crear la sesion"
    lector.stop()


def test_lo_que_falta_se_separa_de_lo_que_bloquea(app):
    """missing_requirements informa; blocking_requirements decide."""
    assert app.blocking_requirements(None) == [
        StartBlocker.CLOCK, StartBlocker.PERIOD, StartBlocker.SCORE]
    assert StartBlocker.MARKET not in app.blocking_requirements(None)
    assert "mercado y lineas" in app.missing_requirements(None)


def test_con_datos_del_partido_la_sesion_esta_lista_sin_lineas(app):
    """La extension manda el estado del partido pero ninguna linea."""
    app.start_bridge()
    enviar(app, payload(lines=[], gameState=GAME_STATE))

    assert app.browser.snapshot() is None, "sin lineas no hay oferta publicada"
    assert "mercado y lineas" in app.missing_requirements(None)
    # Aun asi la sesion puede empezar: hay reloj, cuarto y marcador.
    assert app.session_state is SessionState.READY
    lector = app.start_session(None)
    assert lector is not None
    lector.stop()


# ---------------------------------------------------------------------------
# Transicion Q3 -> Q4
# ---------------------------------------------------------------------------
def test_el_cambio_de_cuarto_sin_lineas_no_mata_la_sesion(app):
    """Q3 con lineas -> Q4 sin lineas todavia: la sesion sigue viva."""
    app.start_bridge()
    enviar(app, payload(
        visibleMarket={"marketType": "QUARTER_TOTAL", "period": 3, "half": None,
                       "confidence": 0.95, "rawTitle": "Total de puntos - Cuarto 3",
                       "sidesConfirmed": True},
        lines=[{"line": 40.5, "overOdds": 1.80, "underOdds": 1.95}],
        gameState={"scoreA": 58, "scoreB": 52, "period": 3, "clock": "00:30"}))

    lector = app.start_session(None)
    assert lector is not None
    lector.tick()
    assert lector.last_snapshot is not None

    # Termina el Q3 y empieza el Q4: se detecta el cuarto, no hay oferta.
    enviar(app, payload(
        visibleMarket={"marketType": "QUARTER_TOTAL", "period": 4, "half": None,
                       "confidence": 0.95, "rawTitle": "Total de puntos - Cuarto 4",
                       "sidesConfirmed": True},
        lines=[],
        gameState={"scoreA": 60, "scoreB": 54, "period": 4, "clock": "09:50"}))
    lector.tick()

    snapshot = lector.last_snapshot
    assert app.reader is lector, "la sesion no puede caerse por un hueco de lineas"
    assert app.session_state is SessionState.RUNNING
    # Y lo importante sigue llegando.
    assert snapshot.state.period_value == 4
    assert snapshot.state.clock_value == 9 * 60 + 50
    assert snapshot.state.total_points == 114
    lector.stop()


def test_cuando_aparecen_las_lineas_del_q4_el_radar_las_evalua(app):
    """Y cuando la casa publica el Q4, se anaden solas."""
    app.start_bridge()
    enviar(app, payload(lines=[], gameState={"scoreA": 60, "scoreB": 54,
                                             "period": 4, "clock": "09:50"}))
    lector = app.start_session(None)
    assert lector is not None
    lector.tick()

    vista = app.build_view_model(lector.last_snapshot)
    assert vista.blocks == [], "todavia no hay ninguna linea que evaluar"

    # La casa publica el Q4.
    enviar(app, payload(
        lines=[{"line": 42.5, "overOdds": 1.85, "underOdds": 1.90}],
        gameState={"scoreA": 62, "scoreB": 55, "period": 4, "clock": "09:10"}))
    lector.tick()

    vista = app.build_view_model(lector.last_snapshot)
    bloques = {b.key: b for b in vista.blocks}
    assert MarketKey.quarter(4) in bloques, "las lineas nuevas deben entrar solas"
    evaluaciones = bloques[MarketKey.quarter(4)].evaluations
    assert [e.line_value for e in evaluaciones] == [42.5]
    assert evaluaciones[0].under_odds == 1.90

    # La sesion empezo con el Q4 ya en marcha, asi que todavia no se sabe con
    # que marcador empezo ese cuarto. La linea entra al radar igualmente, pero
    # se declara NO EVALUABLE con su motivo en vez de inventar los puntos.
    assert evaluaciones[0].points_to_exceed is None
    assert evaluaciones[0].unavailable_reason == "FALTA MARCADOR INICIAL Q4"

    # En cuanto se conoce ese marcador inicial, la misma linea si se evalua.
    app.set_period_baseline(4, 58, 52)
    lector.tick()
    vista = app.build_view_model(lector.last_snapshot)
    bloques = {b.key: b for b in vista.blocks}
    evaluacion = bloques[MarketKey.quarter(4)].evaluations[0]
    assert evaluacion.scope_points == 7          # (62-58) + (55-52)
    assert evaluacion.points_to_exceed == 36     # floor(42.5) + 1 - 7
    assert evaluacion.unavailable_reason == ""
    lector.stop()


def test_una_metrica_sin_linea_no_se_inventa(app):
    """Sin lineas no hay evaluaciones, pero tampoco numeros falsos."""
    app.start_bridge()
    enviar(app, payload(lines=[], gameState=GAME_STATE))
    lector = app.start_session(None)
    lector.tick()

    vista = app.build_view_model(lector.last_snapshot)
    assert vista.blocks == []
    assert vista.focus is None
    assert vista.evaluations == []
    # El estado del partido si esta disponible.
    assert vista.general is not None
    assert vista.general.total_points == 110
    lector.stop()
