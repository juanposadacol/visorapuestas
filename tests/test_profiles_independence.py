"""Perfiles independientes: BetPlay por DOM y Stake por OCR, sin pisarse.

Lo que se fija aqui:

* crear un perfil de Stake NO toca el de BetPlay;
* dos perfiles con nombres distintos conviven y persisten;
* renombrar conserva la identidad (el id), no crea un duplicado;
* dos perfiles no pueden acabar con el mismo nombre por accidente;
* el Browser Bridge de BetPlay sigue funcionando igual;
* un perfil de Stake por OCR funciona SIN extension de Stake, que es el
  estado real: todavia no existe un parser DOM para Stake.
"""

from __future__ import annotations

import json
import os
import urllib.request

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visorunder.app import AppController
from visorunder.bridge.server import BRIDGE_HEADER, BridgeSettings
from visorunder.bridge.source import LinkState
from visorunder.capture.roi import Rect, RoiKind
from visorunder.capture.screen_capture import NullCapture
from visorunder.config.profiles import SportsbookProfile
from visorunder.domain.market import MarketKey


@pytest.fixture()
def app(tmp_path):
    controlador = AppController(db_path=str(tmp_path / "perfiles.db"),
                                capture=NullCapture())
    controlador.settings.log_to_file = False
    controlador.settings.bridge = BridgeSettings(port=0)
    controlador.bridge.settings = controlador.settings.bridge
    yield controlador
    controlador.shutdown()


def _ocr_profile(name: str, sportsbook: str) -> SportsbookProfile:
    """Perfil completo de OCR: las cuatro regiones imprescindibles."""
    perfil = SportsbookProfile(name=name, sportsbook=sportsbook)
    perfil.set_roi(RoiKind.CLOCK, Rect(10, 10, 80, 30))
    perfil.set_roi(RoiKind.PERIOD, Rect(10, 50, 80, 30))
    perfil.set_roi(RoiKind.SCORE_PAIR, Rect(10, 90, 160, 30))
    perfil.set_roi(RoiKind.MARKET_BLOCK, Rect(400, 200, 320, 240))
    return perfil


# ---------------------------------------------------------------------------
# 4 / 5 / 6. Independencia entre perfiles
# ---------------------------------------------------------------------------
def test_crear_stake_no_toca_betplay(app):
    betplay = _ocr_profile("JUAN", "BetPlay")
    id_betplay = app.save_profile(betplay)

    stake = _ocr_profile("Stake principal", "Stake")
    id_stake = app.save_profile(stake)

    assert id_betplay != id_stake, "cada perfil tiene su propia identidad"

    guardado = app.load_profile("JUAN")
    assert guardado is not None
    assert guardado.sportsbook == "BetPlay", "crear Stake sobrescribio BetPlay"
    assert guardado.profile_id == id_betplay
    assert sorted(app.profile_names()) == ["JUAN", "Stake principal"]


def test_dos_perfiles_con_nombres_distintos_persisten(app, tmp_path):
    app.save_profile(_ocr_profile("JUAN", "BetPlay"))
    app.save_profile(_ocr_profile("Stake principal", "Stake"))
    app.save_profile(_ocr_profile("otra casa", "Betano"))
    ruta = app.db.path
    app.shutdown()

    # Se vuelve a abrir la aplicacion sobre la MISMA base.
    otro = AppController(db_path=ruta, capture=NullCapture())
    otro.settings.log_to_file = False
    try:
        assert sorted(otro.profile_names()) == ["JUAN", "Stake principal", "otra casa"]
        assert otro.load_profile("JUAN").sportsbook == "BetPlay"
        assert otro.load_profile("Stake principal").sportsbook == "Stake"
        assert otro.load_profile("otra casa").sportsbook == "Betano"
        # Y cada uno conserva SUS regiones.
        for nombre in ("JUAN", "Stake principal", "otra casa"):
            perfil = otro.load_profile(nombre)
            assert perfil.missing_required() == [], f"{nombre} perdio regiones"
    finally:
        otro.db.close()


