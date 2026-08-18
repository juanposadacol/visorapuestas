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
