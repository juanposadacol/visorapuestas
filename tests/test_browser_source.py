"""Conversion del payload del navegador y estado de la fuente DOM."""

from __future__ import annotations

import pytest

from visorunder.bridge import converter
from visorunder.bridge.source import (BrowserSource, BrowserSourceSettings, ExtensionState,
                                      LinkState, SourceKind)
from visorunder.domain.market import MarketKey, MarketType


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


# ----------------------------------------------------------------- conversion
def test_el_payload_se_convierte_a_los_objetos_del_dominio():
    snapshot = converter.payload_to_snapshot(payload())
    assert snapshot.key == MarketKey.quarter(4)
    assert len(snapshot.lines) == 1
    linea = snapshot.lines[0]
    assert (linea.line, linea.over_odds, linea.under_odds) == (44.5, 1.75, 1.90)
    assert linea.confirmed is True          # ya paso dos validaciones
    assert linea.key == snapshot.key        # la linea va atada a su mercado


def test_los_tres_tipos_de_mercado():
    assert converter.payload_to_market_key(payload()).market_type is MarketType.QUARTER_TOTAL
    juego = payload(visibleMarket={"marketType": "GAME_TOTAL", "period": None, "half": None,
                                   "confidence": 0.95, "rawTitle": "", "sidesConfirmed": True})
    assert converter.payload_to_market_key(juego) == MarketKey.game()
    mitad = payload(visibleMarket={"marketType": "HALF_TOTAL", "period": None, "half": 2,
                                   "confidence": 0.95, "rawTitle": "", "sidesConfirmed": True})
    assert converter.payload_to_market_key(mitad) == MarketKey.half_market(2)


def test_un_mercado_no_soportado_lanza():
    malo = payload()
    malo["visibleMarket"]["marketType"] = "OTRA_COSA"
    with pytest.raises(ValueError):
        converter.payload_to_market_key(malo)


def test_el_reloj_llega_convertido_a_segundos():
    estado = converter.payload_to_game_state(
        payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}))
    assert estado == {"score_a": 58, "score_b": 52, "period": 4, "clock_seconds": 384}


def test_sin_gameState_no_se_inventa_nada():
    assert converter.payload_to_game_state(payload()) == {}
    assert converter.payload_to_game_state(payload(gameState={})) == {}


def test_gameState_parcial_solo_aporta_lo_que_trae():
    estado = converter.payload_to_game_state(payload(gameState={"scoreA": 58, "scoreB": 52}))
    assert estado == {"score_a": 58, "score_b": 52}
    assert "clock_seconds" not in estado


def test_una_hora_invalida_no_rompe_la_conversion():
    snapshot = converter.payload_to_snapshot(payload(observedAt="no es una fecha"))
    assert snapshot.timestamp > 0


# --------------------------------------------------------------------- fuente
def test_sin_paquetes_la_fuente_esta_desconectada():
    fuente = BrowserSource()
    assert fuente.link_state() is LinkState.DISCONNECTED
    assert fuente.snapshot() is None
    assert fuente.available_fields() == []


def test_ciclo_de_vida_del_enlace():
    fuente = BrowserSource(BrowserSourceSettings(live_within_seconds=3,
                                                 disconnected_after_seconds=12))
    fuente.accept(payload(), now=1000.0)
    assert fuente.link_state(1001.0) is LinkState.LIVE
    assert fuente.link_state(1005.0) is LinkState.STALE
    assert fuente.link_state(1030.0) is LinkState.DISCONNECTED


def test_un_enlace_desconectado_deja_de_ofrecer_datos():
    fuente = BrowserSource()
    fuente.accept(payload(), now=1000.0)
    assert fuente.snapshot(1001.0) is not None
    assert fuente.snapshot(1030.0) is None          # no se muestra lo viejo como actual
    # pero se conserva para poder decir ULTIMA LINEA OBSERVADA
    assert fuente.last_snapshot_any_age() is not None


def test_los_campos_disponibles_reflejan_lo_que_trae_el_DOM():
    fuente = BrowserSource()
    fuente.accept(payload(), now=1000.0)
    assert fuente.available_fields(1000.5) == ["market", "lines"]

    fuente.accept(payload(gameState={"scoreA": 58, "scoreB": 52, "period": 4, "clock": "06:24"}),
                  now=1001.0)
    campos = fuente.available_fields(1001.5)
    assert set(campos) == {"market", "lines", "score_a", "score_b", "period", "clock_seconds"}


