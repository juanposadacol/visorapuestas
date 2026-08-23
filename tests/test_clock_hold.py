"""El reloj pausado conserva tiempo; nunca fabrica un countdown."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visorunder.bridge.source import BrowserSource, BrowserSourceSettings, SourceKind
from visorunder.calculations.entry import evaluate_line
from visorunder.calculations.metrics import compute_bet_metrics, compute_general_metrics
from visorunder.capture.roi import Rect
from visorunder.capture.roi_manager import RoiManager
from visorunder.capture.screen_capture import NullCapture
from visorunder.config.criteria import EntryCriteria
from visorunder.config.profiles import SportsbookProfile
from visorunder.domain.game_state import GamePhase
from visorunder.domain.market import MarketKey, MarketLine
from visorunder.domain.rules import FIBA, NBA
from visorunder.ocr.engines.stub_engine import StubEngine
from visorunder.pipeline.reader import LiveReader


def _game_state(*, score_a=56, score_b=35, period=2, clock=None, phase=None,
                periods_a=None, periods_b=None):
    state = {"scoreA": score_a, "scoreB": score_b, "period": period}
    if clock is not None:
        state["clock"] = clock
    if phase is not None:
        state["phase"] = phase
    if periods_a is not None:
        state["teamA"] = {
            "name": "Dallas Wings (F)", "total": score_a, "periods": periods_a,
        }
    if periods_b is not None:
        state["teamB"] = {
            "name": "Seattle Storm (F)", "total": score_b, "periods": periods_b,
        }
    return state


def _payload(*, event_id="dallas-seattle", state=None, market="GAME_TOTAL",
             period=None, line=174.5, under=1.90):
    return {
        "protocol": 1,
        "source": "betplay",
        "observedAt": "2026-08-23T00:00:00.000Z",
        "event": {"id": event_id, "name": "Dallas Wings (F) vs Seattle Storm (F)"},
        "visibleMarket": {
            "marketType": market, "period": period, "half": None,
            "confidence": 0.99, "rawTitle": "Total", "sidesConfirmed": True,
        },
        "lines": [{"line": line, "overOdds": 1.80, "underOdds": under}],
        "gameState": state,
    }


def _rig(rules=FIBA):
    source = BrowserSource(BrowserSourceSettings(disconnected_after_seconds=12))
    profile = SportsbookProfile(
        name="DOM", sportsbook="BetPlay", frame=Rect(0, 0, 1920, 1080))
    manager = RoiManager(profile, NullCapture(), use_anchor=False)
    reader = LiveReader(
        manager, StubEngine(), rules=rules, browser_source=source,
        required_confirmations=2, sportsbook="BetPlay",
    )
    return source, reader


def _line(key, value):
    return MarketLine(
        sportsbook="BetPlay", event="Dallas vs Seattle", key=key, line=value,
        over_odds=1.80, under_odds=1.90, confirmed=True,
    )


def test_timeout_mas_de_30_segundos_con_reloj_inmovil_no_fabrica_countdown():
    source, reader = _rig()
    for now in (0.0, 31.0, 62.0):
        source.accept(_payload(state=_game_state(
            clock="04:37", phase="CLOCK_STOPPED")), now=now)
        state = reader.tick(now=now + 0.1).state
        assert state.clock_value == 277
        assert state.phase is GamePhase.CLOCK_STOPPED
    assert reader.state.clock_held is False  # reloj observado, no reconstruido


def test_reloj_temporalmente_ausente_se_retiene_mas_de_30_segundos_sin_countdown():
    source, reader = _rig()
    source.accept(_payload(state=_game_state(clock="04:37")), now=0.0)
    assert reader.tick(now=0.1).state.clock_value == 277

    for now in (31.0, 62.0):
        source.accept(_payload(state=_game_state()), now=now)
        state = reader.tick(now=now + 0.1).state
        assert state.clock_value == 277
        assert state.clock_held is True
        assert state.phase is GamePhase.CLOCK_STOPPED
    assert reader.state.clock_value == 277, "no existe countdown sintetico"


def test_fixture_dallas_seattle_en_halftime_conserva_todas_las_metricas():
    source, reader = _rig()
    state = _game_state(
        phase="HALFTIME",
        periods_a={"Q1": 34, "Q2": 22, "Q3": None, "Q4": None},
        periods_b={"Q1": 17, "Q2": 18, "Q3": None, "Q4": None},
    )
    source.accept(_payload(state=state), now=100.0)
    snapshot = reader.tick(now=100.1)
    general = compute_general_metrics(snapshot.state)
    game = compute_bet_metrics(snapshot.state, MarketKey.game(), 174.5)

    assert snapshot.state.phase is GamePhase.HALFTIME
    assert snapshot.state.clock_value == 0
    assert general.elapsed_period_seconds == FIBA.period_seconds(2)
    assert general.period_points == 40
    assert general.period_pace == pytest.approx(4.00)
    assert general.half_points == 91
    assert general.half_pace == pytest.approx(4.55)
    assert general.total_points == 91
    assert general.game_pace == pytest.approx(4.55)
    assert game.exceed_threshold == 175
    assert game.points_to_exceed == 84
    assert game.scope_remaining_seconds == 20 * 60
    assert game.required_pace == pytest.approx(4.20)


def test_fixture_halftime_se_muestra_en_ui_sin_guiones():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from visorunder.ui.metrics_panel import MetricsPanel

    source, reader = _rig()
    source.accept(_payload(state=_game_state(
        phase="HALFTIME",
        periods_a={"Q1": 34, "Q2": 22, "Q3": None, "Q4": None},
        periods_b={"Q1": 17, "Q2": 18, "Q3": None, "Q4": None},
    )), now=100.0)
    snapshot = reader.tick(now=100.1)
    general = compute_general_metrics(snapshot.state)
    evaluation = evaluate_line(
        snapshot.state, _line(MarketKey.game(), 174.5), EntryCriteria(), general)

    app = QApplication.instance() or QApplication([])
    panel = MetricsPanel()
    panel.update_view(snapshot.state, general, evaluation=evaluation,
                      criteria=EntryCriteria())
    assert panel.played_label.text() == "10:00"
    assert panel.period_points_label.text().startswith("40")
    assert panel.period_pace_label.text() == "4.00 pts/min"
    assert panel.half_points_label.text().endswith("91 pts")
    assert panel.half_pace_label.text() == "4.55 pts/min"
    assert panel.game_points_label.text().endswith("91 pts")
    assert panel.game_pace_label.text() == "4.55 pts/min"
    assert panel.points_to_exceed_label.text() == "84 PUNTOS"
    assert panel.required_pace_label.text() == "4.20 pts/min"
    assert "RELOJ NO CONFIRMADO" not in panel.exceeded_label.text()
    panel.deleteLater()
    app.processEvents()


def test_q3_ofrecido_durante_descanso_usa_scope_futuro_independiente():
    source, reader = _rig()
    halftime = _game_state(
        phase="HALFTIME",
        periods_a={"Q1": 34, "Q2": 22, "Q3": None, "Q4": None},
        periods_b={"Q1": 17, "Q2": 18, "Q3": None, "Q4": None},
    )
    source.accept(_payload(state=halftime, market="QUARTER_TOTAL",
                           period=3, line=41.5), now=200.0)
    snapshot = reader.tick(now=200.1)
    metrics = compute_bet_metrics(snapshot.state, MarketKey.quarter(3), 41.5)
    general = compute_general_metrics(snapshot.state)

    assert metrics.scope_points == 0
    assert metrics.scope_elapsed_seconds == 0
    assert metrics.scope_remaining_seconds == FIBA.period_seconds(3)
    assert metrics.current_pace is None
    assert metrics.points_to_exceed == 42
    assert metrics.required_pace == pytest.approx(4.20)
    assert general.period_pace == pytest.approx(4.00)  # Q2 final sigue visible
    assert general.half_pace == pytest.approx(4.55)
    assert general.game_pace == pytest.approx(4.55)


def test_mercado_y_cuota_cambian_mientras_el_reloj_esta_retenido():
    source, reader = _rig()
    source.accept(_payload(state=_game_state(clock="04:37")), now=0.0)
    reader.tick(now=0.1)

    source.accept(_payload(state=_game_state(), line=176.5, under=2.05), now=31.0)
    snapshot = reader.tick(now=31.1)
    market = snapshot.markets.get(MarketKey.game())
    assert snapshot.state.clock_value == 277
    assert market.lines[0].line == 176.5
    assert market.lines[0].under_odds == 2.05


def test_correccion_de_marcador_recalcula_con_el_mismo_tiempo_retenido():
    source, reader = _rig()
    source.accept(_payload(state=_game_state(score_a=56, score_b=35, clock="04:37")), now=0)
    reader.tick(now=0.1)
    source.accept(_payload(state=_game_state(score_a=55, score_b=35)), now=31)
    snapshot = reader.tick(now=31.1)

    assert snapshot.state.total_points == 90
    assert snapshot.state.clock_value == 277
    assert snapshot.state.clock_held is True


def test_reanudacion_valida_reemplaza_automaticamente_el_reloj_retenido():
    source, reader = _rig()
    source.accept(_payload(state=_game_state(clock="04:37")), now=0)
    reader.tick(now=0.1)
    source.accept(_payload(state=_game_state()), now=31)
    assert reader.tick(now=31.1).state.clock_held is True

    source.accept(_payload(state=_game_state(period=3, clock="09:58")), now=32)
    resumed = reader.tick(now=32.1).state
    assert resumed.period_value == 3
    assert resumed.clock_value == 598
    assert resumed.clock_held is False
    assert resumed.phase is GamePhase.IN_PLAY


def test_cambio_de_evento_y_desconexion_real_no_reutilizan_el_reloj():
    source, reader = _rig()
    source.accept(_payload(state=_game_state(clock="04:37")), now=0)
    reader.tick(now=0.1)
    source.accept(_payload(state=_game_state()), now=5)
    assert reader.tick(now=5.1).state.clock_held is True

    source.accept(_payload(event_id="otro", state=None, line=150.5), now=6)
    changed = reader.tick(now=6.1).state
    assert changed.clock_value is None
    assert changed.clock_held is False

    source2, reader2 = _rig()
    source2.accept(_payload(state=_game_state(clock="04:37")), now=0)
    reader2.tick(now=0.1)
    disconnected = reader2.tick(now=20).state
    assert disconnected.clock_value is None
    assert disconnected.clock_held is False
    assert "clock_seconds" not in reader2.field_sources


@pytest.mark.parametrize(
    ("rules", "period", "clock"),
    [(FIBA, 2, "04:37"), (NBA, 2, "06:37"), (FIBA, 5, "03:12")],
)
def test_reloj_retenido_respeta_fiba_nba_y_overtime(rules, period, clock):
    source, reader = _rig(rules)
    source.accept(_payload(state=_game_state(period=period, clock=clock)), now=0)
    expected = reader.tick(now=0.1).state.clock_value
    source.accept(_payload(state=_game_state(period=period)), now=31)
    held = reader.tick(now=31.1).state
    assert held.clock_value == expected
    assert held.clock_held is True
    assert held.clock_value <= rules.period_seconds(period)


def test_phase_del_puente_se_valida_y_convierte():
    from visorunder.bridge.converter import payload_to_game_state
    from visorunder.bridge.schema import validate_browser_payload

    wire = _payload(state=_game_state(phase="HALFTIME"))
    valid, errors = validate_browser_payload(wire)
    assert valid, errors
    assert payload_to_game_state(wire)["phase"] == "HALFTIME"

    wire["gameState"]["phase"] = "PAUSA_INVENTADA"
    valid, errors = validate_browser_payload(wire)
    assert not valid
    assert any("phase" in error for error in errors)
