"""Repositorios: unico punto de acceso a las tablas (requisitos 19, 27 y 28)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..capture.roi import Roi, RoiKind
from ..config.profiles import SportsbookProfile
from ..domain.bet import LockedBet
from ..domain.game_state import GameState, PointsSource
from ..domain.market import MarketKey, MarketLine, MarketSnapshot, MarketType, Side
from .database import Database


class ProfileRepository:
    """Perfiles de casa de apuestas + sus regiones."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def _sportsbook_id(self, name: str) -> Optional[int]:
        if not name:
            return None
        row = self.db.query_one("SELECT id FROM sportsbooks WHERE name = ?", (name,))
        if row:
            return int(row["id"])
        return self.db.insert(
            "INSERT INTO sportsbooks (name, created_at) VALUES (?, ?)", (name, time.time())
        )

    def save(self, profile: SportsbookProfile) -> int:
        profile.updated_at = time.time()
        payload = profile.to_json()
        sportsbook_id = self._sportsbook_id(profile.sportsbook or profile.name)
        existing = self.db.query_one("SELECT id FROM profiles WHERE name = ?", (profile.name,))
        if existing:
            profile_id = int(existing["id"])
            self.db.execute(
                "UPDATE profiles SET sportsbook_id=?, payload=?, screen_width=?, "
                "screen_height=?, dpi_scale=?, updated_at=? WHERE id=?",
                (sportsbook_id, payload, profile.screen.width, profile.screen.height,
                 profile.screen.dpi_scale, profile.updated_at, profile_id),
            )
        else:
            profile_id = self.db.insert(
                "INSERT INTO profiles (name, sportsbook_id, payload, screen_width, "
                "screen_height, dpi_scale, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (profile.name, sportsbook_id, payload, profile.screen.width,
                 profile.screen.height, profile.screen.dpi_scale, profile.updated_at),
            )
        profile.profile_id = profile_id
        self._save_regions(profile_id, profile)
        return profile_id

    def _save_regions(self, profile_id: int, profile: SportsbookProfile) -> None:
        self.db.execute("DELETE FROM screen_regions WHERE profile_id = ?", (profile_id,))
        rows = [
            (profile_id, roi.kind.value, roi.rect.fx, roi.rect.fy, roi.rect.fw, roi.rect.fh,
             1 if roi.enabled else 0, json.dumps(roi.hints.as_dict()))
            for roi in profile.rois.values()
        ]
        if rows:
            self.db.executemany(
                "INSERT INTO screen_regions (profile_id, kind, fx, fy, fw, fh, enabled, hints) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
            )

    def load(self, name: str) -> Optional[SportsbookProfile]:
        row = self.db.query_one("SELECT id, payload FROM profiles WHERE name = ?", (name,))
        if not row:
            return None
        return SportsbookProfile.from_json(row["payload"], int(row["id"]))

    def load_by_id(self, profile_id: int) -> Optional[SportsbookProfile]:
        row = self.db.query_one("SELECT id, payload FROM profiles WHERE id = ?", (profile_id,))
        if not row:
            return None
        return SportsbookProfile.from_json(row["payload"], int(row["id"]))

    def list_names(self) -> List[str]:
        return [r["name"] for r in self.db.query("SELECT name FROM profiles ORDER BY name")]

    def list_all(self) -> List[SportsbookProfile]:
        return [
            SportsbookProfile.from_json(r["payload"], int(r["id"]))
            for r in self.db.query("SELECT id, payload FROM profiles ORDER BY name")
        ]

    def delete(self, name: str) -> None:
        self.db.execute("DELETE FROM profiles WHERE name = ?", (name,))