def test_cambiar_de_partido_se_detecta_y_no_mezcla_mercados():
    fuente = BrowserSource()
    fuente.accept(payload(), now=1000.0)
    assert fuente.event_id == "9876543"

    otro = payload(event={"id": "1111111", "name": "Equipo C vs Equipo D"})
    fuente.accept(otro, now=1001.0)

    cambio = fuente.clear_event_change()
    assert cambio is not None
    assert cambio["from"] == "9876543"
    assert cambio["to"] == "1111111"
    assert fuente.event_id == "1111111"
    # y el aviso se consume una sola vez
    assert fuente.clear_event_change() is None


def test_el_mismo_partido_no_dispara_cambio_de_evento():
    fuente = BrowserSource()
    fuente.accept(payload(), now=1000.0)
    fuente.accept(payload(), now=1001.0)
    assert fuente.clear_event_change() is None
    assert fuente.packets == 2


def test_se_mide_la_latencia_de_cada_paquete():
    fuente = BrowserSource()
    paquete = fuente.accept(payload(), now=1000.0)
    assert paquete.latency_ms >= 0
    assert fuente.latency_ms() is not None


def test_la_latencia_nunca_sale_negativa_por_relojes_desalineados():
    fuente = BrowserSource()
    # observedAt en el futuro respecto al reloj de la app
    futuro = payload(observedAt="2099-01-01T00:00:00.000Z")
    paquete = fuente.accept(futuro, now=1000.0)
    assert paquete.latency_ms == 0.0


def test_un_payload_no_convertible_no_rompe_la_fuente():
    fuente = BrowserSource()
    malo = payload()
    malo["visibleMarket"]["marketType"] = "OTRA_COSA"
    fuente.accept(malo, now=1000.0)
    assert fuente.last_error
    assert fuente.snapshot(1000.5) is None
    # y sigue aceptando los buenos
    fuente.accept(payload(), now=1001.0)
    assert fuente.snapshot(1001.5) is not None
    assert not fuente.last_error


def test_reset_deja_la_fuente_como_nueva():
    fuente = BrowserSource()
    fuente.accept(payload(), now=1000.0)
    fuente.reset()
    assert fuente.link_state(1000.5) is LinkState.DISCONNECTED
    assert fuente.event_id is None


def test_las_etiquetas_son_legibles():
    assert LinkState.LIVE.label == "BETPLAY CONECTADO"
    assert LinkState.STALE.label == "DATOS DOM DESACTUALIZADOS"
    # LinkState habla de los DATOS; ExtensionState, de la extension. Que no
    # haya datos NO es que la extension este caida.
    assert LinkState.DISCONNECTED.label == "SIN DATOS DEL DOM"
    assert ExtensionState.CONNECTED.label == "EXTENSION CONECTADA"
    assert ExtensionState.STALE.label == "EXTENSION SIN CONFIRMAR"
    assert ExtensionState.DISCONNECTED.label == "EXTENSION DESCONECTADA"
    assert SourceKind.BROWSER_DOM.label == "DOM"


# --------------------------------- extension conectada frente a datos disponibles
#
# El fallo real: `Invoke-RestMethod http://127.0.0.1:8765/health` respondia
# `status: ok` y el panel decia EXTENSION DESCONECTADA, porque solo se sabia de
# la extension cuando llegaba un mercado. Son dos ejes distintos.

def test_la_extension_puede_estar_conectada_sin_haber_mandado_ningun_mercado():
    fuente = BrowserSource()
    assert fuente.extension_state() is ExtensionState.DISCONNECTED

    fuente.note_contact(now=1000.0)

    assert fuente.extension_state(now=1000.5) is ExtensionState.CONNECTED
    assert fuente.link_state(now=1000.5) is LinkState.DISCONNECTED
    assert fuente.snapshot(now=1000.5) is None
    assert "EXTENSION CONECTADA" in fuente.describe(now=1000.5)
    assert "sin mercado" in fuente.describe(now=1000.5)


def test_sin_latidos_la_extension_se_da_por_caida():
    fuente = BrowserSource(BrowserSourceSettings(
        extension_alive_within_seconds=10.0, extension_lost_after_seconds=20.0))
    fuente.note_contact(now=1000.0)
    assert fuente.extension_state(now=1005.0) is ExtensionState.CONNECTED
    assert fuente.extension_state(now=1015.0) is ExtensionState.STALE
    assert fuente.extension_state(now=1030.0) is ExtensionState.DISCONNECTED


def test_un_mercado_tambien_cuenta_como_senal_de_vida():
    fuente = BrowserSource()
    fuente.accept(payload(), now=2000.0)
    # Nunca se llamo a note_contact, pero es evidente que la extension esta.
    assert fuente.extension_state(now=2001.0) is ExtensionState.CONNECTED


def test_reiniciar_la_sesion_no_desconecta_la_extension():
    fuente = BrowserSource()
    fuente.note_contact(now=3000.0)
    fuente.accept(payload(), now=3000.0)
    fuente.reset()
    assert fuente.extension_state(now=3001.0) is ExtensionState.CONNECTED
    assert fuente.snapshot(now=3001.0) is None


