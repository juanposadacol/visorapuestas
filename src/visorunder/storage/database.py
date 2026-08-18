"""Base de datos SQLite local (requisito 27).

Inicializacion limpia con MIGRACIONES numeradas: la version del esquema se
guarda en la propia base, asi que actualizar la aplicacion no obliga a borrar
el historial.

La conexion es unica y protegida por un cerrojo, porque el hilo de lectura
escribe observaciones mientras la interfaz consulta.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence

SCHEMA_VERSION = 2


def _migration_001(cx: sqlite3.Connection) -> None:
    cx.executescript(
        """
        CREATE TABLE IF NOT EXISTS sportsbooks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            created_at  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profiles (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL UNIQUE,
            sportsbook_id  INTEGER REFERENCES sportsbooks(id) ON DELETE SET NULL,
            payload        TEXT NOT NULL,
            screen_width   INTEGER,
            screen_height  INTEGER,
            dpi_scale      REAL,
            updated_at     REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS screen_regions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            kind        TEXT NOT NULL,
            fx          REAL NOT NULL,
            fy          REAL NOT NULL,
            fw          REAL NOT NULL,
            fh          REAL NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1,
            hints       TEXT NOT NULL DEFAULT '{}',
            UNIQUE(profile_id, kind)
        );

        CREATE TABLE IF NOT EXISTS events (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            sportsbook_id  INTEGER REFERENCES sportsbooks(id) ON DELETE SET NULL,
            team_a         TEXT NOT NULL DEFAULT '',
            team_b         TEXT NOT NULL DEFAULT '',
            rules_name     TEXT NOT NULL DEFAULT 'FIBA',
            created_at     REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER REFERENCES events(id) ON DELETE CASCADE,
            profile_id  INTEGER REFERENCES profiles(id) ON DELETE SET NULL,
            started_at  REAL NOT NULL,
            ended_at    REAL,
            status      TEXT NOT NULL DEFAULT 'ACTIVE',
            notes       TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS ocr_observations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
            ts           REAL NOT NULL,
            roi_kind     TEXT NOT NULL,
            raw_text     TEXT NOT NULL DEFAULT '',
            normalized   TEXT NOT NULL DEFAULT '',
            confidence   REAL NOT NULL DEFAULT 0,
            value_text   TEXT,
            status       TEXT NOT NULL DEFAULT 'RAW',
            reason       TEXT NOT NULL DEFAULT '',
            elapsed_ms   REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS score_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
            ts              REAL NOT NULL,
            period          INTEGER,
            clock_seconds   INTEGER,
            score_a         INTEGER,
            score_b         INTEGER,
            period_points_a INTEGER,
            period_points_b INTEGER,
            points_source   TEXT NOT NULL DEFAULT 'UNKNOWN'
        );

        CREATE TABLE IF NOT EXISTS market_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
            ts            REAL NOT NULL,
            sportsbook    TEXT NOT NULL DEFAULT '',
            event         TEXT NOT NULL DEFAULT '',
            market_type   TEXT NOT NULL,
            period        INTEGER,
            half          INTEGER,
            line          REAL NOT NULL,
            over_odds     REAL,
            under_odds    REAL,
            suspended     INTEGER NOT NULL DEFAULT 0,
            clock_seconds INTEGER,
            score_a       INTEGER,
            score_b       INTEGER
        );

        CREATE TABLE IF NOT EXISTS bets (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
            sportsbook          TEXT NOT NULL DEFAULT '',
            event               TEXT NOT NULL DEFAULT '',
            market_type         TEXT NOT NULL,
            quarter             INTEGER,
            half                INTEGER,
            side                TEXT NOT NULL DEFAULT 'UNDER',
            line                REAL NOT NULL,
            odds                REAL,
            placed_at           REAL NOT NULL,
            score_a_when_locked INTEGER,
            score_b_when_locked INTEGER,
            clock_when_locked   INTEGER,
            period_when_locked  INTEGER,
            status              TEXT NOT NULL DEFAULT 'OPEN',
            closed_at           REAL
        );

        CREATE INDEX IF NOT EXISTS ix_obs_session_ts ON ocr_observations(session_id, ts);
        CREATE INDEX IF NOT EXISTS ix_score_session_ts ON score_snapshots(session_id, ts);
        CREATE INDEX IF NOT EXISTS ix_market_session_ts ON market_snapshots(session_id, ts);
        CREATE INDEX IF NOT EXISTS ix_bets_session ON bets(session_id);
        """
    )


def _migration_002(cx: sqlite3.Connection) -> None:
    """Guarda en la sesion los criterios de entrada con los que se trabajo.

    Se guarda la CONFIGURACION, no las evaluaciones. Los margenes y las
    senales son datos derivados: con el marcador, el reloj, las lineas, las
    cuotas y estos parametros se pueden recalcular exactamente igual mas
    adelante, asi que duplicarlos en la base solo crearia dos versiones de la
    verdad que podrian discrepar.
    """
    cx.executescript(
        """
        ALTER TABLE sessions ADD COLUMN entry_criteria TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE sessions ADD COLUMN reference_pace REAL;
        ALTER TABLE sessions ADD COLUMN target_under_odds REAL;
        """
    )


MIGRATIONS: List[Callable[[sqlite3.Connection], None]] = [_migration_001, _migration_002]


class Database:
    """Envoltorio fino sobre sqlite3 con migraciones y acceso seguro entre hilos."""

    def __init__(self, path: Any = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cx = sqlite3.connect(self.path, check_same_thread=False)
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._cx.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    # ------------------------------------------------------------ migraciones
    @property
    def version(self) -> int:
        row = self._cx.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def migrate(self) -> int:
        with self._lock:
            current = self.version
            for index, migration in enumerate(MIGRATIONS, start=1):
                if index > current:
                    migration(self._cx)
                    self._cx.execute(f"PRAGMA user_version = {index}")
            self._cx.commit()
            return self.version

    # ---------------------------------------------------------------- acceso
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._cx.execute(sql, params)
            self._cx.commit()
            return cur

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> None:
        with self._lock:
            self._cx.executemany(sql, seq)
            self._cx.commit()

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return list(self._cx.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, sql: str, params: Sequence[Any] = ()) -> int:
        return int(self.execute(sql, params).lastrowid)

    def close(self) -> None:
        with self._lock:
            self._cx.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
