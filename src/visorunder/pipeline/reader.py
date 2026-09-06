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
from ..config.profiles import resolve_default_market
from ..diagnostics.logbus import LogBus
from ..bridge.source import BrowserSource, MarketUpdateStatus, SourceKind
from ..domain.event_markets import EventMarkets, MarketState
from ..domain.game_state import GamePhase, GameState, PointsSource
from ..domain.market import MarketKey, MarketSnapshot
from ..domain.rules import FIBA, GameRules
from ..domain.time_utils import period_remaining_from_game_elapsed, seconds_to_clock
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
from ..parsers.scoreboard_parser import parse_scoreboard
from .market_tracker import MarketTracker

#: Regiones que solo se capturan cuando toca refrescar el mercado.
_MARKET_ROIS = (RoiKind.MARKET_BLOCK, RoiKind.MARKET_LABEL, RoiKind.LINES,
                RoiKind.OVER_ODDS, RoiKind.UNDER_ODDS)


@dataclass
class ReaderSnapshot:
    """Fotografia completa de un ciclo, lista para pintar en la interfaz."""

    state: GameState
    #: Todos los mercados del evento con su frescura.
    markets: Optional[EventMarkets] = None
    #: Mercado visible ahora mismo (atajo de `markets.visible`).
    market: Optional[MarketSnapshot] = None
    market_raw: Optional[MarketSnapshot] = None
    market_key: Optional[MarketKey] = None
    cycle_ms: float = 0.0
    ocr_ms: float = 0.0
    reads: int = 0
    errors: List[str] = field(default_factory=list)
    needs_period_baseline: bool = False
    #: True si el mercado se identifico leyendo su titulo en pantalla; False si
    #: proviene del mercado por defecto elegido en el perfil.
    market_from_label: bool = False
    #: True mientras se esta cambiando de pestana: el titulo en bruto ya dice
    #: otro mercado pero todavia no esta confirmado, asi que no se atribuye
    #: ninguna linea.
    market_in_transition: bool = False
    #: True mientras la casa ensena un conjunto de lineas distinto al
    #: publicado y todavia se esta confirmando.
    market_under_review: bool = False
    #: Lineas pendientes de confirmacion, para poder mostrarlas como aviso.
    market_pending_lines: tuple = ()
    field_status: Dict[str, str] = field(default_factory=dict)
    #: De donde salio cada dato en este ciclo.
    field_sources: Dict[str, str] = field(default_factory=dict)
    #: Discrepancias DOM/OCR sin resolver en silencio.
    source_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    ts: float = field(default_factory=time.time)
    browser_event_id: Optional[str] = None


