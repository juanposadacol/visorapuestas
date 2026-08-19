"""Conversion del payload del navegador y estado de la fuente DOM."""

from __future__ import annotations

import pytest

from visorunder.bridge import converter
from visorunder.bridge.source import BrowserSource, BrowserSourceSettings, LinkState, SourceKind
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
    assert LinkState.DISCONNECTED.label == "EXTENSION DESCONECTADA"
    assert SourceKind.BROWSER_DOM.label == "DOM"