def test_un_gameState_parcial_se_acepta_tal_cual():
    fuente = BrowserSource()
    fuente.accept(payload(gameState={"period": 4, "clock": "06:24"}), now=4000.0)
    estado = fuente.game_state(now=4000.5)
    assert estado["period"] == 4
    assert estado["clock_seconds"] == 6 * 60 + 24
    # Lo que el DOM no sabe, no se inventa.
    assert "score_a" not in estado
    assert "score_b" not in estado
    assert fuente.snapshot(now=4000.5) is not None, "el mercado llega igual"


def test_sin_gameState_el_mercado_llega_igual():
    fuente = BrowserSource()
    fuente.accept(payload(gameState=None), now=5000.0)
    assert fuente.game_state(now=5000.5) == {}
    snapshot = fuente.snapshot(now=5000.5)
    assert snapshot is not None
    assert snapshot.lines[0].under_odds == 1.90
    assert fuente.available_fields(now=5000.5) == ["market", "lines"]


# ------------------------------- el reloj que NO es el restante de un cuarto
#
# BetPlay (Kambi) muestra "Q4 - 33:52": tiempo JUGADO del partido, no restante
# del cuarto. La extension lo manda crudo con su semantica y la conversion la
# hace quien conoce las reglas de la competicion.

def test_el_reloj_acumulado_viaja_crudo_con_su_semantica():
    fuente = BrowserSource()
    fuente.accept(payload(gameState={
        "scoreA": 76, "scoreB": 69, "period": 4,
        "clockRaw": "33:52", "clockSemantics": "GAME_ELAPSED",
        "teamA": "Dallas Wings (F)", "teamB": "Indiana Fever (F)",
    }), now=6000.0)

    estado = fuente.game_state(now=6000.5)
    assert estado["clock_raw_seconds"] == 33 * 60 + 52
    assert estado["clock_semantics"] == "GAME_ELAPSED"
    # NO se publica como restante: eso seria un dato matematicamente incorrecto.
    assert "clock_seconds" not in estado
    assert estado["score_a"] == 76 and estado["score_b"] == 69
    assert estado["team_a"] == "Dallas Wings (F)"


def test_el_scoreboard_anidado_llega_con_nombres_y_parciales_sin_derivados():
    fuente = BrowserSource()
    fuente.accept(payload(gameState={
        "scoreA": 65, "scoreB": 47, "period": 3,
        "teamA": {"name": "Baréin", "total": 65,
                  "periods": {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0}},
        "teamB": {"name": "Arabia Saudí", "total": 47,
                  "periods": {"Q1": 26, "Q2": 18, "Q3": 3, "Q4": None}},
    }), now=6500.0)
    estado = fuente.game_state(now=6500.5)
    assert estado["team_a"] == "Baréin"
    assert estado["periods_a"] == {"Q1": 21, "Q2": 25, "Q3": 19, "Q4": 0}
    assert estado["periods_b"]["Q4"] is None
    assert "period_pace" not in estado and "half_pace" not in estado


def test_cambiar_evento_limpia_nombres_y_parciales_del_paquete_anterior():
    fuente = BrowserSource()
    fuente.accept(payload(gameState={
        "scoreA": 65, "scoreB": 47,
        "teamA": {"name": "Baréin", "total": 65, "periods": {"Q1": 21}},
        "teamB": {"name": "Arabia Saudí", "total": 47, "periods": {"Q1": 26}},
    }), now=6600.0)
    fuente.accept(payload(event={"id": "evento-nuevo", "name": "C vs D"},
                          gameState={"period": 1}), now=6601.0)
    estado = fuente.game_state(now=6601.5)
    assert estado == {"period": 1}


def test_el_reloj_acumulado_cuenta_como_reloj_cubierto():
    fuente = BrowserSource()
    fuente.accept(payload(gameState={"period": 4, "clockRaw": "33:52",
                                     "clockSemantics": "GAME_ELAPSED"}), now=7000.0)
    # Para "que falta para empezar", el reloj esta cubierto: el lector lo
    # convertira con sus reglas.
    assert "clock_seconds" in fuente.available_fields(now=7000.5)


def test_el_reloj_directo_sigue_llegando_como_restante():
    fuente = BrowserSource()
    fuente.accept(payload(gameState={"period": 4, "clock": "06:08",
                                     "clockRaw": "06:08",
                                     "clockSemantics": "PERIOD_REMAINING"}), now=8000.0)
    estado = fuente.game_state(now=8000.5)
    assert estado["clock_seconds"] == 6 * 60 + 8
    assert estado["clock_semantics"] == "PERIOD_REMAINING"
