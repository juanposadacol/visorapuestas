"""Prueba de integracion del ciclo completo, sin pantalla ni OCR real.

Se usa el motor simulado (`StubEngine`) y la captura nula: el pipeline es
exactamente el mismo que en produccion, solo cambia de donde sale el texto.
"""

import pytest

from visorunder.calculations.metrics import compute_bet_metrics, compute_general_metrics
from visorunder.capture.roi import Rect, RoiKind
from visorunder.capture.roi_manager import RoiManager
from visorunder.capture.screen_capture import NullCapture
from visorunder.config.profiles import SportsbookProfile
from visorunder.diagnostics.logbus import LogBus
from visorunder.domain.market import MarketKey, MarketType, Side
from visorunder.ocr.engines.stub_engine import StubEngine
from visorunder.pipeline.reader import LiveReader
from visorunder.storage.database import Database
from visorunder.storage.repositories import HistoryRepository, SessionRepository


@pytest.fixture()
def rig():
    profile = SportsbookProfile(name="Test", sportsbook="Sportium", frame=Rect(0, 0, 1920, 1080))
    profile.set_roi(RoiKind.CLOCK, Rect(100, 100, 100, 40))
    profile.set_roi(RoiKind.PERIOD, Rect(220, 100, 60, 40))
    profile.set_roi(RoiKind.SCORE_PAIR, Rect(300, 100, 200, 40))
    profile.set_roi(RoiKind.MARKET_LABEL, Rect(1200, 300, 400, 40))
    profile.set_roi(RoiKind.MARKET_BLOCK, Rect(1200, 350, 400, 300))
    engine = StubEngine()
    manager = RoiManager(profile, NullCapture(), use_anchor=False)
    reader = LiveReader(manager, engine, logbus=LogBus(), required_confirmations=2,
                        sportsbook="Sportium", event_name="Cal Irvine vs Chinese Taipei")
    return reader, engine


def _feed(reader, engine, *, clock, period, score, label=None, block=None, times=3):
    engine.set_text("CLOCK", clock)
    engine.set_text("PERIOD", period)
    engine.set_text("SCORE_PAIR", score)
    if label is not None:
        engine.set_text("MARKET_LABEL", label)
    if block is not None:
        engine.set_text("MARKET_BLOCK", block)
    snapshot = None
    for _ in range(times):
        snapshot = reader.tick()
    return snapshot


def test_ciclo_confirma_reloj_marcador_y_cuarto(rig):
    reader, engine = rig
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    assert snap.state.clock_value == 328
    assert snap.state.period_value == 3
    assert (snap.state.score_a_value, snap.state.score_b_value) == (43, 31)
    assert snap.state.total_points == 74
    assert snap.state.elapsed_period_seconds == 272


def test_no_confirma_con_una_sola_lectura(rig):
    reader, engine = rig
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31", times=1)
    assert snap.state.clock_value is None
    assert snap.state.period_value is None


def test_puntos_del_cuarto_desconocidos_al_arrancar_a_mitad(rig):
    reader, engine = rig
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    general = compute_general_metrics(snap.state)
    assert general.period_points is None       # no se inventa
    assert general.total_points == 74          # el total si se conoce
    assert snap.needs_period_baseline is True  # hay que preguntar al usuario


def test_baseline_manual_desbloquea_las_metricas_del_cuarto(rig):
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    reader.state.tracker.set_manual_baseline(3, 34, 21)
    snap = reader.tick()
    general = compute_general_metrics(snap.state)
    assert general.period_points == 19
    assert general.period_pace == pytest.approx(19 / (272 / 60), abs=1e-6)
    assert snap.needs_period_baseline is False


def test_cambio_de_cuarto_calcula_los_puntos_sin_preguntar(rig):
    reader, engine = rig
    _feed(reader, engine, clock="00:04", period="Q2", score="40 - 38")
    _feed(reader, engine, clock="10:00", period="Q3", score="40 - 38")
    _feed(reader, engine, clock="09:20", period="Q3", score="45 - 42")
    snap = reader.tick()
    assert snap.state.period_value == 3
    assert compute_general_metrics(snap.state).period_points == 9  # (45-40)+(42-38)
    assert snap.needs_period_baseline is False


def test_lee_varias_lineas_del_mercado(rig):
    reader, engine = rig
    block = ("37.5 OVER 1.55 UNDER 2.25\n38.5 OVER 1.68 UNDER 2.05\n"
             "39.5 OVER 1.80 UNDER 1.90\n40.5 OVER 1.95 UNDER 1.72")
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31",
                 label="3.er Cuarto - Total de puntos", block=block)
    assert snap.market is not None
    assert [ln.line for ln in snap.market.sorted_lines()] == [37.5, 38.5, 39.5, 40.5]
    assert snap.market.key.market_type is MarketType.QUARTER_TOTAL
    assert snap.market.key.period == 3
    assert all(ln.quarter == 3 for ln in snap.market.lines)