def test_cambiar_el_sportsbook_de_un_perfil_no_afecta_al_otro(app):
    app.save_profile(_ocr_profile("JUAN", "BetPlay"))
    stake = _ocr_profile("Stake principal", "Stake")
    app.save_profile(stake)

    stake.sportsbook = "Stake.com"
    app.save_profile(stake)

    assert app.load_profile("Stake principal").sportsbook == "Stake.com"
    assert app.load_profile("JUAN").sportsbook == "BetPlay"


def test_renombrar_conserva_la_identidad(app):
    perfil = _ocr_profile("Stake principal", "Stake")
    profile_id = app.save_profile(perfil)

    perfil.name = "Stake cuenta 2"
    assert app.save_profile(perfil) == profile_id, "renombrar creo otro perfil"

    assert app.load_profile("Stake principal") is None
    renombrado = app.load_profile("Stake cuenta 2")
    assert renombrado is not None
    assert renombrado.profile_id == profile_id
    assert renombrado.sportsbook == "Stake"
    assert renombrado.missing_required() == [], "renombrar perdio las regiones"
    assert app.profile_names() == ["Stake cuenta 2"]


def test_no_se_permiten_nombres_duplicados(app):
    app.save_profile(_ocr_profile("Stake principal", "Stake"))

    duplicado = _ocr_profile("Stake principal", "Otra")
    with pytest.raises(ValueError, match="Ya existe"):
        app.save_profile(duplicado)

    # El original sigue intacto.
    assert app.load_profile("Stake principal").sportsbook == "Stake"
    assert app.profile_names() == ["Stake principal"]


def test_renombrar_al_nombre_de_otro_perfil_se_rechaza(app):
    app.save_profile(_ocr_profile("JUAN", "BetPlay"))
    stake = _ocr_profile("Stake principal", "Stake")
    app.save_profile(stake)

    stake.name = "JUAN"
    with pytest.raises(ValueError, match="Ya existe"):
        app.save_profile(stake)

    assert app.load_profile("JUAN").sportsbook == "BetPlay"
    assert sorted(app.profile_names()) == ["JUAN", "Stake principal"]


def test_profile_exists_distingue_el_perfil_que_se_edita(app):
    perfil = _ocr_profile("Stake principal", "Stake")
    profile_id = app.save_profile(perfil)

    assert app.profile_exists("Stake principal") is True
    # Pero no cuenta como duplicado cuando es EL MISMO perfil.
    assert app.profile_exists("Stake principal", exclude_profile_id=profile_id) is False


# ---------------------------------------------------------------------------
# 16. El Browser Bridge de BetPlay sigue funcionando
# ---------------------------------------------------------------------------
def _enviar(controlador, cuerpo):
    peticion = urllib.request.Request(
        f"{controlador.bridge.url}/v1/browser-state",
        data=json.dumps(cuerpo).encode("utf-8"), method="POST")
    peticion.add_header("Content-Type", "application/json")
    peticion.add_header(BRIDGE_HEADER, "1")
    peticion.add_header("Origin", "chrome-extension://abcdefghijklmnopabcdefghijklmnop")
    with urllib.request.urlopen(peticion, timeout=5) as respuesta:
        return respuesta.status


BETPLAY_PAYLOAD = {
    "protocol": 1, "source": "betplay",
    "observedAt": "2026-08-19T02:00:00.000Z",
    "event": {"id": "9876543", "name": "Equipo A vs Equipo B"},
    "visibleMarket": {"marketType": "QUARTER_TOTAL", "period": 4, "half": None,
                      "confidence": 0.95, "rawTitle": "Total de puntos - Cuarto 4",
                      "sidesConfirmed": True},
    "lines": [{"line": 44.5, "overOdds": 1.75, "underOdds": 1.90}],
    "gameState": {"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"},
}


