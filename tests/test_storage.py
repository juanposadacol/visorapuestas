"""Requisitos 19, 24, 27 y 28: persistencia local."""

import pytest

from visorunder.capture.roi import Rect, RoiKind
from visorunder.config.profiles import ScreenContext, SportsbookProfile
from visorunder.domain.bet import LockedBet
from visorunder.domain.game_state import GameState
from visorunder.domain.market import MarketKey, MarketLine, MarketSnapshot, Side
from visorunder.domain.values import Observed
from visorunder.storage.database import Database
from visorunder.storage.repositories import (
    BetRepository,
    HistoryRepository,
    ProfileRepository,
    SessionRepository,
)


@pytest.fixture()
def db():
    database = Database(":memory:")
    yield database
    database.close()


def _profile():
    p = SportsbookProfile(name="Sportium 1080", sportsbook="Sportium",
                          frame=Rect(0, 0, 1920, 1080))
    p.set_roi(RoiKind.CLOCK, Rect(100, 200, 120, 40))
    p.set_roi(RoiKind.PERIOD, Rect(240, 200, 60, 40))
    p.set_roi(RoiKind.SCORE_PAIR, Rect(400, 200, 200, 40))
    p.set_roi(RoiKind.MARKET_BLOCK, Rect(1200, 400, 300, 260))
    return p


def test_esquema_versionado(db):
    assert db.version == 1
    db.migrate()  # idempotente
    assert db.version == 1


def test_guardar_y_cargar_perfil(db):
    repo = ProfileRepository(db)
    profile = _profile()
    repo.save(profile)
    loaded = repo.load("Sportium 1080")
    assert loaded is not None
    assert loaded.sportsbook == "Sportium"
    assert set(loaded.rois) == set(profile.rois)
    assert loaded.get_roi(RoiKind.CLOCK).rect == profile.get_roi(RoiKind.CLOCK).rect
    assert loaded.is_ready


def test_actualizar_perfil_no_duplica(db):
    repo = ProfileRepository(db)
    profile = _profile()
    repo.save(profile)
    profile.notes = "segunda version"
    repo.save(profile)
    assert repo.list_names() == ["Sportium 1080"]
    assert repo.load("Sportium 1080").notes == "segunda version"


def test_regiones_quedan_consultables(db):
    repo = ProfileRepository(db)
    repo.save(_profile())
    rows = db.query("SELECT kind FROM screen_regions ORDER BY kind")
    assert {r["kind"] for r in rows} == {"CLOCK", "PERIOD", "SCORE_PAIR", "MARKET_BLOCK"}


def test_historial_de_mercado(db):
    sessions = SessionRepository(db)
    history = HistoryRepository(db)
    event_id = sessions.create_event("Sportium", "Cal Irvine", "Chinese Taipei")
    session_id = sessions.start(event_id, None)

    key = MarketKey.quarter(3)
    snapshot = MarketSnapshot(key=key, lines=[
        MarketLine("Sportium", "Cal Irvine vs Chinese Taipei", key, 42.5, 1.80, 1.85),
        MarketLine("Sportium", "Cal Irvine vs Chinese Taipei", key, 41.5, 1.78, 1.87),
    ])
    state = GameState()
    state.score_a = Observed.confirmed(32)
    state.score_b = Observed.confirmed(27)
    state.period = Observed.confirmed(3)
    state.clock_seconds = Observed.confirmed(522)

    assert history.save_market_snapshot(session_id, snapshot, state) == 2
    rows = history.market_history(session_id)
    assert len(rows) == 2
    assert rows[0]["period"] == 3
    assert rows[0]["score_a"] == 32


def test_historial_de_marcador_y_baseline(db):
    sessions = SessionRepository(db)
    history = HistoryRepository(db)
    session_id = sessions.start(None, None)

    state = GameState()
    state.period = Observed.confirmed(3)
    state.clock_seconds = Observed.confirmed(600)
    state.score_a = Observed.confirmed(34)
    state.score_b = Observed.confirmed(21)
    history.save_score_snapshot(session_id, state)

    state.clock_seconds = Observed.confirmed(328)
    state.score_a = Observed.confirmed(43)
    state.score_b = Observed.confirmed(31)
    history.save_score_snapshot(session_id, state)

    first = history.first_score_of_period(session_id, 3)
    assert (first["score_a"], first["score_b"]) == (34, 21)


def test_apuesta_fijada_se_guarda_y_se_recupera(db):
    sessions = SessionRepository(db)
    bets = BetRepository(db)
    session_id = sessions.start(None, None)

    bet = LockedBet(sportsbook="Sportium", event="Cal Irvine vs Chinese Taipei",
                    key=MarketKey.quarter(3), side=Side.UNDER, line=40.5, odds=1.87,
                    score_a_when_locked=43, score_b_when_locked=31,
                    clock_when_locked=328, period_when_locked=3, session_id=session_id)
    bet_id = bets.save(bet)
    restored = bets.list_for_session(session_id)
    assert len(restored) == 1
    r = restored[0]
    assert (r.line, r.odds, r.side) == (40.5, 1.87, Side.UNDER)
    assert r.key.period == 3
    assert r.clock_when_locked == 328
    bets.close(bet_id)
    assert db.query_one("SELECT status FROM bets WHERE id = ?", (bet_id,))["status"] == "CLOSED"


def test_observaciones_ocr_para_diagnostico(db):
    sessions = SessionRepository(db)
    history = HistoryRepository(db)
    session_id = sessions.start(None, None)
    history.log_observation(session_id, "CLOCK", "O5:2B", "05:28", 0.91, "328", "CONFIRMED")
    rows = history.observations(session_id)
    assert rows[0]["raw_text"] == "O5:2B"
    assert rows[0]["value_text"] == "328"