def test_la_linea_del_q3_no_se_usa_para_el_q2_en_juego(rig):
    """Requisito 5: partido en Q2 00:04 y mercado ya del Q3."""
    reader, engine = rig
    snap = _feed(reader, engine, clock="00:04", period="Q2", score="40 - 38",
                 label="3.er Cuarto - Total de puntos", block="40.5 OVER 1.75 UNDER 1.87")
    reader.state.tracker.set_manual_baseline(2, 20, 19)
    snap = reader.tick()
    linea = snap.market.sorted_lines()[0]
    m = compute_bet_metrics(snap.state, linea.key, linea.line, linea.under_odds, Side.UNDER)
    assert linea.quarter == 3
    assert m.scope_points == 0            # el Q3 no ha empezado
    assert m.scope_remaining_seconds == 600
    # Los 39 puntos del Q2 en curso NO entran en el calculo del Q3.
    assert compute_general_metrics(snap.state).period_points == 39
    assert m.scope_points != 39


def test_mercado_de_partido(rig):
    reader, engine = rig
    snap = _feed(reader, engine, clock="08:30", period="Q4", score="60 - 56",
                 label="Partido - Total de puntos", block="153.5 OVER 1.85 UNDER 1.80")
    linea = snap.market.sorted_lines()[0]
    m = compute_bet_metrics(snap.state, linea.key, linea.line, linea.under_odds)
    assert m.exceed_threshold == 154
    assert m.points_to_exceed == 38
    assert m.scope_remaining_seconds == 510
    assert m.required_pace == pytest.approx(38 / 8.5, abs=1e-6)


def test_ocr_perdido_no_borra_el_dato_al_instante(rig):
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    engine.set_text("CLOCK", "")
    snap = reader.tick()
    assert snap.state.clock_value == 328  # sigue vigente dentro del TTL


def test_marcador_absurdo_no_contamina_el_estado(rig):
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="36 - 30")
    engine.set_text("SCORE_PAIR", "86 - 30")
    reader.tick()
    assert reader.state.score_a_value == 36


def test_historial_se_guarda_en_sqlite(rig):
    reader, engine = rig
    db = Database(":memory:")
    sessions = SessionRepository(db)
    history = HistoryRepository(db)
    reader.history = history
    reader.session_id = sessions.start(None, None)

    _feed(reader, engine, clock="08:42", period="Q3", score="32 - 27",
          label="3.er Cuarto - Total de puntos", block="42.5 OVER 1.80 UNDER 1.85")
    reader._last_score_persist = 0.0
    reader.tick()
    _feed(reader, engine, clock="07:55", period="Q3", score="34 - 29",
          block="41.5 OVER 1.78 UNDER 1.87")

    market_rows = history.market_history(reader.session_id)
    assert {row["line"] for row in market_rows} == {42.5, 41.5}
    assert history.score_history(reader.session_id)
    assert history.observations(reader.session_id)
    db.close()


def test_el_log_de_diagnostico_registra_bruto_y_confirmado(rig):
    reader, engine = rig
    _feed(reader, engine, clock="O5:2B", period="Q3", score="43 - 31")
    entries = [e for e in reader.log.entries() if e.region == "CLOCK"]
    assert entries
    assert entries[-1].raw == "O5:2B"
    assert entries[-1].normalized == "05:28"
    assert entries[-1].value == "328"


# ---------------------------------------- mercado por defecto (requisito 5)
def test_sin_titulo_de_mercado_se_usa_la_eleccion_explicita_del_perfil(rig):
    """Sin ROI de titulo NO se supone 'partido': manda lo que eligio el usuario."""
    reader, engine = rig
    reader.roi_manager.profile.remove_roi(RoiKind.MARKET_LABEL)
    reader.roi_manager.refresh_layout()
    reader.roi_manager.profile.default_market = "CURRENT_QUARTER"
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31",
                 block="40.5 OVER 1.75 UNDER 1.87")
    assert snap.market.key == MarketKey.quarter(3)
    assert snap.market_from_label is False


def test_mercado_por_defecto_de_partido(rig):
    reader, engine = rig
    reader.roi_manager.profile.remove_roi(RoiKind.MARKET_LABEL)
    reader.roi_manager.refresh_layout()
    reader.roi_manager.profile.default_market = "GAME"
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31",
                 block="153.5 OVER 1.85 UNDER 1.80")
    assert snap.market.key.market_type is MarketType.GAME_TOTAL