class SessionRepository:
    """Sesiones de lectura y eventos (partidos)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create_event(self, sportsbook: str, team_a: str, team_b: str,
                     rules_name: str = "FIBA") -> int:
        sportsbook_id = None
        if sportsbook:
            row = self.db.query_one("SELECT id FROM sportsbooks WHERE name = ?", (sportsbook,))
            if row:
                sportsbook_id = int(row["id"])
            else:
                sportsbook_id = self.db.insert(
                    "INSERT INTO sportsbooks (name, created_at) VALUES (?, ?)",
                    (sportsbook, time.time()))
        return self.db.insert(
            "INSERT INTO events (sportsbook_id, team_a, team_b, rules_name, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (sportsbook_id, team_a, team_b, rules_name, time.time()))

    def start(self, event_id: Optional[int], profile_id: Optional[int]) -> int:
        return self.db.insert(
            "INSERT INTO sessions (event_id, profile_id, started_at, status) VALUES (?, ?, ?, ?)",
            (event_id, profile_id, time.time(), "ACTIVE"))

    def finish(self, session_id: int, status: str = "FINISHED") -> None:
        self.db.execute("UPDATE sessions SET ended_at = ?, status = ? WHERE id = ?",
                        (time.time(), status, session_id))

    def update_event_teams(self, event_id: int, team_a: str, team_b: str) -> None:
        self.db.execute("UPDATE events SET team_a = ?, team_b = ? WHERE id = ?",
                        (team_a, team_b, event_id))

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT s.id, s.started_at, s.ended_at, s.status, e.team_a, e.team_b "
            "FROM sessions s LEFT JOIN events e ON e.id = s.event_id "
            "ORDER BY s.started_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]


class HistoryRepository:
    """Historial de lecturas: OCR, marcadores y mercado (requisitos 19 y 22)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def log_observation(self, session_id: Optional[int], roi_kind: str, raw: str,
                        normalized: str, confidence: float, value_text: Optional[str],
                        status: str, reason: str = "", elapsed_ms: float = 0.0) -> int:
        return self.db.insert(
            "INSERT INTO ocr_observations (session_id, ts, roi_kind, raw_text, normalized, "
            "confidence, value_text, status, reason, elapsed_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (session_id, time.time(), roi_kind, raw, normalized, confidence,
             value_text, status, reason, elapsed_ms))

    def save_score_snapshot(self, session_id: Optional[int], state: GameState) -> Optional[int]:
        ps = state.current_period_score()
        return self.db.insert(
            "INSERT INTO score_snapshots (session_id, ts, period, clock_seconds, score_a, "
            "score_b, period_points_a, period_points_b, points_source) VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, time.time(), state.period_value, state.clock_value,
             state.score_a_value, state.score_b_value, ps.points_a, ps.points_b,
             ps.source.value))

    def save_market_snapshot(self, session_id: Optional[int], snapshot: MarketSnapshot,
                             state: Optional[GameState] = None) -> int:
        count = 0
        for line in snapshot.lines:
            self.db.insert(
                "INSERT INTO market_snapshots (session_id, ts, sportsbook, event, market_type, "
                "period, half, line, over_odds, under_odds, suspended, clock_seconds, score_a, "
                "score_b) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (session_id, line.timestamp, line.sportsbook, line.event,
                 line.key.market_type.value, line.key.period, line.key.half, line.line,
                 line.over_odds, line.under_odds, 1 if snapshot.suspended else 0,
                 state.clock_value if state else None,
                 state.score_a_value if state else None,
                 state.score_b_value if state else None))
            count += 1
        return count

    def market_history(self, session_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT ts, market_type, period, line, over_odds, under_odds, clock_seconds, "
            "score_a, score_b FROM market_snapshots WHERE session_id = ? "
            "ORDER BY ts DESC LIMIT ?", (session_id, limit))
        return [dict(r) for r in rows]

    def observations(self, session_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT ts, roi_kind, raw_text, normalized, confidence, value_text, status, reason "
            "FROM ocr_observations WHERE session_id = ? ORDER BY ts DESC LIMIT ?",
            (session_id, limit))
        return [dict(r) for r in rows]

    def score_history(self, session_id: int, limit: int = 500) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT ts, period, clock_seconds, score_a, score_b, period_points_a, "
            "period_points_b FROM score_snapshots WHERE session_id = ? ORDER BY ts DESC LIMIT ?",
            (session_id, limit))
        return [dict(r) for r in rows]

    def first_score_of_period(self, session_id: int, period: int) -> Optional[Dict[str, Any]]:
        """Marcador mas antiguo registrado en un periodo: sirve de baseline."""
        row = self.db.query_one(
            "SELECT ts, score_a, score_b, clock_seconds FROM score_snapshots "
            "WHERE session_id = ? AND period = ? AND score_a IS NOT NULL "
            "ORDER BY ts ASC LIMIT 1", (session_id, period))
        return dict(row) if row else None


class BetRepository:
    """Apuestas fijadas (requisito 28)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, bet: LockedBet) -> int:
        return self.db.insert(
            "INSERT INTO bets (session_id, sportsbook, event, market_type, quarter, half, side, "
            "line, odds, placed_at, score_a_when_locked, score_b_when_locked, clock_when_locked, "
            "period_when_locked, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bet.session_id, bet.sportsbook, bet.event, bet.key.market_type.value,
             bet.key.period, bet.key.half, bet.side.value, bet.line, bet.odds, bet.placed_at,
             bet.score_a_when_locked, bet.score_b_when_locked, bet.clock_when_locked,
             bet.period_when_locked, "OPEN"))

    def close(self, bet_id: int, status: str = "CLOSED") -> None:
        self.db.execute("UPDATE bets SET status = ?, closed_at = ? WHERE id = ?",
                        (status, time.time(), bet_id))

    def list_for_session(self, session_id: int) -> List[LockedBet]:
        rows = self.db.query("SELECT * FROM bets WHERE session_id = ? ORDER BY placed_at", (session_id,))
        return [self._to_bet(r) for r in rows]

    @staticmethod
    def _to_bet(row: Any) -> LockedBet:
        market_type = MarketType(row["market_type"])
        key = MarketKey(market_type, period=row["quarter"], half=row["half"])
        return LockedBet(
            sportsbook=row["sportsbook"], event=row["event"], key=key,
            side=Side(row["side"]), line=float(row["line"]),
            odds=row["odds"], placed_at=float(row["placed_at"]),
            score_a_when_locked=row["score_a_when_locked"],
            score_b_when_locked=row["score_b_when_locked"],
            clock_when_locked=row["clock_when_locked"],
            period_when_locked=row["period_when_locked"],
            session_id=row["session_id"], bet_id=int(row["id"]),
        )