def test_el_browser_bridge_de_betplay_sigue_funcionando(app):
    """El DOM de BetPlay no se toca: sigue arrancando sin dibujar regiones."""
    assert app.start_bridge()
    assert _enviar(app, BETPLAY_PAYLOAD) == 200

    assert app.link_state is LinkState.LIVE
    assert app.browser.snapshot().key == MarketKey.quarter(4)
    assert app.browser.snapshot().lines[0].under_odds == 1.90
    assert set(app.dom_fields()) == {"market", "lines", "score_a", "score_b",
                                     "period", "clock_seconds"}
    assert app.missing_requirements(None) == []

    lector = app.start_session(None)      # sin perfil y sin regiones
    assert lector is not None
    lector.tick()
    estado = lector.last_snapshot.state
    assert estado.total_points == 110
    assert estado.period_value == 4
    assert estado.clock_value == 6 * 60 + 24
    lector.stop()


def test_tener_un_perfil_de_stake_no_estorba_al_bridge(app):
    """Guardar perfiles de otras casas no afecta al DOM de BetPlay."""
    app.save_profile(_ocr_profile("Stake principal", "Stake"))
    app.save_profile(_ocr_profile("otra casa", "Betano"))

    assert app.start_bridge()
    assert _enviar(app, BETPLAY_PAYLOAD) == 200
    assert app.link_state is LinkState.LIVE
    assert app.browser.snapshot().lines[0].under_odds == 1.90

    lector = app.start_session(None)
    assert lector is not None
    lector.tick()
    assert lector.last_snapshot.state.total_points == 110
    lector.stop()


# ---------------------------------------------------------------------------
# 17. Stake funciona por OCR, SIN extension de Stake
# ---------------------------------------------------------------------------
def test_el_perfil_de_stake_funciona_por_ocr_sin_extension(app):
    """No hay parser DOM de Stake, y no se finge que lo haya."""
    perfil = _ocr_profile("Stake principal", "Stake")
    app.save_profile(perfil)

    # Sin extension conectada: el DOM no aporta nada.
    assert app.dom_fields() == []
    assert app.link_state is LinkState.DISCONNECTED

    # Y aun asi el perfil de Stake esta completo por sus propias regiones.
    assert perfil.missing_required() == []
    assert app.missing_requirements(perfil) == []
    assert app.blocking_requirements(perfil) == []

    lector = app.start_session(perfil)
    assert lector is not None, "Stake debe poder leerse por OCR sin extension"
    assert lector.roi_manager.profile.sportsbook == "Stake"
    lector.stop()


def test_la_extension_solo_declara_betplay():
    """El manifiesto no puede prometer Stake sin un parser real."""
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parent.parent
    manifiesto = json.loads((raiz / "browser-extension" / "manifest.json").read_text())

    dominios = json.dumps(manifiesto)
    assert "betplay" in dominios.lower(), "el manifiesto debe seguir cubriendo BetPlay"
    assert "stake.com" not in dominios.lower(), (
        "no se anuncia soporte de Stake mientras no exista su parser")


def test_stake_por_ocr_y_betplay_por_dom_conviven(app):
    """Los dos caminos a la vez: cada perfil con su fuente."""
    stake = _ocr_profile("Stake principal", "Stake")
    app.save_profile(stake)

    app.start_bridge()
    _enviar(app, BETPLAY_PAYLOAD)

    # BetPlay entra por DOM sin necesitar regiones.
    assert app.missing_requirements(None) == []
    # Stake sigue siendo un perfil OCR completo y aparte.
    assert app.load_profile("Stake principal").missing_required() == []
    assert app.load_profile("Stake principal").sportsbook == "Stake"
    # Y el DOM de BetPlay no ha cambiado el perfil de Stake.
    assert app.load_profile("Stake principal").rois.keys() == stake.rois.keys()