def test_no_se_publican_lineas_si_el_mercado_no_puede_atribuirse(rig):
    """CURRENT_QUARTER sin cuarto confirmado: mejor sin lineas que mal atribuidas."""
    reader, engine = rig
    reader.roi_manager.profile.remove_roi(RoiKind.MARKET_LABEL)
    reader.roi_manager.profile.remove_roi(RoiKind.PERIOD)
    reader.roi_manager.refresh_layout()
    reader.roi_manager.profile.default_market = "CURRENT_QUARTER"
    engine.set_text("CLOCK", "05:28")
    engine.set_text("SCORE_PAIR", "43 - 31")
    engine.set_text("MARKET_BLOCK", "40.5 OVER 1.75 UNDER 1.87")
    snap = None
    for _ in range(4):
        snap = reader.tick()
    assert snap.market is None


def test_el_titulo_leido_tiene_prioridad_sobre_el_defecto(rig):
    reader, engine = rig
    reader.roi_manager.profile.default_market = "GAME"
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31",
                 label="3.er Cuarto - Total de puntos", block="40.5 OVER 1.75 UNDER 1.87")
    assert snap.market.key == MarketKey.quarter(3)
    assert snap.market_from_label is True


# ------------------------------------------------ varios mercados (etapa 3)
def _feed_market(reader, engine, label, block, times=3):
    engine.set_text("MARKET_LABEL", label)
    engine.set_text("MARKET_BLOCK", block)
    snapshot = None
    for _ in range(times):
        snapshot = reader.tick()
    return snapshot


def test_varios_mercados_del_mismo_partido_conviven(rig):
    """Requisito B: 3 + 4 + 3 lineas repartidas en tres pestanas."""
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")

    _feed_market(reader, engine, "Partido - Total de puntos",
                 "176.5 OVER 1.85 UNDER 2.05\n178.5 OVER 1.90 UNDER 1.93\n"
                 "180.5 OVER 2.00 UNDER 1.81")
    _feed_market(reader, engine, "1.a mitad - Total de puntos",
                 "78.5 OVER 1.80 UNDER 2.02\n80.5 OVER 1.98 UNDER 1.82\n"
                 "82.5 OVER 2.15 UNDER 1.67\n84.5 OVER 2.30 UNDER 1.55")
    snap = _feed_market(reader, engine, "2.o cuarto - Total de puntos",
                        "38.5 OVER 1.78 UNDER 2.04\n39.5 OVER 1.90 UNDER 1.91\n"
                        "40.5 OVER 2.00 UNDER 1.80")

    markets = snap.markets
    assert len(markets) == 3
    assert markets.total_lines() == 10
    assert len(markets.get(MarketKey.game()).lines) == 3
    assert len(markets.get(MarketKey.half_market(1)).lines) == 4
    assert len(markets.get(MarketKey.quarter(2)).lines) == 3


def test_cada_linea_queda_en_su_mercado(rig):
    """Requisito I: una linea de 1H jamas acaba en GAME ni en Q2."""
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    _feed_market(reader, engine, "Partido - Total de puntos", "180.5 OVER 2.00 UNDER 1.81")
    _feed_market(reader, engine, "1.a mitad - Total de puntos", "80.5 OVER 1.98 UNDER 1.82")
    snap = _feed_market(reader, engine, "2.o cuarto - Total de puntos",
                        "40.5 OVER 2.00 UNDER 1.80")

    for key in (MarketKey.game(), MarketKey.half_market(1), MarketKey.quarter(2)):
        for line in snap.markets.get(key).lines:
            assert line.key == key
    assert [ln.line for ln in snap.markets.get(MarketKey.half_market(1)).lines] == [80.5]
    assert [ln.line for ln in snap.markets.get(MarketKey.game()).lines] == [180.5]


def test_al_cambiar_de_pestana_el_mercado_anterior_conserva_sus_lineas(rig):
    """Requisito D: se conservan, pero dejan de estar EN VIVO."""
    from visorunder.config.freshness import FreshnessCriteria
    from visorunder.domain.event_markets import FreshnessState

    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    _feed_market(reader, engine, "2.o cuarto - Total de puntos", "40.5 OVER 2.00 UNDER 1.80")
    q2 = reader.markets.get(MarketKey.quarter(2))
    visto_en = q2.last_seen_at
    assert q2.visible is True

    snap = _feed_market(reader, engine, "Partido - Total de puntos",
                        "180.5 OVER 2.00 UNDER 1.81")
    q2 = snap.markets.get(MarketKey.quarter(2))
    assert q2.visible is False
    assert [ln.line for ln in q2.lines] == [40.5]        # se conservan
    assert q2.last_seen_at == visto_en                   # no se refresca solo
    criteria = FreshnessCriteria(recent_after_seconds=5, stale_after_seconds=15)
    assert q2.freshness(criteria, now=visto_en + 20) is FreshnessState.STALE
    assert snap.markets.visible.key == MarketKey.game()