class LiveReader:
    """Motor de lectura. No depende de Qt: se puede usar y probar sin interfaz."""

    def __init__(self, roi_manager: RoiManager, engine: OcrEngine, *,
                 rules: GameRules = FIBA, logbus: Optional[LogBus] = None,
                 history=None, session_id: Optional[int] = None,
                 required_confirmations: int = 3, value_ttl: float = 3.0,
                 sportsbook: str = "", event_name: str = "",
                 browser_source: Optional[BrowserSource] = None) -> None:
        self.roi_manager = roi_manager
        self.engine = engine
        self.rules = rules
        self.log = logbus or LogBus()
        self.history = history
        self.session_id = session_id
        self.sportsbook = sportsbook
        self.event_name = event_name
        #: Fuente DOM. Cuando esta viva, manda sobre el OCR para los datos que
        #: aporta, porque viene estructurada de la propia pagina.
        self.browser_source = browser_source
        #: De donde salio cada dato. Lo sabe la capa de adquisicion; el dominio
        #: sigue recibiendo solo estados normalizados.
        self.field_sources: Dict[str, SourceKind] = {}
        #: Discrepancias entre fuentes, para poder verlas en diagnostico en vez
        #: de resolverlas en silencio.
        self.source_conflicts: List[Dict[str, Any]] = []

        self.state = GameState(rules=rules)
        #: Registro de TODOS los mercados observados del evento. La casa los
        #: reparte en pestanas y solo se puede leer la visible; el resto
        #: conserva su ultima lectura con su marca de tiempo.
        self.markets = EventMarkets()
        self._market_required = max(2, required_confirmations - 1)
        #: Un tracker independiente por mercado. Al ser independientes, un
        #: fotograma rezagado de la pestana anterior no puede confirmarse solo
        #: dentro del mercado nuevo: es la salvaguarda contra mezclar lineas.
        self._trackers: Dict[MarketKey, MarketTracker] = {}
        #: Mercado que el usuario fuerza a mano cuando el titulo no se lee.
        self.manual_visible_key: Optional[MarketKey] = None
        #: Ultima clave leida EN BRUTO del titulo (sin estabilizar). Sirve de
        #: compuerta durante los cambios de pestana.
        self._raw_label_key: Optional[MarketKey] = None
        self._in_transition: bool = False

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
        self.market_key_from_ocr: bool = False
        #: Cadencia propia del bloque de lineas, la region mas cara de leer
        #: (necesita deteccion de texto). 0 = leerlo en cada ciclo, que es el
        #: valor por defecto: el mercado es el objeto principal de analisis.
        #: Un valor mayor que 0 lo lee mas despacio para ahorrar CPU.
        self.market_reads_per_second: float = 0.0
        self._last_market_read: float = 0.0
        self._last_score_persist = 0.0
        self._market_signatures: Dict[MarketKey, tuple] = {}
        self._running = threading.Event()
        self._paused = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.on_update: Optional[Callable[[ReaderSnapshot], None]] = None
        self.reads_per_second = 3.0
        self.last_snapshot: Optional[ReaderSnapshot] = None
        #: Identidad del evento cuyos datos consolidamos. BrowserSource limpia
        #: su propia foto al cambiar el hash; el lector tambien debe vaciar su
        #: dominio antes de aplicar un update parcial del evento nuevo.
        self._browser_event_id: Optional[str] = (
            browser_source.event_id if browser_source is not None else None)
        #: Ultimo reloj DOM confirmado. Solo se reutiliza si el mismo evento
        #: sigue enviando un gameState fresco y coherente sin reloj.
        self._held_browser_clock: Optional[int] = None
        self._held_browser_period: Optional[int] = None
        self._held_browser_event_id: Optional[str] = None

    # ------------------------------------------------------------- utilidades
    def tracker_for(self, key: MarketKey) -> MarketTracker:
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = MarketTracker(required=self._market_required)
            self._trackers[key] = tracker
        return tracker

    def set_manual_visible_market(self, key: Optional[MarketKey]) -> None:
        """Fuerza que mercado se considera visible (respaldo del titulo OCR)."""
        self.manual_visible_key = key
        if key is not None:
            self.markets.set_visible(key)

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
        self._reset_if_browser_event_changed()
        errors: List[str] = []
        ocr_ms = 0.0
        reads = 0

        market_due = self._market_is_due(now)
        wanted = [k for k in self.roi_manager.configured_kinds()
                  if market_due or k not in _MARKET_ROIS]
        frames = self.roi_manager.grab_all(wanted)
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
                # La sospecha viaja con cada mitad: si el recorte estaba sucio,
                # ninguno de los dos marcadores se confirma.
                self.score_a.submit(ParseResult(value=a, raw=parsed.raw, normalized=str(a),
                                                confidence=parsed.confidence,
                                                suspicious=parsed.suspicious,
                                                reason=parsed.reason), now)
                self.score_b.submit(ParseResult(value=b, raw=parsed.raw, normalized=str(b),
                                                confidence=parsed.confidence,
                                                suspicious=parsed.suspicious,
                                                reason=parsed.reason), now)
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

        # --- tablero completo con columnas variables (opcional) -----------
        # Va DESPUES de las regiones sueltas: solo rellena lo que ninguna de
        # ellas cubre, asi que un perfil que ya tiene reloj o marcador propios
        # conserva su fuente y esto no le cambia nada.
        ocr_ms += self._read_scoreboard(frames, now)

        # --- estado del partido ------------------------------------------
        self._sync_state(now)
        self._apply_browser_source(now)

        # --- mercado visible ----------------------------------------------
        market_raw = None
        if self._market_is_due(now):
            self._last_market_read = now
            market_raw = self._read_market(frames, now)

        visible_state = self.markets.visible
        confirmed_market = visible_state.snapshot if visible_state else None

        snapshot = ReaderSnapshot(
            browser_event_id=self._browser_event_id,
            state=self.state,
            markets=self.markets,
            market=confirmed_market,
            market_raw=market_raw,
            market_key=self.markets.visible_key,
            cycle_ms=(time.perf_counter() - start) * 1000.0,
            ocr_ms=ocr_ms,
            reads=reads,
            errors=errors,
            needs_period_baseline=self._needs_baseline(),
            market_from_label=self.market_key_from_ocr,
            market_in_transition=self._in_transition,
            market_under_review=bool(visible_state and visible_state.under_review),
            market_pending_lines=visible_state.pending_lines if visible_state else (),
            field_status=self._field_status(),
            field_sources={k: v.value for k, v in self.field_sources.items()},
            source_conflicts=list(self.source_conflicts[-5:]),
            ts=now,
        )
        self._persist(snapshot, now)
        self.last_snapshot = snapshot
        return snapshot

    def _reset_if_browser_event_changed(self) -> None:
        """Inicia una foto vacia antes de leer el nuevo evento del navegador.

        La UI tambien cierra la sesion al detectar el cambio, pero el dominio
        no puede depender de ese siguiente pulso: entre ambos, un paquete solo
        de mercado no debe convivir con nombres, parciales o ritmos antiguos.
        """
        fuente = self.browser_source
        current = fuente.event_id if fuente is not None else None
        if not current:
            return
        if self._browser_event_id is None:
            self._browser_event_id = current
            return
        if current == self._browser_event_id:
            return

        previous = self._browser_event_id
        self._browser_event_id = current
        self.state = GameState(rules=self.rules)
        self.markets = EventMarkets()
        self._trackers.clear()
        self._market_signatures.clear()
        self.field_sources.clear()
        self.source_conflicts.clear()
        for stabilizer in (self.clock, self.period, self.score_a, self.score_b,
                           self.team_a, self.team_b, self.market_label):
            stabilizer.reset()
        self._previous_period = None
        self._clear_held_browser_clock()
        self.manual_visible_key = None
        self._raw_label_key = None
        self._in_transition = False
        self.market_key_from_ocr = False
        self._last_market_read = 0.0
        self.log.info(
            f"Estado local limpiado por cambio de evento: {previous} -> {current}",
            region="BRIDGE")

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

    # ------------------------------------------------ tablero de columnas variables
    def _scoreboard_covers(self, kind: RoiKind) -> bool:
        """True si `kind` tiene su PROPIA region configurada.

        El tablero completo es un respaldo, no un sustituto: si el perfil ya
        define el reloj o el marcador por separado, esos siguen mandando y el
        tablero no los toca. Es la politica que pidio conservarse para no
        romper los perfiles que ya existen.
        """
        if kind is RoiKind.SCORE_PAIR:
            profile = self.roi_manager.profile
            return profile.has(RoiKind.SCORE_PAIR) or (
                profile.has(RoiKind.SCORE_A) and profile.has(RoiKind.SCORE_B))
        return self.roi_manager.profile.has(kind)

    def _read_scoreboard(self, frames: Dict[RoiKind, RoiFrame], now: float) -> float:
        """Lee el tablero completo y rellena lo que no cubra otra region.

        Devuelve los milisegundos de OCR consumidos.

        Ninguna de estas lecturas se aplica directamente al estado: todas
        pasan por los MISMOS estabilizadores que el resto del OCR, asi que una
        lectura suelta no puede mover el marcador ni el cuarto. Y como el DOM
        se aplica despues, BetPlay sigue mandando sobre todo esto.
        """
        frame = frames.get(RoiKind.SCOREBOARD)
        if not (frame and frame.ok):
            return 0.0

        result = self._recognize(frame, self._hints_for(RoiKind.SCOREBOARD))
        parsed = parse_scoreboard(
            result.text,
            regulation_quarters=self.rules.regulation_quarters,
            halftime_after_period=self.rules.halftime_after_period,
            confidence=result.confidence)
        self._log_reading(RoiKind.SCOREBOARD, result, parsed, None)

        lectura = parsed.value
        if lectura is None or parsed.suspicious:
            # Incoherente o ilegible: no se toca nada. El estado bueno anterior
            # se queda como esta y solo envejece por su propio TTL.
            return result.elapsed_ms

        def _submit(stabilizer, value, normalized: str) -> None:
            stabilizer.submit(ParseResult(
                value=value, raw=parsed.raw, normalized=normalized,
                confidence=parsed.confidence), now)

        if lectura.clock_seconds is not None and not self._scoreboard_covers(RoiKind.CLOCK):
            _submit(self.clock, lectura.clock_seconds, seconds_to_clock(lectura.clock_seconds))
        if lectura.period is not None and not self._scoreboard_covers(RoiKind.PERIOD):
            _submit(self.period, lectura.period, f"Q{lectura.period}")
        if lectura.has_scores and not self._scoreboard_covers(RoiKind.SCORE_PAIR):
            _submit(self.score_a, lectura.score_a, str(lectura.score_a))
            _submit(self.score_b, lectura.score_b, str(lectura.score_b))
        if lectura.team_a and not self._scoreboard_covers(RoiKind.TEAM_A):
            _submit(self.team_a, lectura.team_a, lectura.team_a)
        if lectura.team_b and not self._scoreboard_covers(RoiKind.TEAM_B):
            _submit(self.team_b, lectura.team_b, lectura.team_b)

        # Los parciales entran por el MISMO camino que BREAKDOWN_A/B: no hay
        # un segundo sistema de parciales, asi que Q1..Q4, 1H, 2H y PARTIDO
        # siguen calculandose exactamente igual que siempre.
        # El descanso NO se toca: es un acumulado, no un periodo.
        if not (self._scoreboard_covers(RoiKind.BREAKDOWN_A)
                and self._scoreboard_covers(RoiKind.BREAKDOWN_B)):
            for period, puntos_a, puntos_b in lectura.breakdown_pairs():
                self.state.tracker.set_breakdown(period, puntos_a, puntos_b)

        if lectura.phase == HALFTIME:
            self.state.phase = GamePhase.HALFTIME
        elif lectura.phase == GAME_OVER:
            self.state.phase = GamePhase.GAME_OVER

        return result.elapsed_ms

    def _resolve_visible_key(self, now: float) -> Optional[MarketKey]:
        """Decide a QUE mercado pertenece lo que se esta viendo en pantalla.

        Prioridad acordada: automatico cuando es fiable, manual como respaldo,
        y jamas adivinar.

        1. Titulo del mercado leido y confirmado por OCR.
        2. Mercado que el usuario ha fijado a mano como visible.
        3. Mercado por defecto del perfil (eleccion explicita del usuario).

        Si nada de eso resuelve, no se publica ninguna linea: es preferible
        quedarse sin datos a atribuirlos a un mercado equivocado.
        """
        leido = self.market_label.current(now).usable_value()
        self.market_key_from_ocr = leido is not None
        if leido is not None:
            return leido

        if self.manual_visible_key is not None:
            return self.manual_visible_key

        key = resolve_default_market(
            getattr(self.roi_manager.profile, "default_market", "GAME"),
            self.state.period_value)
        if key is None:
            self.log.warn(
                "No se puede atribuir el mercado: falta el titulo, no hay mercado "
                "elegido a mano y el de por defecto depende del cuarto, que aun "
                "no se conoce",
                region=RoiKind.MARKET_BLOCK.value)
        return key

    def _publish(self, key: MarketKey, snapshot: Optional[MarketSnapshot],
                 now: float) -> Optional[MarketSnapshot]:
        """Entrega la lectura al tracker del mercado y actualiza el registro."""
        tracker = self.tracker_for(key)
        tracker.submit(snapshot, now)
        confirmado = tracker.current(now)
        self.markets.observe(
            key, confirmado,
            confirmed=confirmado is not None,
            under_review=tracker.under_review,
            pending_lines=tracker.pending_lines,
            now=now,
        )
        return snapshot

    def _market_is_due(self, now: float) -> bool:
        if self.market_reads_per_second <= 0:
            return True
        return (now - self._last_market_read) >= (1.0 / self.market_reads_per_second)

    def _read_market(self, frames: Dict[RoiKind, RoiFrame], now: float) -> Optional[MarketSnapshot]:
        # Etiqueta del mercado: define a QUE cuarto pertenecen las lineas.
        frame = frames.get(RoiKind.MARKET_LABEL)
        has_label_roi = bool(frame and frame.ok)
        if has_label_roi:
            result = self._recognize(frame, self._hints_for(RoiKind.MARKET_LABEL))
            parsed = market_parser.parse_market_label(result.text, confidence=result.confidence)
            self._raw_label_key = parsed.value
            self.market_label.submit(parsed, now)
            self._log_reading(RoiKind.MARKET_LABEL, result, parsed, self.market_label)

        key = self._resolve_visible_key(now)
        if key is None:
            return None

        # COMPUERTA DE TRANSICION.
        # Al cambiar de pestana, el titulo tarda unas lecturas en confirmarse:
        # durante ese hueco el titulo confirmado aun dice "Q2" mientras el
        # bloque ya ensena las lineas de "Partido". Publicarlas ahi las
        # atribuiria al mercado equivocado, que es justo lo que no puede pasar.
        # Mientras el titulo en bruto discrepe del confirmado, no se publica
        # nada y el mercado anterior conserva intacta su ultima lectura.
        self._in_transition = bool(
            has_label_roi and self._raw_label_key is not None and self._raw_label_key != key)
        if self._in_transition:
            self.log.debug(
                f"Cambio de pestana en curso: el titulo ya dice "
                f"{self._raw_label_key.label!r} pero aun no esta confirmado; "
                "no se atribuyen lineas",
                region=RoiKind.MARKET_LABEL.value)
            return None

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
            return self._publish(key, snapshot, now)

        # Modo por columnas: lineas / cuotas OVER / cuotas UNDER en ROIs aparte.
        lines_frame = frames.get(RoiKind.LINES)
        if lines_frame and lines_frame.ok:
            snapshot = self._read_market_columns(frames, key)
            if snapshot is not None:
                return self._publish(key, snapshot, now)
            return None
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
        self.state.clock_held = False
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

    def _apply_browser_source(self, now: float) -> None:
        """Incorpora lo que aporta la extension.

        Orden de preferencia acordado: DOM confirmado por encima de OCR
        confirmado, porque el DOM viene estructurado de la propia pagina y no
        de una lectura de imagen. Cuando las dos fuentes discrepan NO se elige
        en silencio: se registra el conflicto y se deja ver en diagnostico.
        """
        fuente = self.browser_source
        if fuente is None:
            return

        # Los datos que no aporta el DOM conservan la fuente que los trajo.
        for campo, valor in (("market", self.markets.visible_key),
                             ("lines", self.markets.visible_key)):
            if valor is not None and campo not in self.field_sources:
                self.field_sources[campo] = SourceKind.OCR

        updates = fuente.market_updates(now)
        for update in updates:
            if (update.status is MarketUpdateStatus.AVAILABLE and
                    update.snapshot is not None and update.snapshot.lines):
                self.markets.observe(update.key, update.snapshot, confirmed=True,
                                     now=update.received_at, set_as_only_visible=False)
            elif update.status is MarketUpdateStatus.NO_LINES:
                self.markets.mark_suspended(update.key, now=update.received_at,
                                            set_as_only_visible=False)

        current_keys = fuente.current_market_keys(now)
        self.markets.set_visible_many(current_keys, fuente.primary_market_key(now))
        if current_keys:
            self.field_sources["market"] = SourceKind.BROWSER_DOM
            if any(update.status is MarketUpdateStatus.AVAILABLE
                   for update in updates if update.key in current_keys):
                self.field_sources["lines"] = SourceKind.BROWSER_DOM
            elif self.field_sources.get("lines") is SourceKind.BROWSER_DOM:
                self.field_sources.pop("lines", None)
        else:
            self.markets.set_visible(None)
            for campo in ("market", "lines"):
                if self.field_sources.get(campo) is SourceKind.BROWSER_DOM:
                    self.field_sources.pop(campo, None)

        estado = fuente.game_state(now)
        if not estado:
            self._clear_held_browser_clock()
            for campo in ("score_a", "score_b", "period", "clock_seconds",
                          "team_a", "team_b", "breakdown"):
                if self.field_sources.get(campo) is SourceKind.BROWSER_DOM:
                    self.field_sources.pop(campo, None)
            return

        self._apply_browser_field("score_a", estado.get("score_a"),
                                  self.state.score_a, now)
        self._apply_browser_field("score_b", estado.get("score_b"),
                                  self.state.score_b, now)
        self._apply_browser_field("period", estado.get("period"),
                                  self.state.period, now)
        browser_clock, clock_held = self._clock_for_browser_state(estado)
        self._apply_browser_field("clock_seconds", browser_clock,
                                  self.state.clock_seconds, now)
        self.state.clock_held = clock_held
        self._apply_browser_field("team_a", estado.get("team_a"),
                                  self.state.team_a, now)
        self._apply_browser_field("team_b", estado.get("team_b"),
                                  self.state.team_b, now)

        if "periods_a" in estado and "periods_b" in estado:
            self.state.tracker.replace_dom_breakdown(estado["periods_a"],
                                                     estado["periods_b"])
            if self.state.tracker.has_dom_breakdown:
                self.field_sources["breakdown"] = SourceKind.BROWSER_DOM

        # La primera clasificacion ocurrio antes de aplicar el DOM. Se repite
        # con sus valores y luego la evidencia estructural explicita manda.
        self._update_phase()
        fase = estado.get("phase")
        if fase == "HALFTIME":
            self.state.phase = GamePhase.HALFTIME
        elif fase == "GAME_OVER":
            self.state.phase = GamePhase.GAME_OVER
        elif fase == "CLOCK_STOPPED" or clock_held:
            self.state.phase = GamePhase.CLOCK_STOPPED

    def _clock_for_browser_state(self, estado: Dict[str, Any]) -> tuple[Optional[int], bool]:
        """Devuelve reloj DOM vivo/retenido sin fabricar paso del tiempo.

        La retencion exige tres evidencias simultaneas: el BrowserSource sigue
        fresco, su eventId no cambio y el gameState reobservado conserva el
        mismo periodo. Un reloj nuevo reemplaza el retenido inmediatamente.
        Una fase final estructural fija cero usando la duracion de GameRules.
        """
        fuente = self.browser_source
        event_id = fuente.event_id if fuente is not None else None
        periodo = estado.get("period")
        if periodo is None:
            periodo = self.state.period_value

        fase = estado.get("phase")
        final_confirmado = fase in ("PERIOD_END", "HALFTIME", "GAME_OVER")
        if final_confirmado and periodo is not None:
            if fase != "HALFTIME" or periodo == self.rules.halftime_after_period:
                self._remember_browser_clock(0, periodo, event_id)
                return 0, False

        reloj = self._browser_clock(estado)
        if reloj is not None and periodo is not None:
            self._remember_browser_clock(reloj, periodo, event_id)
            return reloj, False

        # Si el DOM mando un reloj pero contradice las reglas, no se oculta la
        # contradiccion reutilizando un valor anterior.
        if "clock_seconds" in estado or "clock_raw_seconds" in estado:
            self._clear_held_browser_clock()
            return None, False

        contexto_fresco = any(key in estado for key in (
            "score_a", "score_b", "period", "periods_a", "periods_b"))
        if (contexto_fresco and event_id and event_id == self._held_browser_event_id and
                periodo is not None and periodo == self._held_browser_period and
                self._held_browser_clock is not None):
            return self._held_browser_clock, True

        self._clear_held_browser_clock()
        return None, False

    def _remember_browser_clock(self, clock: int, period: int,
                                event_id: Optional[str]) -> None:
        self._held_browser_clock = int(clock)
        self._held_browser_period = int(period)
        self._held_browser_event_id = event_id

    def _clear_held_browser_clock(self) -> None:
        self._held_browser_clock = None
        self._held_browser_period = None
        self._held_browser_event_id = None

    def _browser_clock(self, estado: Dict[str, Any]) -> Optional[int]:
        """Restante del cuarto a partir de lo que manda la extension.

        La extension envia `clock_seconds` cuando la casa muestra directamente
        el restante del cuarto. BetPlay (Kambi) no lo hace: muestra el tiempo
        JUGADO del partido ("Q4 - 33:52"), y lo manda como `clock_raw_seconds`
        con su semantica. Convertirlo necesita saber cuanto dura un cuarto y
        cuantos van, y eso lo sabe este lector a traves de `self.rules`, no la
        extension: con FIBA 33:52 en el cuarto 4 deja 06:08, y con NBA ese
        valor ni siquiera cae dentro del cuarto 4.

        Si la conversion no cuadra devuelve None: sin reloj se puede seguir, con
        un reloj equivocado no.
        """
        directo = estado.get("clock_seconds")
        if directo is not None:
            return directo

        crudo = estado.get("clock_raw_seconds")
        semantica = estado.get("clock_semantics")
        if crudo is None or semantica != "GAME_ELAPSED":
            return None

        periodo = estado.get("period")
        if periodo is None:
            periodo_actual = self.state.period.usable_value()
            periodo = periodo_actual if periodo_actual is not None else None
        if periodo is None:
            return None

        restante = period_remaining_from_game_elapsed(crudo, periodo, self.rules)
        if restante is None:
            self.log.warn(
                f"El reloj del DOM dice {seconds_to_clock(crudo)} de juego acumulado en el "
                f"periodo {periodo}, y con las reglas {self.rules.name} eso no cuadra. "
                "Se deja sin reloj antes que publicar uno equivocado.",
                region="BRIDGE")
        return restante

    def _apply_browser_field(self, campo: str, valor: Any, actual: Observed, now: float) -> None:
        """Aplica un dato del DOM al estado, anotando la fuente y el conflicto."""
        if valor is None:
            if actual.is_usable and campo not in self.field_sources:
                self.field_sources[campo] = SourceKind.OCR
            return

        anterior = actual.usable_value()
        if anterior is not None and anterior != valor:
            conflicto = {"field": campo, "dom": valor, "ocr": anterior, "ts": now}
            self.source_conflicts.append(conflicto)
            self.source_conflicts = self.source_conflicts[-20:]
            self.log.warn(
                f"CONFLICTO DE FUENTES en {campo}: DOM dice {valor} y OCR dice {anterior}. "
                "Se usa el DOM por venir estructurado de la pagina.",
                region="BRIDGE")

        observado = Observed(value=valor, status=ValueStatus.CONFIRMED, confidence=1.0,
                             raw_text="", updated_at=now, source="BROWSER_DOM")
        setattr(self.state, campo if campo != "clock_seconds" else "clock_seconds", observado)
        self.field_sources[campo] = SourceKind.BROWSER_DOM

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
        # En la vista TODO puede haber varias ofertas visibles a la vez.
        for visible in (state for state in self.markets.all_states() if state.visible):
            if visible.last_seen_at is None:
                continue
            self.history.record_market_observation(
                self.session_id, visible.key, visible.last_seen_at,
                visible.last_confirmed_at)
        if now - self._last_score_persist >= 1.0 and self.state.score_a_value is not None:
            self.history.save_score_snapshot(self.session_id, self.state)
            self._last_score_persist = now
        for market_state in self.markets.all_states():
            market = market_state.snapshot
            if market is None or market.is_empty:
                continue
            from .market_tracker import signature as market_signature
            sig = market_signature(market) + tuple(
                (ln.over_odds, ln.under_odds) for ln in market.sorted_lines())
            # La firma se guarda POR MERCADO: si no, alternar entre pestanas
            # reescribiria el historial en cada cambio.
            previa = self._market_signatures.get(market.key)
            if sig != previa:
                self.history.save_market_snapshot(self.session_id, market, self.state)
                self._market_signatures[market.key] = sig

    # ------------------------------------------------------------------ hilo
    @property
    def in_market_transition(self) -> bool:
        """True mientras se esta cambiando de pestana y no se atribuye nada."""
        return self._in_transition

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
