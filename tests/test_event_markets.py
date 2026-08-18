"""Registro multi-mercado y estados de frescura."""

import pytest

from visorunder.config.freshness import FreshnessCriteria
from visorunder.domain.event_markets import EventMarkets, FreshnessState, MarketState
from visorunder.domain.market import MarketKey, MarketLine, MarketSnapshot


def _snapshot(key, *lines):
    return MarketSnapshot(key=key, lines=[
        MarketLine("BetPlay", "A vs B", key, value, over, under)
        for value, over, under in lines
    ])


GAME = MarketKey.game()
H1 = MarketKey.half_market(1)
H2 = MarketKey.half_market(2)
Q2 = MarketKey.quarter(2)
Q3 = MarketKey.quarter(3)


# --------------------------------------------------------------- estructura
def test_evento_agrupa_mercados_con_sus_propias_lineas():
    """EVENTO -> MERCADOS -> MULTIPLES LINEAS, no una lista plana."""
    markets = EventMarkets()
    markets.observe(GAME, _snapshot(GAME, (176.5, 1.85, 2.05), (178.5, 1.90, 1.93),
                                    (180.5, 2.00, 1.81), (182.5, 2.15, 1.68)),
                    confirmed=True, now=1000.0)
    markets.observe(H1, _snapshot(H1, (78.5, 1.80, 2.02), (80.5, 1.98, 1.82),
                                  (82.5, 2.15, 1.67)), confirmed=True, now=1001.0)
    markets.observe(Q2, _snapshot(Q2, (38.5, 1.78, 2.04), (39.5, 1.90, 1.91),
                                  (40.5, 2.00, 1.80), (41.5, 2.10, 1.69)),
                    confirmed=True, now=1002.0)

    assert len(markets) == 3
    assert markets.total_lines() == 11
    assert [ln.line for ln in markets.get(GAME).lines] == [176.5, 178.5, 180.5, 182.5]
    assert [ln.line for ln in markets.get(H1).lines] == [78.5, 80.5, 82.5]
    assert len(markets.get(Q2).lines) == 4


def test_cada_linea_conserva_su_mercado():
    """Requisito I: una linea de 1H jamas puede acabar en GAME ni en Q2."""
    markets = EventMarkets()
    markets.observe(H1, _snapshot(H1, (80.5, 1.98, 1.82)), confirmed=True, now=1000.0)
    markets.observe(GAME, _snapshot(GAME, (180.5, 2.00, 1.81)), confirmed=True, now=1001.0)
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.00, 1.80)), confirmed=True, now=1002.0)

    for key in (GAME, H1, Q2):
        for line in markets.get(key).lines:
            assert line.key == key
    assert {ln.line for ln in markets.get(H1).lines} == {80.5}
    assert {ln.line for ln in markets.get(GAME).lines} == {180.5}


def test_orden_de_presentacion_estable():
    markets = EventMarkets()
    for key in (Q3, GAME, H2, Q2, H1):
        markets.observe(key, _snapshot(key, (40.5, 1.9, 1.9)), confirmed=True, now=1000.0)
    assert [s.key for s in markets.all_states()] == [GAME, H1, H2, Q2, Q3]


# ---------------------------------------------------------------- frescura
def _criteria():
    return FreshnessCriteria(recent_after_seconds=5.0, stale_after_seconds=15.0)


def test_mercado_visible_y_recien_leido_esta_en_vivo():
    markets = EventMarkets()
    markets.observe(GAME, _snapshot(GAME, (180.5, 2.0, 1.81)), confirmed=True, now=1000.0)
    estado = markets.get(GAME)
    assert estado.visible is True
    assert estado.freshness(_criteria(), now=1001.0) is FreshnessState.LIVE
    assert estado.freshness(_criteria(), now=1001.0).label == "EN VIVO"


def test_mercado_oculto_hace_poco_es_reciente():
    markets = EventMarkets()
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.0, 1.80)), confirmed=True, now=1000.0)
    markets.set_visible(GAME)   # el usuario cambia de pestana
    estado = markets.get(Q2)
    assert estado.visible is False
    assert estado.freshness(_criteria(), now=1008.0) is FreshnessState.RECENT


def test_mercado_sin_observar_demasiado_tiempo_esta_desactualizado():
    markets = EventMarkets()
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.0, 1.80)), confirmed=True, now=1000.0)
    markets.set_visible(GAME)
    assert markets.get(Q2).freshness(_criteria(), now=1020.0) is FreshnessState.STALE
    assert markets.get(Q2).describe_age(now=1020.0) == "hace 20 s"


