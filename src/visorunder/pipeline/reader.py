"""Ciclo de lectura en vivo (requisitos 4, 5, 9, 20, 21, 32).

Un ciclo (`tick`) hace exactamente esto:

    capturar ROIs -> preprocesar -> OCR -> parsear -> validar -> estabilizar
                  -> actualizar el estado del partido -> registrar historial

El ciclo es SINCRONO y aislado, por eso se puede probar sin interfaz ni
pantalla. `LiveReader.start()` simplemente lo repite en un hilo al ritmo
configurado (2-4 lecturas por segundo).

Nada de lo que sale de aqui es una suposicion: si un dato no se confirma,
el estado lo refleja como desconocido y la interfaz muestra "--".
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..calculations import metrics as metrics_mod
from ..capture.roi import OcrHints, RoiKind
from ..capture.roi_manager import RoiFrame, RoiManager
from ..diagnostics.logbus import LogBus
from ..domain.game_state import GamePhase, GameState, PointsSource
from ..domain.market import MarketKey, MarketSnapshot
from ..domain.rules import FIBA, GameRules
from ..domain.values import Observed, ValueStatus
from ..ocr import preprocessing
from ..ocr.base import OcrEngine, OcrResult
from ..ocr.stabilization import (
    Stabilizer,
    clock_fast_path,
    clock_validator,
    period_validator,
    score_validator,
)
from ..parsers import market_parser
from ..parsers.base import ParseResult
from ..parsers.clock_parser import parse_clock
from ..parsers.odds_parser import parse_odds
from ..parsers.quarter_parser import GAME_OVER, HALFTIME, parse_period
from ..parsers.score_parser import parse_breakdown, parse_score, parse_score_pair
from .market_tracker import MarketTracker


@dataclass
class ReaderSnapshot:
    """Fotografia completa de un ciclo, lista para pintar en la interfaz."""

    state: GameState
    market: Optional[MarketSnapshot] = None
    market_raw: Optional[MarketSnapshot] = None
    market_key: Optional[MarketKey] = None
    cycle_ms: float = 0.0
    ocr_ms: float = 0.0
    reads: int = 0
    errors: List[str] = field(default_factory=list)
    needs_period_baseline: bool = False
    field_status: Dict[str, str] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class LiveReader:
    """Motor de lectura. No depende de Qt: se puede usar y probar sin interfaz."""

    def __init__(self, roi_manager: RoiManager, engine: OcrEngine, *,
                 rules: GameRules = FIBA, logbus: Optional[LogBus] = None,
                 history=None, session_id: Optional[int] = None,
                 required_confirmations: int = 3, value_ttl: float = 3.0,
                 sportsbook: str = "", event_name: str = "") -> None:
        self.roi_manager = roi_manager
        self.engine = engine
        self.rules = rules
        self.log = logbus or LogBus()
        self.history = history
        self.session_id = session_id
        self.sportsbook = sportsbook
        self.event_name = event_name

        self.state = GameState(rules=rules)
        self.market_tracker = MarketTracker(required=max(2, required_confirmations - 1))

        req = max(1, int(required_confirmations))
        self.clock = Stabilizer[int](
            "CLOCK", required=max(2, req - 1), ttl=value_ttl,
            validator=clock_validator(self._current_period_seconds),
            fast_path=clock_fast_path())
        self.period = Stabilizer[int](
            "PERIOD", required=req, ttl=value_ttl * 4,
            validator=period_validator(rules.regulation_quarters))
        self.score_a = Stabilizer[int]("SCORE_A", required=req, ttl=value_ttl * 3,
                                       validator=score_validator())
        self.score_b = Stabilizer[int]("SCORE_B", required=req, ttl=value_ttl * 3,
                                       validator=score_validator())
        self.team_a = Stabilizer[str]("TEAM_A", required=req, ttl=3600)
        self.team_b = Stabilizer[str]("TEAM_B", required=req, ttl=3600)
        self.market_label = Stabilizer[MarketKey]("MARKET_LABEL", required=req, ttl=value_ttl * 4)

        self._previous_period: Optional[int] = None
        self._last_score_persist = 0.0
        self._last_market_signature: Optional[tuple] = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.on_update: Optional[Callable[[ReaderSnapshot], None]] = None
        self.reads_per_second = 3.0
        self.last_snapshot: Optional[ReaderSnapshot] = None

    # ------------------------------------------------------------- utilidades
    def _current_period_seconds(self) -> Optional[int]:
        period = self.period.confirmed.usable_value()
        return self.rules.period_seconds(period) if period else self.rules.quarter_seconds

    def _recognize(self, frame: RoiFrame, hints: Optional[OcrHints]) -> OcrResult:
        image = preprocessing.prepare(frame.image, hints)
        return self.engine.recognize(image, hints)

    def _hints_for(self, kind: RoiKind) -> OcrHints:
        roi = self.roi_manager.profile.get_roi(kind)
        hints = roi.hints if roi else OcrHints.for_kind(kind)
        if not hints.roi_kind:
            hints.roi_kind = kind.value
        return hints

    def _log_reading(self, kind: RoiKind, result: OcrResult, parsed: ParseResult,
                     stabilizer: Optional[Stabilizer]) -> None:
        if stabilizer is not None:
            observed = stabilizer.confirmed
            status = observed.status.value
            value = "" if observed.value is None else str(observed.value)
            if stabilizer.pending is not None:
                status = f"RAW {stabilizer.progress}"
        else:
            status = "RAW"
            value = "" if parsed.value is None else str(parsed.value)
        reason = parsed.reason or (stabilizer.stats.last_reason if stabilizer else "")
        self.log.reading(region=kind.value, raw=result.text, normalized=parsed.normalized,
                         confidence=result.confidence, value=value, status=status,
                         reason=reason, elapsed_ms=result.elapsed_ms)
        if self.history is not None:
            self.history.log_observation(
                self.session_id, kind.value, result.text, parsed.normalized,
                result.confidence, value or None, status, reason, result.elapsed_ms)

    # ------------------------------------------------------------------ ciclo
    def tick(self, now: Optional[float] = None) -> ReaderSnapshot:
        """Ejecuta un ciclo completo de lectura."""
        start = time.perf_counter()
        now = now if now is not None else time.time()
        errors: List[str] = []
        ocr_ms = 0.0
        reads = 0

        frames = self.roi_manager.grab_all()
        for kind, frame in frames.items():
            if not frame.ok:
                errors.append(f"{kind.value}: {frame.error}")

        # --- reloj -------------------------------------------------------
        frame = frames.get(RoiKind.CLOCK)
        if frame and frame.ok:
            result = self._recognize(frame, self._hints_for(RoiKind.CLOCK))
            ocr_ms += result.elapsed_ms
            reads += 1
            parsed = parse_clock(result.text,
                                 max_period_seconds=self._current_period_seconds() or 720,
                                 confidence=result.confidence)
            self.clock.submit(parsed, now)
            self._log_reading(RoiKind.CLOCK, result, parsed, self.clock)

        # --- cuarto ------------------------------------------------------
        frame = frames.get(RoiKind.PERIOD)
        if frame and frame.ok:
            result = self._recognize(frame, self._hints_for(RoiKind.PERIOD))
            ocr_ms += result.elapsed_ms
            reads += 1
            parsed = parse_period(result.text,
                                  regulation_quarters=self.rules.regulation_quarters,
                                  confidence=result.confidence)
            self.period.submit(parsed, now)
            self._log_reading(RoiKind.PERIOD, result, parsed, self.period)
            if parsed.normalized == HALFTIME:
                self.state.phase = GamePhase.HALFTIME
            elif parsed.normalized == GAME_OVER:
                self.state.phase = GamePhase.GAME_OVER

        # --- marcador ----------------------------------------------------
        frame = frames.get(RoiKind.SCORE_PAIR)
        if frame and frame.ok:
            result = self._recognize(frame, self._hints_for(RoiKind.SCORE_PAIR))
            ocr_ms += result.elapsed_ms
            reads += 1
            parsed = parse_score_pair(result.text, confidence=result.confidence)
            if parsed.value is not None:
                a, b = parsed.value
                self.score_a.submit(ParseResult(value=a, raw=parsed.raw, normalized=str(a),
                                                confidence=parsed.confidence), now)
                self.score_b.submit(ParseResult(value=b, raw=parsed.raw, normalized=str(b),
                                                confidence=parsed.confidence), now)
            else:
                self.score_a.submit(ParseResult(value=None, raw=parsed.raw,
                                                reason=parsed.reason), now)
            self._log_reading(RoiKind.SCORE_PAIR, result, parsed, None)
        else:
            for kind, stabilizer in ((RoiKind.SCORE_A, self.score_a),
                                     (RoiKind.SCORE_B, self.score_b)):
                frame = frames.get(kind)
                if not (frame and frame.ok):
                    continue
                result = self._recognize(frame, self._hints_for(kind))
                ocr_ms += result.elapsed_ms
                reads += 1
                parsed = parse_score(result.text, confidence=result.confidence)
                stabilizer.submit(parsed, now)
                self._log_reading(kind, result, parsed, stabilizer)

        # --- nombres de equipo (opcional) --------------------------------
        for kind, stabilizer in ((RoiKind.TEAM_A, self.team_a), (RoiKind.TEAM_B, self.team_b)):
            frame = frames.get(kind)
            if not (frame and frame.ok):
                continue
            result = self._recognize(frame, self._hints_for(kind))
            ocr_ms += result.elapsed_ms
            reads += 1
            text = (result.text or "").strip()
            parsed = ParseResult(value=text or None, raw=result.text, normalized=text,
                                 confidence=result.confidence,
                                 reason="" if text else "sin texto")
            stabilizer.submit(parsed, now)
            self._log_reading(kind, result, parsed, stabilizer)

        # --- desglose por cuartos (opcional, maxima prioridad) ------------
        self._read_breakdown(frames, now)

        # --- estado del partido ------------------------------------------
        self._sync_state(now)

        # --- mercado ------------------------------------------------------
        market_raw = self._read_market(frames, now)
        confirmed_market = self.market_tracker.current(now)

        snapshot = ReaderSnapshot(
            state=self.state,
            market=confirmed_market,
            market_raw=market_raw,
            market_key=confirmed_market.key if confirmed_market else None,
            cycle_ms=(time.perf_counter() - start) * 1000.0,
            ocr_ms=ocr_ms,
            reads=reads,
            errors=errors,
            needs_period_baseline=self._needs_baseline(),
            field_status=self._field_status(),
            ts=now,
        )
        self._persist(snapshot, now)
        self.last_snapshot = snapshot
        return snapshot

    # ------------------------------------------------------------ submodulos
    def _read_breakdown(self, frames: Dict[RoiKind, RoiFrame], now: float) -> None:
        frame_a = frames.get(RoiKind.BREAKDOWN_A)
        frame_b = frames.get(RoiKind.BREAKDOWN_B)
        if not (frame_a and frame_a.ok and frame_b and frame_b.ok):
            return
        result_a = self._recognize(frame_a, self._hints_for(RoiKind.BREAKDOWN_A))
        result_b = self._recognize(frame_b, self._hints_for(RoiKind.BREAKDOWN_B))
        parsed_a = parse_breakdown(result_a.text, expected_periods=self.rules.regulation_quarters,
                                   confidence=result_a.confidence)
        parsed_b = parse_breakdown(result_b.text, expected_periods=self.rules.regulation_quarters,
                                   confidence=result_b.confidence)
        self._log_reading(RoiKind.BREAKDOWN_A, result_a, parsed_a, None)
        self._log_reading(RoiKind.BREAKDOWN_B, result_b, parsed_b, None)
        if not (parsed_a.ok and parsed_b.ok):
            return
        for index, (pa, pb) in enumerate(zip(parsed_a.value, parsed_b.value), start=1):
            self.state.tracker.set_breakdown(index, pa, pb)

    def _read_market(self, frames: Dict[RoiKind, RoiFrame], now: float) -> Optional[MarketSnapshot]:
        # Etiqueta del mercado: define a QUE cuarto pertenecen las lineas.
        frame = frames.get(RoiKind.MARKET_LABEL)
        if frame and frame.ok:
            result = self._recognize(frame, self._hints_for(RoiKind.MARKET_LABEL))
            parsed = market_parser.parse_market_label(result.text, confidence=result.confidence)
            self.market_label.submit(parsed, now)
            self._log_reading(RoiKind.MARKET_LABEL, result, parsed, self.market_label)

        key = self.market_label.current(now).usable_value()

        block = frames.get(RoiKind.MARKET_BLOCK)
        if block and block.ok:
            result = self._recognize(block, self._hints_for(RoiKind.MARKET_BLOCK))
            snapshot = market_parser.parse_lines_block(
                result.text, sportsbook=self.sportsbook, event=self.event_name,
                key=key, confidence=result.confidence)
            self.log.reading(region=RoiKind.MARKET_BLOCK.value, raw=result.text,
                             normalized=f"{len(snapshot.lines)} lineas",
                             confidence=result.confidence,
                             value=", ".join(f"{ln.line:g}" for ln in snapshot.lines),
                             status="RAW", reason="suspendido" if snapshot.suspended else "",
                             elapsed_ms=result.elapsed_ms)
            self.market_tracker.submit(snapshot, now)
            return snapshot

        # Modo por columnas: lineas / cuotas OVER / cuotas UNDER en ROIs aparte.
        lines_frame = frames.get(RoiKind.LINES)
        if lines_frame and lines_frame.ok:
            snapshot = self._read_market_columns(frames, key)
            if snapshot is not None:
                self.market_tracker.submit(snapshot, now)
            return snapshot
        return None

    def _read_market_columns(self, frames: Dict[RoiKind, RoiFrame],
                             key: Optional[MarketKey]) -> Optional[MarketSnapshot]:
        def read_column(kind: RoiKind) -> List[str]:
            frame = frames.get(kind)
            if not (frame and frame.ok):
                return []
            result = self._recognize(frame, self._hints_for(kind))
            self.log.reading(region=kind.value, raw=result.text, normalized="",
                             confidence=result.confidence, value="", status="RAW",
                             elapsed_ms=result.elapsed_ms)
            return [ln for ln in result.text.splitlines() if ln.strip()]

        line_texts = read_column(RoiKind.LINES)
        over_texts = read_column(RoiKind.OVER_ODDS)
        under_texts = read_column(RoiKind.UNDER_ODDS)
        if not line_texts:
            return None

        text_rows = []
        for index, line_text in enumerate(line_texts):
            over = over_texts[index] if index < len(over_texts) else ""
            under = under_texts[index] if index < len(under_texts) else ""
            text_rows.append(f"{line_text} OVER {over} UNDER {under}")
        return market_parser.parse_lines_block(
            "\n".join(text_rows), sportsbook=self.sportsbook, event=self.event_name, key=key)

    def _sync_state(self, now: float) -> None:
        """Vuelca los valores confirmados al estado del partido."""
        self.state.clock_seconds = self.clock.current(now)
        self.state.score_a = self.score_a.current(now)
        self.state.score_b = self.score_b.current(now)
        self.state.team_a = self.team_a.current(now)
        self.state.team_b = self.team_b.current(now)
        period_obs = self.period.current(now)
        self.state.period = period_obs
        self.state.updated_at = now

        period = period_obs.usable_value()
        if period is not None and period != self._previous_period:
            self._on_period_detected(period, now)

        self._update_phase()

    def _on_period_detected(self, period: int, now: float) -> None:
        """Reacciona a un cambio de periodo SIN inventar el marcador base.

        Requisito 9: el marcador que se ve al detectar un cuarto solo puede
        usarse como base en dos situaciones en las que es un HECHO:

        * hemos presenciado la transicion (veniamos del cuarto anterior);
        * el reloj marca el cuarto recien empezado (10:00 en FIBA).

        Si la aplicacion se abre a mitad del Q3, no se registra base alguna:
        se intenta el historial y, si tampoco, se pregunta al usuario.
        """
        score_a = self.score_a.current(now).usable_value()
        score_b = self.score_b.current(now).usable_value()
        previous = self._previous_period
        clock = self.clock.current(now).usable_value()
        duration = self.rules.period_seconds(period)
        just_started = clock is not None and clock >= duration - 3

        if score_a is None or score_b is None:
            if previous is not None:
                self.log.warn("Cambio de periodo sin marcador confirmado", region="PERIOD")
            self._previous_period = period
            self._try_history_baseline(period)
            return

        if previous is not None:
            # Transicion presenciada: el marcador actual cierra el periodo
            # anterior y abre el nuevo. No hay ninguna suposicion.
            self.state.tracker.on_period_change(previous, period, score_a, score_b)
            self.log.info(f"Cambio de periodo -> {self.rules.label(period)}",
                          region="PERIOD", value=f"{score_a}-{score_b}")
        elif just_started:
            # Primera deteccion pero el cuarto acaba de empezar: es un hecho.
            self.state.tracker.set_baseline(period, score_a, score_b, PointsSource.HISTORY)
            self.log.info(f"{self.rules.label(period)} recien empezado: base {score_a}-{score_b}",
                          region="PERIOD")
        else:
            self.log.warn(
                f"Aplicacion iniciada a mitad del {self.rules.label(period)}: "
                "los puntos del cuarto son desconocidos hasta conocer el marcador inicial",
                region="PERIOD")

        self._previous_period = period
        self._try_history_baseline(period)

    def _try_history_baseline(self, period: int) -> None:
        """Prioridad 2 del requisito 9: recuperar el baseline del historial."""
        if self.history is None or self.session_id is None:
            return
        if self.state.tracker.has_baseline(period):
            return
        row = self.history.first_score_of_period(self.session_id, period)
        if row and row.get("score_a") is not None:
            self.state.tracker.set_baseline(period, row["score_a"], row["score_b"],
                                            PointsSource.HISTORY)
            self.log.info(f"Baseline del {self.rules.label(period)} recuperado del historial",
                          region="PERIOD", value=f"{row['score_a']}-{row['score_b']}")

    def _update_phase(self) -> None:
        if self.state.phase in (GamePhase.HALFTIME, GamePhase.GAME_OVER):
            # Se sale de esos estados en cuanto el reloj vuelve a correr.
            clock = self.state.clock_value
            if clock is None or clock == 0:
                return
        clock = self.state.clock_value
        period = self.state.period_value
        if clock is None or period is None:
            self.state.phase = GamePhase.UNKNOWN
            return
        duration = self.rules.period_seconds(period)
        if clock == 0:
            self.state.phase = (GamePhase.HALFTIME
                                if period == self.rules.halftime_after_period
                                else GamePhase.PERIOD_END)
        elif clock >= duration:
            self.state.phase = GamePhase.PERIOD_START
        else:
            self.state.phase = GamePhase.IN_PLAY

    def _needs_baseline(self) -> bool:
        """True si hay que preguntar al usuario los puntos al empezar el cuarto."""
        period = self.state.period_value
        if period is None:
            return False
        if self.state.tracker.has_baseline(period):
            return False
        return self.state.score_a_value is not None and self.state.score_b_value is not None

    def _field_status(self) -> Dict[str, str]:
        out = {}
        for name, stabilizer in (("clock", self.clock), ("period", self.period),
                                 ("score_a", self.score_a), ("score_b", self.score_b)):
            observed = stabilizer.confirmed
            out[name] = observed.status.value if observed.value is not None else "UNKNOWN"
        return out

    def _persist(self, snapshot: ReaderSnapshot, now: float) -> None:
        if self.history is None or self.session_id is None:
            return
        if now - self._last_score_persist >= 1.0 and self.state.score_a_value is not None:
            self.history.save_score_snapshot(self.session_id, self.state)
            self._last_score_persist = now
        market = snapshot.market
        if market is not None and not market.is_empty:
            from .market_tracker import signature as market_signature
            sig = market_signature(market) + tuple(
                (ln.over_odds, ln.under_odds) for ln in market.sorted_lines())
            if sig != self._last_market_signature:
                self.history.save_market_snapshot(self.session_id, market, self.state)
                self._last_market_signature = sig

    # ------------------------------------------------------------------ hilo
    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def start(self, reads_per_second: Optional[float] = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if reads_per_second:
            self.reads_per_second = reads_per_second
        self._running.set()
        self._paused.clear()
        self._thread = threading.Thread(target=self._loop, name="visorunder-reader", daemon=True)
        self._thread.start()
        self.log.info(f"Lectura iniciada a {self.reads_per_second:g} lecturas/s")

    def pause(self) -> None:
        self._paused.set()
        self.log.info("Lectura pausada")

    def resume(self) -> None:
        self._paused.clear()
        self.log.info("Lectura reanudada")

    def toggle_pause(self) -> bool:
        if self._paused.is_set():
            self.resume()
        else:
            self.pause()
        return self._paused.is_set()

    def stop(self) -> None:
        self._running.clear()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self.log.info("Lectura detenida")

    def _loop(self) -> None:
        while self._running.is_set():
            cycle_start = time.perf_counter()
            if not self._paused.is_set():
                try:
                    snapshot = self.tick()
                    if self.on_update is not None:
                        self.on_update(snapshot)
                except Exception as exc:  # pragma: no cover - el hilo nunca debe morir
                    self.log.error(f"Fallo en el ciclo de lectura: {type(exc).__name__}: {exc}")
            interval = 1.0 / max(0.5, self.reads_per_second)
            elapsed = time.perf_counter() - cycle_start
            time.sleep(max(0.01, interval - elapsed))
