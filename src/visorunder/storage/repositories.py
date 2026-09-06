"""Repositorios: unico punto de acceso a las tablas (requisitos 19, 27 y 28)."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ..capture.roi import RoiKind
from ..config.profiles import SportsbookProfile
from ..domain.bet import LockedBet
from ..domain.game_state import GameState
from ..domain.manual_bet import ManualBet, ManualBetStatus, ManualBetSummary
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

    def exists(self, name: str, *, exclude_profile_id: Optional[int] = None) -> bool:
        """Indica si el nombre ya pertenece a OTRO perfil.

        Es importante distinguir un perfil cargado que se esta actualizando de
        un perfil nuevo. Antes se buscaba solo por nombre y un perfil nuevo con
        nombre repetido podia sobrescribir silenciosamente al anterior.
        """
        if exclude_profile_id is None:
            row = self.db.query_one("SELECT id FROM profiles WHERE name = ?", (name,))
        else:
            row = self.db.query_one(
                "SELECT id FROM profiles WHERE name = ? AND id <> ?",
                (name, exclude_profile_id),
            )
        return row is not None

    def save(self, profile: SportsbookProfile) -> int:
        profile.updated_at = time.time()
        sportsbook_id = self._sportsbook_id(profile.sportsbook or profile.name)

        # La identidad real es profile_id cuando el perfil ya fue guardado.
        # Esto permite renombrarlo sin crear un duplicado y evita que un
        # perfil NUEVO con el mismo nombre destruya al anterior.
        profile_id = profile.profile_id
        stored_by_id = None
        if profile_id is not None:
            stored_by_id = self.db.query_one("SELECT id FROM profiles WHERE id = ?", (profile_id,))

        if stored_by_id is not None:
            if self.exists(profile.name, exclude_profile_id=profile_id):
                raise ValueError(f"Ya existe otro perfil llamado '{profile.name}'.")
            payload = profile.to_json()
            self.db.execute(
                "UPDATE profiles SET name=?, sportsbook_id=?, payload=?, screen_width=?, "
                "screen_height=?, dpi_scale=?, updated_at=? WHERE id=?",
                (profile.name, sportsbook_id, payload, profile.screen.width,
                 profile.screen.height, profile.screen.dpi_scale, profile.updated_at, profile_id),
            )
        else:
            # Un id ajeno/obsoleto no debe convertir una insercion en un
            # UPDATE accidental. Se trata como perfil nuevo.
            profile.profile_id = None
            if self.exists(profile.name):
                raise ValueError(
                    f"Ya existe un perfil llamado '{profile.name}'. "
                    "Usa otro nombre para crear una casa/perfil adicional."
                )
            payload = profile.to_json()
            profile_id = self.db.insert(
                "INSERT INTO profiles (name, sportsbook_id, payload, screen_width, "
                "screen_height, dpi_scale, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (profile.name, sportsbook_id, payload, profile.screen.width,
                 profile.screen.height, profile.screen.dpi_scale, profile.updated_at),
            )

        profile.profile_id = int(profile_id)
        self._save_regions(int(profile_id), profile)
        return int(profile_id)

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

    def start(self, event_id: Optional[int], profile_id: Optional[int],
              criteria=None) -> int:
        """Abre una sesion dejando constancia de los criterios en uso."""
        payload = json.dumps(criteria.as_dict()) if criteria is not None else "{}"
        reference = criteria.reference_pace if criteria is not None else None
        target = criteria.target_under_odds if criteria is not None else None
        return self.db.insert(
            "INSERT INTO sessions (event_id, profile_id, started_at, status, entry_criteria, "
            "reference_pace, target_under_odds) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, profile_id, time.time(), "ACTIVE", payload, reference, target))

    def save_criteria(self, session_id: int, criteria) -> None:
        """Actualiza los criterios de la sesion si se cambian a mitad."""
        self.db.execute(
            "UPDATE sessions SET entry_criteria = ?, reference_pace = ?, "
            "target_under_odds = ? WHERE id = ?",
            (json.dumps(criteria.as_dict()), criteria.reference_pace,
             criteria.target_under_odds, session_id))

    def load_criteria(self, session_id: int):
        """Recupera los criterios con los que se trabajo en una sesion."""
        from ..config.criteria import EntryCriteria

        row = self.db.query_one("SELECT entry_criteria FROM sessions WHERE id = ?", (session_id,))
        if not row or not row["entry_criteria"]:
            return None
        try:
            data = json.loads(row["entry_criteria"])
        except json.JSONDecodeError:
            return None
        return EntryCriteria.from_dict(data) if data else None

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

    def record_market_observation(self, session_id: Optional[int], key: MarketKey,
                                  last_seen_at: float,
                                  last_confirmed_at: Optional[float] = None) -> None:
        """Anota que se miro este mercado, cambiara o no lo que ofrecia."""
        if session_id is None:
            return
        self.db.execute(
            "INSERT INTO market_observations (session_id, market_type, period, half, "
            "first_seen_at, last_seen_at, last_confirmed_at, observations) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(session_id, market_type, COALESCE(period, -1), "
            "COALESCE(half, -1)) DO UPDATE SET "
            "last_seen_at = excluded.last_seen_at, "
            "last_confirmed_at = COALESCE(excluded.last_confirmed_at, last_confirmed_at), "
            "observations = observations + 1",
            (session_id, key.market_type.value, key.period, key.half,
             last_seen_at, last_seen_at, last_confirmed_at))

    def market_observations(self, session_id: int) -> List[Dict[str, Any]]:
        rows = self.db.query(
            "SELECT market_type, period, half, first_seen_at, last_seen_at, "
            "last_confirmed_at, observations FROM market_observations "
            "WHERE session_id = ? ORDER BY last_seen_at DESC", (session_id,))
        return [dict(r) for r in rows]

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

    def save_manual(self, bet: LockedBet, browser_event_id: Optional[str]) -> int:
        with self.db.transaction():
            bet_id = self.save(bet)
            self.db.execute("INSERT INTO browser_manual_bets (bet_id, browser_event_id) VALUES (?, ?)",
                            (bet_id, browser_event_id))
        return bet_id

    def list_manual(self) -> list:
        rows = self.db.query(
            "SELECT b.*, m.browser_event_id FROM bets b JOIN browser_manual_bets m ON m.bet_id=b.id "
            "ORDER BY b.placed_at DESC, b.id DESC")
        return [(self._to_bet(r), r["browser_event_id"], r["status"]) for r in rows]

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


class ManualBetRepository:
    """Registro manual de apuestas, independiente del OCR y de la casa activa."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, bet: ManualBet) -> ManualBet:
        bet_id = self.db.insert(
            "INSERT INTO manual_bets (session_id, sportsbook, event, market_type, quarter, half, "
            "side, line, odds, stake, placed_at, status, settled_at, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bet.session_id, bet.sportsbook.strip(), bet.event.strip(), bet.key.market_type.value,
             bet.key.period, bet.key.half, bet.side.value, bet.line, bet.odds, bet.stake,
             bet.placed_at, bet.status.value, bet.settled_at, bet.notes.strip()),
        )
        return replace(bet, bet_id=bet_id)

    def list_recent(self, limit: int = 100) -> List[ManualBet]:
        rows = self.db.query(
            "SELECT * FROM manual_bets ORDER BY placed_at DESC, id DESC LIMIT ?", (limit,))
        return [self._to_bet(row) for row in rows]

    def get(self, bet_id: int) -> Optional[ManualBet]:
        row = self.db.query_one("SELECT * FROM manual_bets WHERE id = ?", (bet_id,))
        return self._to_bet(row) if row else None

    def settle(self, bet_id: int, status: ManualBetStatus) -> Optional[ManualBet]:
        settled_at = None if status is ManualBetStatus.PENDING else time.time()
        self.db.execute(
            "UPDATE manual_bets SET status = ?, settled_at = ? WHERE id = ?",
            (status.value, settled_at, bet_id),
        )
        return self.get(bet_id)

    def delete(self, bet_id: int) -> None:
        self.db.execute("DELETE FROM manual_bets WHERE id = ?", (bet_id,))

    def summary(self) -> ManualBetSummary:
        rows = self.db.query("SELECT status, odds, stake FROM manual_bets")
        total = len(rows)
        pending = won = lost = void = 0
        total_staked = 0.0
        resolved_stake = 0.0
        net_profit = 0.0

        for row in rows:
            status = ManualBetStatus(row["status"])
            odds = float(row["odds"])
            stake = float(row["stake"])
            total_staked += stake
            if status is ManualBetStatus.PENDING:
                pending += 1
            elif status is ManualBetStatus.WON:
                won += 1
                resolved_stake += stake
                net_profit += stake * (odds - 1.0)
            elif status is ManualBetStatus.LOST:
                lost += 1
                resolved_stake += stake
                net_profit -= stake
            else:
                void += 1

        return ManualBetSummary(
            total=total,
            pending=pending,
            won=won,
            lost=lost,
            void=void,
            total_staked=total_staked,
            resolved_stake=resolved_stake,
            net_profit=net_profit,
        )

    @staticmethod
    def _to_bet(row: Any) -> ManualBet:
        market_type = MarketType(row["market_type"])
        key = MarketKey(market_type, period=row["quarter"], half=row["half"])
        return ManualBet(
            sportsbook=row["sportsbook"], event=row["event"], key=key,
            side=Side(row["side"]), line=float(row["line"]), odds=float(row["odds"]),
            stake=float(row["stake"]), status=ManualBetStatus(row["status"]),
            placed_at=float(row["placed_at"]), settled_at=row["settled_at"],
            notes=row["notes"], session_id=row["session_id"], bet_id=int(row["id"]),
        )
