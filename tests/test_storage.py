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
    from visorunder.storage.database import SCHEMA_VERSION

    assert db.version == SCHEMA_VERSION
    db.migrate()  # idempotente
    assert db.version == SCHEMA_VERSION


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


# --------------------------------------- criterios de la sesion (migracion 002)
def test_las_migraciones_actualizan_una_base_de_la_version_1(tmp_path):
    """Una base ya existente debe subir de version sin perder el historial."""
    import sqlite3

    from visorunder.storage.database import SCHEMA_VERSION, _migration_001

    path = tmp_path / "vieja.db"
    cx = sqlite3.connect(path)
    _migration_001(cx)
    cx.execute("PRAGMA user_version = 1")
    cx.execute("INSERT INTO sessions (started_at, status) VALUES (?, ?)", (1000.0, "FINISHED"))
    cx.commit()
    cx.close()

    db = Database(path)
    assert db.version == SCHEMA_VERSION
    fila = db.query_one("SELECT started_at, status, entry_criteria FROM sessions")
    assert fila["started_at"] == 1000.0     # el historial anterior sigue ahi
    assert fila["status"] == "FINISHED"
    assert fila["entry_criteria"] == "{}"   # sin criterios registrados
    # y la tabla nueva de la migracion 003 existe
    assert db.query("SELECT name FROM sqlite_master WHERE name='market_observations'")
    db.close()


def test_la_sesion_guarda_los_criterios_usados(db):
    from visorunder.config.criteria import EntryCriteria

    sessions = SessionRepository(db)
    criteria = EntryCriteria(reference_pace=4.25, target_under_odds=1.95,
                             threshold_very_demanding=1.5)
    session_id = sessions.start(None, None, criteria)

    recuperados = sessions.load_criteria(session_id)
    assert recuperados.reference_pace == 4.25
    assert recuperados.target_under_odds == 1.95
    assert recuperados.threshold_very_demanding == 1.5
    # consultables tambien como columnas sueltas
    fila = db.query_one("SELECT reference_pace, target_under_odds FROM sessions WHERE id = ?",
                        (session_id,))
    assert fila["reference_pace"] == 4.25


def test_cambiar_los_criterios_a_mitad_de_sesion_queda_registrado(db):
    from visorunder.config.criteria import EntryCriteria

    sessions = SessionRepository(db)
    session_id = sessions.start(None, None, EntryCriteria())
    sessions.save_criteria(session_id, EntryCriteria(reference_pace=3.8))
    assert sessions.load_criteria(session_id).reference_pace == 3.8


def test_no_se_persisten_datos_derivados(db):
    """Los margenes y las senales se recalculan; no se duplican en la base."""
    tablas = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "line_evaluations" not in tablas
    columnas = {r["name"] for r in db.query("PRAGMA table_info(market_snapshots)")}
    assert not columnas & {"signal", "margin", "required_pace", "points_to_exceed"}


# ------------------------------------------- observaciones de mercado (003)
def test_se_registra_cuando_se_miro_cada_mercado(db):
    from visorunder.domain.market import MarketKey

    sessions = SessionRepository(db)
    history = HistoryRepository(db)
    session_id = sessions.start(None, None)

    history.record_market_observation(session_id, MarketKey.game(), 1000.0, 1000.0)
    history.record_market_observation(session_id, MarketKey.quarter(2), 1005.0, 1005.0)
    history.record_market_observation(session_id, MarketKey.game(), 1010.0, None)

    filas = {(r["market_type"], r["period"], r["half"]): r
             for r in history.market_observations(session_id)}
    juego = filas[("GAME_TOTAL", None, None)]
    assert juego["first_seen_at"] == 1000.0
    assert juego["last_seen_at"] == 1010.0          # se actualiza
    assert juego["last_confirmed_at"] == 1000.0     # no se pierde al no confirmar
    assert juego["observations"] == 2
    assert ("QUARTER_TOTAL", 2, None) in filas


def test_las_lineas_se_guardan_con_su_mercado(db):
    from visorunder.domain.market import MarketKey, MarketLine, MarketSnapshot

    sessions = SessionRepository(db)
    history = HistoryRepository(db)
    session_id = sessions.start(None, None)

    for key, valores in ((MarketKey.game(), [180.5]),
                         (MarketKey.half_market(1), [80.5]),
                         (MarketKey.quarter(2), [40.5])):
        snapshot = MarketSnapshot(key=key, lines=[
            MarketLine("BetPlay", "A vs B", key, v, 1.9, 1.85) for v in valores])
        history.save_market_snapshot(session_id, snapshot)

    filas = history.market_history(session_id)
    por_tipo = {(r["market_type"], r["period"]): r["line"] for r in filas}
    assert por_tipo[("GAME_TOTAL", None)] == 180.5
    assert por_tipo[("HALF_TOTAL", None)] == 80.5
    assert por_tipo[("QUARTER_TOTAL", 2)] == 40.5


def test_no_se_persisten_senales_ni_margenes(db):
    columnas = {r["name"] for r in db.query("PRAGMA table_info(market_observations)")}
    assert not columnas & {"signal", "freshness", "margin", "required_pace"}