def test_mercado_visible_con_lectura_pendiente_esta_en_revision():
    markets = EventMarkets()
    markets.observe(GAME, _snapshot(GAME, (180.5, 2.0, 1.81)), confirmed=True, now=1000.0)
    markets.observe(GAME, None, confirmed=False, under_review=True,
                    pending_lines=(182.5,), now=1001.0)
    estado = markets.get(GAME)
    assert estado.freshness(_criteria(), now=1001.0) is FreshnessState.REVIEWING
    assert estado.pending_lines == (182.5,)
    # la lectura sin confirmar NO sustituye a la publicada
    assert [ln.line for ln in estado.lines] == [180.5]


def test_mercado_sin_lineas_es_no_disponible():
    markets = EventMarkets()
    estado = markets.ensure(GAME)
    assert estado.freshness(_criteria(), now=1000.0) is FreshnessState.UNAVAILABLE


def test_umbrales_configurables():
    markets = EventMarkets()
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.0, 1.80)), confirmed=True, now=1000.0)
    markets.set_visible(GAME)
    estricto = FreshnessCriteria(recent_after_seconds=1.0, stale_after_seconds=3.0)
    assert markets.get(Q2).freshness(estricto, now=1005.0) is FreshnessState.STALE
    laxo = FreshnessCriteria(recent_after_seconds=30.0, stale_after_seconds=120.0)
    assert markets.get(Q2).freshness(laxo, now=1005.0) is FreshnessState.RECENT


def test_umbrales_incoherentes_se_corrigen():
    c = FreshnessCriteria(recent_after_seconds=20.0, stale_after_seconds=5.0).validate()
    assert c.stale_after_seconds > c.recent_after_seconds


def test_solo_un_mercado_visible_a_la_vez():
    markets = EventMarkets()
    markets.observe(GAME, _snapshot(GAME, (180.5, 2.0, 1.81)), confirmed=True, now=1000.0)
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.0, 1.80)), confirmed=True, now=1001.0)
    assert markets.visible.key == Q2
    assert markets.get(GAME).visible is False
    assert sum(1 for s in markets.all_states() if s.visible) == 1


def test_las_lineas_de_un_mercado_oculto_se_conservan():
    """Requisito D: al ocultarse, sus lineas siguen guardadas pero no en vivo."""
    markets = EventMarkets()
    markets.observe(Q2, _snapshot(Q2, (39.5, 1.9, 1.92), (40.5, 2.0, 1.80)),
                    confirmed=True, now=1000.0)
    markets.set_visible(GAME)
    estado = markets.get(Q2)
    assert [ln.line for ln in estado.lines] == [39.5, 40.5]
    assert estado.freshness(_criteria(), now=1002.0) is not FreshnessState.LIVE


def test_al_reaparecer_pasa_por_revision_y_luego_a_en_vivo():
    """Requisito E."""
    markets = EventMarkets()
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.0, 1.80)), confirmed=True, now=1000.0)
    markets.set_visible(GAME)

    # el usuario vuelve a Q2 y la casa ofrece otra linea: primero en revision
    markets.observe(Q2, None, confirmed=False, under_review=True,
                    pending_lines=(41.5,), now=1030.0)
    assert markets.get(Q2).freshness(_criteria(), now=1030.0) is FreshnessState.REVIEWING

    # confirmada, pasa a en vivo con la linea nueva
    markets.observe(Q2, _snapshot(Q2, (41.5, 2.1, 1.69)), confirmed=True, now=1031.0)
    estado = markets.get(Q2)
    assert estado.freshness(_criteria(), now=1031.0) is FreshnessState.LIVE
    assert [ln.line for ln in estado.lines] == [41.5]


def test_olvido_opcional_de_mercados_muy_viejos():
    markets = EventMarkets()
    markets.observe(Q2, _snapshot(Q2, (40.5, 2.0, 1.80)), confirmed=True, now=1000.0)
    markets.set_visible(GAME)
    criteria = FreshnessCriteria(recent_after_seconds=5, stale_after_seconds=15,
                                 forget_after_seconds=60)
    assert markets.get(Q2).freshness(criteria, now=1030.0) is FreshnessState.STALE
    assert markets.get(Q2).freshness(criteria, now=1200.0) is FreshnessState.UNAVAILABLE
