"""Controlador de la aplicacion: une captura, OCR, calculo y persistencia.

Deliberadamente NO depende de Qt. La ventana llama a estos metodos, de modo
que toda la logica de sesion (fijar apuesta, cambiar de perfil, guardar
historial) se puede probar sin interfaz grafica.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Callable, List, Optional, Tuple

from .calculations import metrics as metrics_mod
from .calculations.metrics import BetMetrics, GeneralMetrics
from .capture.roi_manager import RoiManager
from .capture.screen_capture import ScreenCapture, create_capture
from .config.profiles import ScreenContext, SportsbookProfile
from .config.settings import AppSettings
from .diagnostics.logbus import LogBus
from .domain.bet import LockedBet
from .domain.market import MarketLine, MarketSnapshot, Side
from .domain.rules import rules_from_name
from .ocr.base import EngineNotAvailable, OcrEngine
from .ocr.engine import create_engine
from .pipeline.reader import LiveReader, ReaderSnapshot
from .storage.database import Database
from .storage.repositories import (
    BetRepository,
    HistoryRepository,
    ProfileRepository,
    SessionRepository,
)


@dataclass
class ViewModel:
    """Todo lo que la interfaz necesita para pintar un ciclo."""

    snapshot: Optional[ReaderSnapshot] = None
    general: Optional[GeneralMetrics] = None
    bet_metrics: Optional[BetMetrics] = None
    bet: Optional[LockedBet] = None
    selected_line: Optional[MarketLine] = None
    current_market_line: Optional[MarketLine] = None


class AppController:
    """Estado global de la aplicacion."""

    def __init__(self, db_path: Optional[str] = None, logbus: Optional[LogBus] = None,
                 settings: Optional[AppSettings] = None,
                 capture: Optional[ScreenCapture] = None) -> None:
        from .config.paths import database_path, log_path

        self.settings = settings or AppSettings.load()
        self.log = logbus or LogBus(file_path=log_path() if self.settings.log_to_file else None)
        self.db = Database(db_path or str(database_path()))
        self.profiles = ProfileRepository(self.db)
        self.sessions = SessionRepository(self.db)
        self.history = HistoryRepository(self.db)
        self.bets = BetRepository(self.db)

        self._capture = capture
        self.engine: Optional[OcrEngine] = None
        self.profile: Optional[SportsbookProfile] = None
        self.reader: Optional[LiveReader] = None
        self.session_id: Optional[int] = None
        self.event_id: Optional[int] = None
        self.locked_bet: Optional[LockedBet] = None
        self.selected_line: Optional[MarketLine] = None
        self.selected_side: Side = Side.UNDER
        self.demo_game = None

    # ---------------------------------------------------------------- basico
    @property
    def capture(self) -> ScreenCapture:
        if self._capture is None:
            self._capture = create_capture(self.settings.capture_backend)
            self.log.info(f"Backend de captura: {type(self._capture).__name__}")
        return self._capture

    def ensure_engine(self, name: str = "auto") -> Optional[OcrEngine]:
        if self.engine is not None:
            return self.engine
        try:
            self.engine = create_engine(name)
            self.engine.warmup()
            self.log.info(f"Motor OCR: {self.engine.describe()}")
        except EngineNotAvailable as exc:
            self.engine = None
            self.log.error(str(exc))
        return self.engine

    def screen_context(self) -> ScreenContext:
        monitors = self.capture.monitors()
        monitor = monitors[0] if monitors else None
        if monitor is None:
            return ScreenContext()
        return ScreenContext(width=monitor.width, height=monitor.height)

    def enable_demo(self, game=None) -> SportsbookProfile:
        """Activa el partido simulado: ni captura de pantalla ni OCR reales."""
        from .capture.screen_capture import NullCapture
        from .pipeline.demo import DemoGame, demo_engine, demo_profile

        self.demo_game = game or DemoGame()
        self._capture = NullCapture()
        self.engine = demo_engine(self.demo_game)
        profile = demo_profile()
        existing = self.profiles.load(profile.name)
        if existing is not None:
            profile.profile_id = existing.profile_id
        self.save_profile(profile)
        self.log.info("MODO DEMO activado: partido simulado, no se lee la pantalla")
        return profile

    # -------------------------------------------------------------- perfiles
    def profile_names(self) -> List[str]:
        return self.profiles.list_names()

    def load_profile(self, name: str) -> Optional[SportsbookProfile]:
        profile = self.profiles.load(name)
        if profile is not None:
            self.profile = profile
            self.settings.last_profile = name
        return profile

    def save_profile(self, profile: SportsbookProfile) -> int:
        profile_id = self.profiles.save(profile)
        self.profile = profile
        self.settings.last_profile = profile.name
        self.log.info(f"Perfil guardado: {profile.name}")
        return profile_id

    def new_profile(self, name: str = "Nuevo perfil") -> SportsbookProfile:
        monitors = self.capture.monitors()
        frame = monitors[0] if monitors else None
        profile = SportsbookProfile(name=name)
        if frame is not None:
            profile.frame = frame
            profile.screen = ScreenContext(width=frame.width, height=frame.height)
        return profile

    # -------------------------------------------------------------- sesiones
    def start_session(self, profile: Optional[SportsbookProfile] = None) -> Optional[LiveReader]:
        """Crea el lector y arranca la lectura en vivo."""
        profile = profile or self.profile
        if profile is None:
            self.log.error("No hay perfil seleccionado")
            return None
        missing = profile.missing_required()
        if missing:
            names = ", ".join(k.display_name for k in missing)
            self.log.error(f"Faltan regiones imprescindibles: {names}")
            return None
        engine = self.ensure_engine(profile.engine)
        if engine is None:
            return None

        rules = rules_from_name(profile.rules_name)
        manager = RoiManager(profile, self.capture, screen=self.screen_context())
        manager.learn_anchor()

        self.event_id = self.sessions.create_event(profile.sportsbook, "", "", rules.name)
        self.session_id = self.sessions.start(self.event_id, profile.profile_id)

        self.reader = LiveReader(
            manager, engine, rules=rules, logbus=self.log, history=self.history,
            session_id=self.session_id,
            required_confirmations=profile.stabilization_required,
            value_ttl=profile.value_ttl_seconds,
            sportsbook=profile.sportsbook or profile.name,
        )
        self.reader.market_reads_per_second = profile.market_reads_per_second
        self.reader.start(profile.reads_per_second)
        self.profile = profile
        return self.reader

    def pause(self) -> None:
        if self.reader:
            self.reader.pause()

    def resume(self) -> None:
        if self.reader:
            self.reader.resume()

    def toggle_reading(self) -> bool:
        """Devuelve True si queda pausado."""
        if self.reader is None:
            self.start_session()
            return False
        return self.reader.toggle_pause()

    def finish_game(self) -> None:
        """FINALIZAR PARTIDO: cierra la sesion y conserva el historial."""
        if self.reader is not None:
            self.reader.stop()
            self.reader = None
        if self.session_id is not None:
            self.sessions.finish(self.session_id)
            self.log.info(f"Partido finalizado. Sesion {self.session_id} guardada.")
        self.session_id = None
        self.event_id = None
        self.locked_bet = None
        self.selected_line = None

    def shutdown(self) -> None:
        if self.reader is not None:
            self.reader.stop()
        if self.session_id is not None:
            self.sessions.finish(self.session_id, "INTERRUPTED")
        try:
            self.settings.save()
        except OSError:
            pass
        self.db.close()

    # --------------------------------------------------------------- apuesta
    def select_line(self, line: Optional[MarketLine], side: Side = Side.UNDER) -> None:
        self.selected_line = line
        self.selected_side = side

    def lock_bet(self) -> Optional[LockedBet]:
        """FIJAR APUESTA: congela linea y cuota (requisito 7)."""
        line = self.selected_line
        if line is None:
            self.log.warn("No hay linea seleccionada que fijar")
            return None
        state = self.reader.state if self.reader else None
        bet = LockedBet.from_line(
            line, self.selected_side,
            score_a=state.score_a_value if state else None,
            score_b=state.score_b_value if state else None,
            clock_seconds=state.clock_value if state else None,
            period=state.period_value if state else None,
            session_id=self.session_id,
        )
        if self.session_id is not None:
            bet = replace(bet, bet_id=self.bets.save(bet))
        self.locked_bet = bet
        self.log.info(f"APUESTA FIJADA: {bet.describe_full()}")
        return bet

    def unlock_bet(self) -> None:
        if self.locked_bet is not None and self.locked_bet.bet_id is not None:
            self.bets.close(self.locked_bet.bet_id, "RELEASED")
        self.locked_bet = None
        self.log.info("Apuesta liberada")

    def set_period_baseline(self, period: int, score_a: int, score_b: int) -> None:
        if self.reader is None:
            return
        self.reader.state.tracker.set_manual_baseline(period, score_a, score_b)
        self.log.info(f"Marcador inicial del periodo {period}: {score_a}-{score_b}",
                      region="PERIOD")

    # --------------------------------------------------------------- lectura
    def build_view_model(self, snapshot: Optional[ReaderSnapshot]) -> ViewModel:
        """Traduce un ciclo de lectura en datos listos para pintar."""
        if snapshot is None:
            return ViewModel()
        state = snapshot.state
        general = metrics_mod.compute_general_metrics(state)

        bet = self.locked_bet
        bet_metrics: Optional[BetMetrics] = None
        if bet is not None:
            bet_metrics = metrics_mod.compute_metrics_for_bet(state, bet)
        elif self.selected_line is not None:
            line = self.selected_line
            odds = line.under_odds if self.selected_side is Side.UNDER else line.over_odds
            bet_metrics = metrics_mod.compute_bet_metrics(
                state, line.key, line.line, odds, self.selected_side)

        current_line = None
        if snapshot.market is not None and bet is not None:
            current_line = snapshot.market.find(bet.line)
            if current_line is None and snapshot.market.lines:
                # La casa movio la linea: se muestra la mas cercana como referencia.
                current_line = min(snapshot.market.sorted_lines(),
                                   key=lambda ln: abs(ln.line - bet.line))

        return ViewModel(
            snapshot=snapshot, general=general, bet_metrics=bet_metrics, bet=bet,
            selected_line=self.selected_line, current_market_line=current_line,
        )