def test_un_mercado_que_reaparece_pasa_por_revision(rig):
    """Requisito E."""
    from visorunder.domain.event_markets import FreshnessState
    from visorunder.config.freshness import FreshnessCriteria

    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    _feed_market(reader, engine, "2.o cuarto - Total de puntos", "40.5 OVER 2.00 UNDER 1.80")
    _feed_market(reader, engine, "Partido - Total de puntos", "180.5 OVER 2.00 UNDER 1.81")

    # vuelve a Q2 con una linea distinta: una sola lectura no la publica
    engine.set_text("MARKET_LABEL", "2.o cuarto - Total de puntos")
    engine.set_text("MARKET_BLOCK", "41.5 OVER 2.10 UNDER 1.69")
    for _ in range(3):
        snap = reader.tick()      # el titulo tarda en confirmarse
    q2 = snap.markets.get(MarketKey.quarter(2))
    criteria = FreshnessCriteria()
    if q2.under_review:
        assert q2.freshness(criteria) is FreshnessState.REVIEWING
        assert [ln.line for ln in q2.lines] == [40.5]   # sigue la anterior

    for _ in range(3):
        snap = reader.tick()
    q2 = snap.markets.get(MarketKey.quarter(2))
    assert [ln.line for ln in q2.lines] == [41.5]
    assert q2.visible is True
    assert q2.freshness(criteria) is FreshnessState.LIVE


def test_una_lectura_rezagada_no_contamina_el_mercado_nuevo(rig):
    """El tracker es por mercado: un fotograma viejo no se confirma solo."""
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    _feed_market(reader, engine, "2.o cuarto - Total de puntos", "40.5 OVER 2.00 UNDER 1.80")

    # El titulo ya dice Partido pero el bloque aun ensena las lineas del Q2.
    engine.set_text("MARKET_LABEL", "Partido - Total de puntos")
    for _ in range(3):
        reader.tick()
    juego = reader.markets.get(MarketKey.game())
    # Con una unica lectura del bloque viejo, el mercado de partido no publica
    # nada o publica solo tras confirmarse; en ningun caso hereda la del Q2
    # bajo la clave equivocada.
    if juego is not None and juego.snapshot is not None:
        for line in juego.lines:
            assert line.key == MarketKey.game()


def test_seleccion_manual_del_mercado_visible(rig):
    """Respaldo cuando el titulo no se puede leer."""
    reader, engine = rig
    reader.roi_manager.profile.remove_roi(RoiKind.MARKET_LABEL)
    reader.roi_manager.refresh_layout()
    reader.set_manual_visible_market(MarketKey.half_market(2))
    snap = _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31",
                 block="79.5 OVER 1.90 UNDER 1.88")
    assert snap.markets.visible_key == MarketKey.half_market(2)
    assert snap.markets.get(MarketKey.half_market(2)).lines[0].key.half == 2


def test_durante_el_cambio_de_pestana_no_se_atribuye_ninguna_linea(rig):
    """El fallo mas peligroso: publicar las lineas nuevas bajo la clave vieja.

    Mientras el titulo en bruto ya dice 'Partido' pero el confirmado sigue
    diciendo 'Q2', no puede publicarse nada: el Q2 conserva sus lineas y el
    mercado de partido no recibe ninguna que no sea suya.
    """
    reader, engine = rig
    _feed(reader, engine, clock="05:28", period="Q3", score="43 - 31")
    _feed_market(reader, engine, "2.o cuarto - Total de puntos", "40.5 OVER 2.00 UNDER 1.80")
    q2_antes = reader.markets.get(MarketKey.quarter(2)).last_seen_at

    # cambia el titulo y el bloque a la vez: primera lectura de la transicion
    engine.set_text("MARKET_LABEL", "Partido - Total de puntos")
    engine.set_text("MARKET_BLOCK", "180.5 OVER 2.00 UNDER 1.81")
    snap = reader.tick()

    assert snap.market_in_transition is True
    q2 = reader.markets.get(MarketKey.quarter(2))
    assert [ln.line for ln in q2.lines] == [40.5]     # intacto
    assert q2.last_seen_at == q2_antes                # ni siquiera se refresca
    # el mercado de partido no recibe lineas que no sean suyas
    juego = reader.markets.get(MarketKey.game())
    assert juego is None or not juego.has_lines

    # confirmado el titulo, el mercado de partido recibe SUS lineas
    for _ in range(4):
        snap = reader.tick()
    assert snap.market_in_transition is False
    assert [ln.line for ln in snap.markets.get(MarketKey.game()).lines] == [180.5]
    assert [ln.line for ln in snap.markets.get(MarketKey.quarter(2)).lines] == [40.5]
