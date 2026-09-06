"""Persistencia de las apuestas manuales y compatibilidad del esquema.

Se comprueba que:

* una apuesta manual sobrevive a cerrar y reabrir la aplicacion, y vuelve con
  su seguimiento intacto;
* las tres tablas relacionadas conviven sin destruirse: `manual_bets` (libro
  manual), `browser_manual_bets` (enlace del flujo anterior) y `bets`;
* una base ya instalada, con registros dentro, se actualiza sin perder nada;
* una base limpia queda igual que una migrada.

El seguimiento en vivo NO se guarda: es un dato derivado. Con el marcador, el
reloj y la linea se recalcula identico, y duplicarlo en la base solo crearia
dos versiones de la verdad que podrian discrepar. Es el mismo criterio que ya
seguia la migracion 002 con las senales del radar.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from visorunder.app import AppController
from visorunder.calculations.manual_tracking import TrackingStatus
from visorunder.capture.screen_capture import NullCapture
from visorunder.domain.game_state import GameState, PeriodPointsTracker
from visorunder.domain.manual_bet import ManualBet, ManualBetStatus
from visorunder.domain.market import MarketKey, Side
from visorunder.domain.rules import FIBA
from visorunder.domain.values import Observed
from visorunder.storage.database import SCHEMA_VERSION, Database
from visorunder.storage.repositories import ManualBetRepository


def _state(period: int, clock: int, score_a: int, score_b: int, baselines=None):
    tracker = PeriodPointsTracker(rules=FIBA)
    for periodo, (a, b) in (baselines or {}).items():
        tracker.set_baseline(periodo, a, b)
    state = GameState(rules=FIBA, tracker=tracker)
    state.period = Observed.confirmed(period)
    state.clock_seconds = Observed.confirmed(clock)
    state.score_a = Observed.confirmed(score_a)
    state.score_b = Observed.confirmed(score_b)
    return state


@pytest.fixture()
def db():
    database = Database(":memory:")
    yield database
    database.close()


# ---------------------------------------------------------------------------
# 15. Persistencia y reapertura
# ---------------------------------------------------------------------------
def test_las_apuestas_manuales_sobreviven_a_reabrir(tmp_path):
    ruta = str(tmp_path / "apuestas.db")

    primera = AppController(db_path=ruta, capture=NullCapture())
    primera.settings.log_to_file = False
    primera.add_manual_bet(sportsbook="BetPlay", event="Equipo A vs Equipo B",
                           key=MarketKey.quarter(4), side=Side.UNDER,
                           line=40.5, odds=1.80, stake=10_000)
    primera.add_manual_bet(sportsbook="Stake", event="Equipo A vs Equipo B",
                           key=MarketKey.quarter(4), side=Side.UNDER,
                           line=42.5, odds=1.75, stake=0.0)
    primera.add_manual_bet(sportsbook="BetPlay", event="Equipo A vs Equipo B",
                           key=MarketKey.game(), side=Side.OVER,
                           line=185.5, odds=1.90, stake=5_000)
    primera.db.close()

    segunda = AppController(db_path=ruta, capture=NullCapture())
    segunda.settings.log_to_file = False
    try:
        apuestas = segunda.list_manual_bets()
        assert len(apuestas) == 3

        por_casa = {(b.sportsbook, b.line): b for b in apuestas}
        assert por_casa[("BetPlay", 40.5)].key == MarketKey.quarter(4)
        assert por_casa[("BetPlay", 40.5)].side is Side.UNDER
        assert por_casa[("BetPlay", 40.5)].stake == 10_000
        assert por_casa[("Stake", 42.5)].stake == 0.0
        assert por_casa[("Stake", 42.5)].has_stake is False
        assert por_casa[("BetPlay", 185.5)].key == MarketKey.game()
        assert por_casa[("BetPlay", 185.5)].side is Side.OVER

        # Y el seguimiento se reconstruye entero desde lo guardado.
        state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
        seguimientos = {(t.sportsbook, t.line): t
                        for t in segunda.manual_bet_tracking_state(state)}
        assert seguimientos[("BetPlay", 40.5)].scope_points == 32
        assert seguimientos[("BetPlay", 40.5)].margin == pytest.approx(8.5)
        assert seguimientos[("BetPlay", 40.5)].points_to_cross == 9
        assert seguimientos[("Stake", 42.5)].margin == pytest.approx(10.5)
        assert seguimientos[("BetPlay", 185.5)].scope_points == 164
    finally:
        segunda.db.close()


def test_el_resultado_liquidado_tambien_persiste(tmp_path):
    ruta = str(tmp_path / "liquidadas.db")

    primera = AppController(db_path=ruta, capture=NullCapture())
    primera.settings.log_to_file = False
    apuesta = primera.add_manual_bet(sportsbook="Stake", event="",
                                     key=MarketKey.quarter(2), side=Side.UNDER,
                                     line=48.5, odds=1.85, stake=10_000)
    primera.settle_manual_bet(apuesta.bet_id, ManualBetStatus.WON)
    primera.db.close()

    segunda = AppController(db_path=ruta, capture=NullCapture())
    segunda.settings.log_to_file = False
    try:
        recuperada = segunda.list_manual_bets()[0]
        assert recuperada.status is ManualBetStatus.WON
        assert recuperada.settled_at is not None
        assert recuperada.profit == pytest.approx(8_500)
        assert segunda.manual_bet_summary().net_profit == pytest.approx(8_500)
    finally:
        segunda.db.close()


def test_el_seguimiento_no_se_guarda_en_la_base(db):
    """Datos derivados fuera de la base: se recalculan, no se duplican."""
    columnas = {str(fila[1]) for fila in db.query("PRAGMA table_info(manual_bets)")}
    derivados = {"margin", "projection", "points_to_cross", "tolerable_points",
                 "scope_points", "status_tracking", "required_pace"}
    assert columnas & derivados == set(), (
        "el seguimiento es derivado: guardarlo crearia dos verdades")
    # Lo que si se guarda es lo observado y lo que decidio el usuario.
    assert {"sportsbook", "market_type", "quarter", "half", "side", "line",
            "odds", "stake", "status"} <= columnas


# ---------------------------------------------------------------------------
# Las tres tablas conviven
# ---------------------------------------------------------------------------
def test_conviven_manual_bets_browser_manual_bets_y_bets(db):
    tablas = {fila["name"] for fila in
              db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"manual_bets", "browser_manual_bets", "bets"} <= tablas


def test_el_libro_manual_no_toca_la_tabla_de_apuestas_fijadas(db):
    from visorunder.domain.bet import LockedBet
    from visorunder.storage.repositories import BetRepository

    bets = BetRepository(db)
    fijada = LockedBet(sportsbook="BetPlay", event="A vs B",
                       key=MarketKey.quarter(4), side=Side.UNDER,
                       line=44.5, odds=1.90)
    bet_id = bets.save(fijada)

    manual = ManualBetRepository(db)
    manual.save(ManualBet(sportsbook="Stake", event="A vs B",
                          key=MarketKey.quarter(4), side=Side.UNDER,
                          line=42.5, odds=1.75))

    assert len(db.query("SELECT id FROM bets")) == 1
    assert len(db.query("SELECT id FROM manual_bets")) == 1
    assert bets.list_for_session(fijada.session_id or 0) is not None
    assert db.query_one("SELECT id FROM bets WHERE id = ?", (bet_id,)) is not None


# ---------------------------------------------------------------------------
# Migraciones: base limpia, base antigua y base con registros
# ---------------------------------------------------------------------------
def test_base_limpia_llega_a_la_version_actual(tmp_path):
    db = Database(str(tmp_path / "limpia.db"))
    try:
        assert db.version == SCHEMA_VERSION
        db.migrate()                      # idempotente
        assert db.version == SCHEMA_VERSION
        manual = ManualBetRepository(db)
        guardada = manual.save(ManualBet(sportsbook="Stake", event="",
                                         key=MarketKey.game(), side=Side.UNDER,
                                         line=185.5, odds=1.9))
        assert guardada.bet_id is not None
    finally:
        db.close()


def test_una_base_con_el_manual_bets_antiguo_se_migra_sin_perder_enlaces(tmp_path):
    """La estructura antigua del Browser Bridge se conserva, no se borra."""
    from visorunder.storage.database import (
        _migration_001, _migration_002, _migration_003,
    )

    ruta = tmp_path / "antigua.db"
    cx = sqlite3.connect(ruta)
    _migration_001(cx)
    _migration_002(cx)
    _migration_003(cx)
    # Tal y como era antes: manual_bets solo enlazaba bet_id con el evento.
    cx.execute(
        "CREATE TABLE manual_bets (bet_id INTEGER PRIMARY KEY "
        "REFERENCES bets(id) ON DELETE CASCADE, browser_event_id TEXT)")
    cx.execute(
        "INSERT INTO bets (session_id, sportsbook, event, market_type, quarter, "
        "side, line, odds, placed_at, status) "
        "VALUES (NULL, 'BetPlay', 'A vs B', 'QUARTER_TOTAL', 4, 'UNDER', 44.5, 1.9, 1000.0, 'OPEN')")
    cx.execute("INSERT INTO manual_bets (bet_id, browser_event_id) VALUES (1, '9876543')")
    cx.execute("PRAGMA user_version = 3")
    cx.commit()
    cx.close()

    db = Database(ruta)
    try:
        assert db.version == SCHEMA_VERSION
        # El enlace antiguo se conserva en su tabla nueva.
        enlace = db.query_one("SELECT * FROM browser_manual_bets WHERE bet_id = 1")
        assert enlace is not None
        assert enlace["browser_event_id"] == "9876543"
        # La apuesta original sigue ahi.
        assert db.query_one("SELECT line FROM bets WHERE id = 1")["line"] == 44.5
        # Y manual_bets ya es el libro completo, listo para usarse.
        guardada = ManualBetRepository(db).save(
            ManualBet(sportsbook="Stake", event="A vs B", key=MarketKey.quarter(4),
                      side=Side.UNDER, line=42.5, odds=1.75, stake=10_000))
        assert guardada.bet_id is not None
    finally:
        db.close()


def test_una_base_con_apuestas_manuales_guardadas_no_pierde_nada(tmp_path):
    """Actualizar sobre registros existentes conserva las apuestas."""
    ruta = str(tmp_path / "conregistros.db")

    db = Database(ruta)
    manual = ManualBetRepository(db)
    manual.save(ManualBet(sportsbook="BetPlay", event="A vs B",
                          key=MarketKey.quarter(4), side=Side.UNDER,
                          line=40.5, odds=1.8, stake=10_000))
    manual.save(ManualBet(sportsbook="Stake", event="A vs B",
                          key=MarketKey.half_market(1), side=Side.OVER,
                          line=90.5, odds=1.95, stake=7_000))
    db.close()

    # Se vuelve a abrir: las migraciones se ejecutan otra vez y no rompen nada.
    otra = Database(ruta)
    try:
        assert otra.version == SCHEMA_VERSION
        apuestas = ManualBetRepository(otra).list_recent()
        assert len(apuestas) == 2
        claves = {(b.sportsbook, b.key, b.side, b.line) for b in apuestas}
        assert ("BetPlay", MarketKey.quarter(4), Side.UNDER, 40.5) in claves
        assert ("Stake", MarketKey.half_market(1), Side.OVER, 90.5) in claves
    finally:
        otra.close()


def test_el_monto_cero_se_guarda_y_se_recupera(db):
    """El monto es opcional: cero significa 'no lo dije', y persiste asi."""
    manual = ManualBetRepository(db)
    guardada = manual.save(ManualBet(sportsbook="Stake", event="",
                                     key=MarketKey.quarter(4), side=Side.UNDER,
                                     line=40.5, odds=1.8))
    recuperada = manual.get(guardada.bet_id)
    assert recuperada.stake == 0.0
    assert recuperada.has_stake is False
    assert recuperada.profit is None

    # Y no ensucia el ROI del resto.
    manual.save(ManualBet(sportsbook="BetPlay", event="", key=MarketKey.game(),
                          side=Side.UNDER, line=185.5, odds=2.0, stake=10_000,
                          status=ManualBetStatus.WON))
    resumen = manual.summary()
    assert resumen.total == 2
    assert resumen.resolved_stake == pytest.approx(10_000)
    assert resumen.net_profit == pytest.approx(10_000)
    assert resumen.roi == pytest.approx(100.0)


def test_el_seguimiento_se_reconstruye_desde_la_base(db):
    """Lo guardado basta para volver a calcular todo el seguimiento."""
    manual = ManualBetRepository(db)
    manual.save(ManualBet(sportsbook="Stake", event="A vs B",
                          key=MarketKey.quarter(4), side=Side.UNDER,
                          line=40.5, odds=1.8))

    from visorunder.calculations.manual_tracking import track_manual_bets

    state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
    seguimiento = track_manual_bets(state, manual.list_recent())[0]
    assert seguimiento.scope_points == 32
    assert seguimiento.margin == pytest.approx(8.5)
    assert seguimiento.tolerable_points == 8
    assert seguimiento.points_to_cross == 9
    assert seguimiento.status is TrackingStatus.AT_RISK
