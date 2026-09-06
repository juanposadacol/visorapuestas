"""Controlador de la aplicacion: une captura, OCR, calculo y persistencia.

Deliberadamente NO depende de Qt. La ventana llama a estos metodos, de modo
que toda la logica de sesion (fijar apuesta, cambiar de perfil, guardar
historial) se puede probar sin interfaz grafica.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .bridge.server import BridgeServer
from .bridge.source import BrowserSource, ExtensionState, LinkState, SourceKind
from .calculations import entry as entry_mod
from .calculations import manual_tracking as manual_tracking_mod
from .calculations import metrics as metrics_mod
from .calculations.entry import LineEvaluation, MarketEvaluation
from .calculations.metrics import BetMetrics, GeneralMetrics
from .config.criteria import EntryCriteria
from .config.freshness import FreshnessCriteria
from .domain.event_markets import FreshnessState
from .capture.roi_manager import RoiManager
from .capture.screen_capture import ScreenCapture, create_capture
from .config.profiles import ScreenContext, SportsbookProfile
from .config.settings import AppSettings
from .diagnostics.logbus import LogBus
from .domain.bet import LockedBet
from .calculations.manual_tracking import ManualBetTracking
from .domain.manual_bet import ManualBet, ManualBetStatus, ManualBetSummary
from .domain.market import MarketKey, MarketType, MarketLine, MarketSnapshot, Side
from .domain.rules import rules_from_name
from .ocr.base import EngineNotAvailable, OcrEngine
from .ocr.engine import create_engine
from .pipeline.reader import LiveReader, ReaderSnapshot
from .storage.database import Database
from .storage.repositories import (
    BetRepository,
    HistoryRepository,
    ManualBetRepository,
    ProfileRepository,
    SessionRepository,
)


class AppMode(str, Enum):
    """Los dos modos de la aplicacion.

    BUSCANDO_ENTRADA es el modo principal: todavia no has apostado y el
    tablero analiza en vivo todas las lineas que ofrece la casa.
    APUESTA_FIJADA anade el seguimiento de tu apuesta SIN quitar el tablero:
    los dos conviven en pantalla.
    """

    BUSCANDO_ENTRADA = "BUSCANDO_ENTRADA"
    APUESTA_FIJADA = "APUESTA_FIJADA"

    @property
    def label(self) -> str:
        return {"BUSCANDO_ENTRADA": "BUSCANDO ENTRADA",
                "APUESTA_FIJADA": "APUESTA FIJADA"}[self.value]


#: Version que anuncia el puente en /health.
APP_VERSION = "1.1.0"


class SessionState(str, Enum):
    """En que punto esta el arranque de la sesion.

    Existe para que la aplicacion no intente arrancar una y otra vez ni diga
    "no se puede iniciar: faltan regiones" como primera respuesta. Las regiones
    son el ultimo recurso; lo normal es esperar a que lleguen los datos.
    """

    WAITING_FOR_DATA = "WAITING_FOR_DATA"   # falta algun dato necesario
    READY = "READY"                         # se puede arrancar ya
    RUNNING = "RUNNING"                     # sesion en marcha

    @property
    def label(self) -> str:
        return {"WAITING_FOR_DATA": "ESPERANDO DATOS",
                "READY": "LISTO PARA EMPEZAR",
                "RUNNING": "RADAR ACTIVO"}[self.value]


@dataclass
class ViewModel:
    """Todo lo que la interfaz necesita para pintar un ciclo."""

    snapshot: Optional[ReaderSnapshot] = None
    general: Optional[GeneralMetrics] = None
    mode: AppMode = AppMode.BUSCANDO_ENTRADA
    #: Un bloque por mercado observado, cada uno con sus propias lineas.
    blocks: List[MarketEvaluation] = field(default_factory=list)
    #: Evaluaciones del mercado VISIBLE (atajo para lo que se esta mirando).
    evaluations: List[LineEvaluation] = field(default_factory=list)
    #: Estado de frescura del mercado al que pertenece la linea enfocada.
    focus_freshness: Optional[FreshnessState] = None
    focus_age_text: str = ""
    #: Linea que ocupa la tarjeta grande (seleccion manual o cuota objetivo).
    focus: Optional[LineEvaluation] = None
    #: Seguimiento de la apuesta fijada, calculado contra su linea congelada.
    bet_tracking: Optional[LineEvaluation] = None
    bet: Optional[LockedBet] = None
    selected_line: Optional[MarketLine] = None
    current_market_line: Optional[MarketLine] = None
    criteria: EntryCriteria = field(default_factory=EntryCriteria)
    freshness: FreshnessCriteria = field(default_factory=FreshnessCriteria)
    #: DOS EJES SEPARADOS. `extension_state` dice si la extension esta ahi;
    #: `link_state` dice si los DATOS que manda siguen frescos. Que no haya
    #: datos no significa que la extension este caida, y confundirlos fue lo
    #: que hizo que el panel dijera EXTENSION DESCONECTADA con la extension
    #: perfectamente conectada.
    extension_state: ExtensionState = ExtensionState.DISCONNECTED
    link_state: LinkState = LinkState.DISCONNECTED
    link_age_seconds: Optional[float] = None
    #: Que falta para poder arrancar. Vacio = listo.
    waiting_for: List[str] = field(default_factory=list)
    session_state: SessionState = SessionState.WAITING_FOR_DATA
    link_latency_ms: Optional[float] = None
    field_sources: Dict[str, str] = field(default_factory=dict)
    source_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    #: Apuestas manuales del Browser Bridge (flujo anterior, sin monto).
    manual_bets: list = field(default_factory=list)
    #: Seguimiento en vivo de cada apuesta manual del libro: puntos del
    #: mercado, margen, puntos para cruzar, proyeccion y estado. Una entrada
    #: por apuesta, calculada contra SU mercado y SU linea.
    manual_tracking: List[ManualBetTracking] = field(default_factory=list)


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
        # Dos conceptos distintos:
        # - manual_bet_repo: libro manual con monto, cuota, resultado y ROI.
        # - manual_bets: apuestas manuales vinculadas al flujo/browser anterior.
        self.manual_bet_repo = ManualBetRepository(self.db)
        self.manual_bets = self.bets.list_manual()
        #: Copia del libro manual. La interfaz se refresca 4 veces por segundo
        #: y el seguimiento no puede depender de consultar SQLite cada vez.
        #: Se invalida en cuanto se agrega, liquida o borra una apuesta.
        self._manual_ledger: Optional[List[ManualBet]] = None

        self._capture = capture
        #: Fuente DOM y puente local. Se arrancan al abrir la aplicacion para
        #: que la extension pueda conectarse sola en cuanto abras BetPlay.
        self.browser = BrowserSource(self.settings.browser)
        self.bridge = BridgeServer(
            self.settings.bridge, on_payload=self._on_browser_payload,
            on_contact=self.browser.note_contact,
            version=APP_VERSION, log=lambda nivel, mensaje: self.log.log(nivel, mensaje))
        self.engine: Optional[OcrEngine] = None
        self._engine_setting: Optional[str] = None
        self.profile: Optional[SportsbookProfile] = None
        self.reader: Optional[LiveReader] = None
        self.session_id: Optional[int] = None
        self.event_id: Optional[int] = None
        self.locked_bet: Optional[LockedBet] = None
        self.selected_line: Optional[MarketLine] = None
        self.selected_side: Side = Side.UNDER
        #: Linea elegida a mano (mercado + valor). Manda sobre el enfoque
        #: automatico por cuota objetivo mientras esa linea siga existiendo.
        self.manual_line_value: Optional[float] = None
        self.manual_market_key = None
        self.demo_game = None

    # ---------------------------------------------------------------- basico
    @property
    def capture(self) -> ScreenCapture:
        if self._capture is None:
            self._capture = create_capture(self.settings.capture_backend)
            self.log.info(f"Backend de captura: {type(self._capture).__name__}")
        return self._capture

    def ensure_engine(self, name: str = "auto") -> Optional[OcrEngine]:
        """Devuelve el motor OCR solicitado por el perfil activo.

        Un motor ya creado solo se reutiliza si corresponde a la misma
        configuracion. Esto evita conservar por accidente el motor de otra
        casa/perfil al cambiar de configuracion.
        """
        requested = (name or "auto").strip() or "auto"
        if self.engine is not None and self._engine_setting == requested:
            return self.engine
        try:
            self.engine = create_engine(requested)
            self.engine.warmup()
            self._engine_setting = requested
            self.log.info(f"Motor OCR: {self.engine.describe()}")
        except EngineNotAvailable as exc:
            self.engine = None
            self._engine_setting = None
            self.log.error(str(exc))
        return self.engine

    def screen_context(self) -> ScreenContext:
        monitors = self.capture.monitors()
        monitor = monitors[0] if monitors else None
        if monitor is None:
            return ScreenContext()
        return ScreenContext(width=monitor.width, height=monitor.height)

    # ------------------------------------------------------------------ puente
    def start_bridge(self) -> bool:
        """Arranca el puente local. Si el puerto esta ocupado, lo dice y sigue."""
        if not self.settings.bridge.enabled:
            self.log.info("Puente local desactivado en las preferencias")
            return False
        if self.bridge.start():
            self.log.info(f"Puente local escuchando en {self.bridge.url} "
                          "(solo 127.0.0.1)")
            return True
        self.log.warn(f"No se pudo arrancar el puente: {self.bridge.stats.last_error}. "
                      "La aplicacion funciona igual con OCR.")
        return False

    def _on_browser_payload(self, payload: Dict[str, Any]) -> None:
        """Llega desde el hilo del puente: solo guarda, no toca la interfaz."""
        paquete = self.browser.accept(payload)
        cambio = self.browser.pending_event_change
        if cambio:
            self.log.info(f"La extension cambio de partido: {cambio['from']} -> {cambio['to']}",
                          region="BRIDGE")
        del paquete

    @property
    def link_state(self) -> LinkState:
        return self.browser.link_state()

    @property
    def extension_state(self) -> ExtensionState:
        return self.browser.extension_state()

    @property
    def session_state(self) -> SessionState:
        """WAITING_FOR_DATA / READY / RUNNING, sin efectos secundarios."""
        if self.reader is not None:
            return SessionState.RUNNING
        if self.missing_requirements(self.profile):
            return SessionState.WAITING_FOR_DATA
        return SessionState.READY

    def dom_fields(self) -> List[str]:
        return self.browser.available_fields()

    def dom_field_sources(self) -> Dict[str, str]:
        """Que campos cubre el DOM ahora mismo, en el formato del panel."""
        return {campo: SourceKind.BROWSER_DOM.value for campo in self.dom_fields()}

    # ---------------------------------------------------------------- requisitos
    def missing_requirements(self, profile: Optional[SportsbookProfile] = None) -> List[str]:
        """Que falta para poder empezar, contando TODAS las fuentes.

        Una region deja de ser obligatoria en cuanto otra fuente entrega ese
        mismo dato. Es lo que permite abrir un partido sin dibujar nada cuando
        la extension esta conectada.
        """
        from .capture.roi import RoiKind

        perfil = profile or self.profile
        dom = set(self.dom_fields())
        faltan: List[str] = []

        tiene_mercado = "market" in dom or (perfil is not None and perfil.has(RoiKind.MARKET_BLOCK))
        if not tiene_mercado:
            faltan.append("mercado y lineas")

        tiene_reloj = "clock_seconds" in dom or (perfil is not None and perfil.has(RoiKind.CLOCK))
        if not tiene_reloj:
            faltan.append("reloj")

        tiene_cuarto = "period" in dom or (perfil is not None and perfil.has(RoiKind.PERIOD))
        if not tiene_cuarto:
            faltan.append("cuarto")

        marcador_dom = {"score_a", "score_b"} <= dom
        marcador_roi = perfil is not None and (
            perfil.has(RoiKind.SCORE_PAIR) or
            (perfil.has(RoiKind.SCORE_A) and perfil.has(RoiKind.SCORE_B)))
        if not (marcador_dom or marcador_roi):
            faltan.append("marcador")

        return faltan

    def browser_profile(self) -> SportsbookProfile:
        """Perfil implicito para trabajar solo con la extension, sin regiones.

        No se le pide al usuario que dibuje nada: si el DOM trae el mercado,
        no hay ninguna region que definir.
        """
        from .capture.roi import Rect

        perfil = SportsbookProfile(name="BetPlay (extension)", sportsbook="BetPlay",
                                   frame=Rect(0, 0, 1920, 1080))
        perfil.engine = "stub"
        perfil.notes = ("Perfil automatico: los datos llegan por la extension del "
                        "navegador y no hacen falta regiones.")
        return perfil

    def enable_demo(self, game=None) -> SportsbookProfile:
        """Activa el partido simulado: ni captura de pantalla ni OCR reales."""
        from .capture.screen_capture import NullCapture
        from .pipeline.demo import DemoGame, demo_engine, demo_profile

        self.demo_game = game or DemoGame()
        self._capture = NullCapture()
        self.engine = demo_engine(self.demo_game)
        profile = demo_profile()
        self._engine_setting = profile.engine
        existing = self.profiles.load(profile.name)
        if existing is not None:
            profile.profile_id = existing.profile_id
        self.save_profile(profile)
        self.log.info("MODO DEMO activado: partido simulado, no se lee la pantalla")
        return profile

    # -------------------------------------------------------------- perfiles
    def profile_names(self) -> List[str]:
        return self.profiles.list_names()

    def profile_exists(self, name: str, *, exclude_profile_id: Optional[int] = None) -> bool:
        return self.profiles.exists(name, exclude_profile_id=exclude_profile_id)

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
        if profile is None and self.browser.is_live:
            # Con la extension conectada no hace falta perfil: se usa el
            # implicito y no se pide dibujar ninguna region.
            profile = self.browser_profile()
        if profile is None:
            self.log.error("No hay perfil seleccionado")
            return None

        faltan = self.missing_requirements(profile)
        if faltan:
            self.log.error("Faltan datos para empezar: " + ", ".join(faltan) +
                           ". Conecta la extension o define esas regiones.")
            return None

        necesita_ocr = bool(profile.rois)
        engine = self.ensure_engine(profile.engine) if necesita_ocr else self.engine
        if engine is None and necesita_ocr:
            return None
        if engine is None:
            # Sin regiones no se llama al OCR en ningun momento; el motor
            # simulado basta para satisfacer la interfaz del lector.
            from .ocr.engines.stub_engine import StubEngine
            engine = StubEngine()

        rules = rules_from_name(profile.rules_name)
        if necesita_ocr:
            captura = self.capture
            pantalla = self.screen_context()
        else:
            # Sin regiones no se captura nada, asi que tampoco hace falta un
            # backend de pantalla: la aplicacion debe poder trabajar solo con
            # la extension aunque este equipo no pueda capturar.
            from .capture.screen_capture import NullCapture
            captura = NullCapture()
            pantalla = None
        manager = RoiManager(profile, captura, screen=pantalla)
        if necesita_ocr:
            manager.learn_anchor()

        self.event_id = self.sessions.create_event(profile.sportsbook, "", "", rules.name)
        self.session_id = self.sessions.start(self.event_id, profile.profile_id, self.criteria)

        self.reader = LiveReader(
            manager, engine, rules=rules, logbus=self.log, history=self.history,
            session_id=self.session_id,
            required_confirmations=profile.stabilization_required,
            value_ttl=profile.value_ttl_seconds,
            sportsbook=profile.sportsbook or profile.name,
            browser_source=self.browser,
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
        # El puente se cierra siempre, aunque algo mas falle: no puede quedar
        # el puerto ocupado ni un hilo suelto.
        try:
            self.bridge.stop()
        except Exception:  # pragma: no cover
            pass
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
    @property
    def criteria(self) -> EntryCriteria:
        return self.settings.entry

    @property
    def freshness_criteria(self) -> FreshnessCriteria:
        return self.settings.freshness

    @property
    def mode(self) -> AppMode:
        return AppMode.APUESTA_FIJADA if self.locked_bet else AppMode.BUSCANDO_ENTRADA

    def select_line(self, line: Optional[MarketLine], side: Side = Side.UNDER,
                    manual: bool = True) -> None:
        """Registra la linea elegida. `manual` la fija como foco preferido."""
        self.selected_line = line
        self.selected_side = side
        if manual:
            self.manual_line_value = line.line if line is not None else None
            self.manual_market_key = line.key if line is not None else None

    def clear_manual_selection(self) -> None:
        """Vuelve al enfoque automatico por cuota objetivo."""
        self.manual_line_value = None
        self.manual_market_key = None

    def set_visible_market(self, key) -> None:
        """Fuerza a mano que mercado se considera visible en pantalla."""
        if self.reader is not None:
            self.reader.set_manual_visible_market(key)

    def update_criteria(self, criteria: EntryCriteria) -> None:
        """Aplica criterios nuevos y los deja guardados en la sesion en curso."""
        self.settings.entry = criteria.validate()
        try:
            self.settings.save()
        except OSError:
            pass
        if self.session_id is not None:
            self.sessions.save_criteria(self.session_id, self.settings.entry)
        self.log.info(f"Criterios de entrada: {self.settings.entry.describe()}")

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

    # ------------------------------------------------------ apuestas manuales
    def add_ledger_manual_bet(self, *, sportsbook: str, event: str, key: MarketKey,
                       side: Side, line: float, odds: float, stake: float,
                       notes: str = "") -> ManualBet:
        bet = ManualBet(
            sportsbook=sportsbook,
            event=event,
            key=key,
            side=side,
            line=float(line),
            odds=float(odds),
            stake=float(stake),
            notes=notes,
            session_id=self.session_id,
        )
        saved = self.manual_bet_repo.save(bet)
        self._invalidate_manual_ledger()
        self.log.info(
            f"APUESTA MANUAL #{saved.bet_id}: {saved.sportsbook} | "
            f"{saved.key.label} | {saved.description} | monto {saved.stake:g}"
        )
        return saved

    def list_manual_bets(self, limit: int = 100) -> List[ManualBet]:
        return self.manual_bet_repo.list_recent(limit)

    def _invalidate_manual_ledger(self) -> None:
        self._manual_ledger = None

    def manual_ledger(self, limit: int = 100) -> List[ManualBet]:
        """Libro manual con memoria, para poder consultarlo en cada refresco."""
        if self._manual_ledger is None:
            self._manual_ledger = self.manual_bet_repo.list_recent(limit)
        return self._manual_ledger

    def settle_manual_bet(
        self, bet_id: int, status: ManualBetStatus
    ) -> Optional[ManualBet]:
        bet = self.manual_bet_repo.settle(bet_id, status)
        self._invalidate_manual_ledger()
        if bet is not None:
            self.log.info(f"APUESTA MANUAL #{bet_id}: {status.label}")
        return bet

    def delete_manual_bet(self, bet_id: int) -> None:
        self.manual_bet_repo.delete(bet_id)
        self._invalidate_manual_ledger()
        self.log.info(f"APUESTA MANUAL #{bet_id}: eliminada")

    def manual_bet_summary(self) -> ManualBetSummary:
        return self.manual_bet_repo.summary()

    # ------------------------------------------- seguimiento en vivo manual
    def manual_bet_tracking(
        self, snapshot: Optional[ReaderSnapshot] = None
    ) -> List[ManualBetTracking]:
        """Seguimiento de TODAS las apuestas manuales contra el partido actual.

        Cada apuesta se calcula contra SU mercado y SU linea, asi que tres
        apuestas simultaneas (BetPlay Q4 40.5, Stake Q4 42.5 y BetPlay partido
        185.5) se actualizan a la vez sin mezclarse.

        La casa NO interviene en el calculo: el marcador y el reloj son del
        partido, no de la casa. Por eso una apuesta de Stake se sigue con los
        datos que llegan por el DOM de BetPlay, que es justo lo que hace falta
        mientras Stake no tenga su propio parser.
        """
        if snapshot is None and self.reader is not None:
            snapshot = self.reader.last_snapshot
        state = snapshot.state if snapshot is not None else None
        return manual_tracking_mod.track_manual_bets(state, self.manual_ledger())

    def manual_bet_tracking_for(
        self, bet_id: int, snapshot: Optional[ReaderSnapshot] = None
    ) -> Optional[ManualBetTracking]:
        """Seguimiento de una apuesta concreta, para el bloque de detalle."""
        for tracking in self.manual_bet_tracking(snapshot):
            if tracking.bet.bet_id == bet_id:
                return tracking
        return None

    def set_period_baseline(self, period: int, score_a: int, score_b: int) -> None:
        if self.reader is None:
            return
        self.reader.state.tracker.set_manual_baseline(period, score_a, score_b)
        self.log.info(f"Marcador inicial del periodo {period}: {score_a}-{score_b}",
                      region="PERIOD")

    def add_browser_manual_bet(self, key: MarketKey, line: float, odds: float,
                               sportsbook: str) -> LockedBet:
        snapshot = self.reader.last_snapshot if self.reader else None
        if snapshot is None or self.session_id is None:
            raise ValueError("Inicia la lectura del partido antes de registrar una apuesta.")
        if snapshot.browser_event_id != self.browser.event_id:
            raise ValueError("Espera a que termine el cambio de partido.")
        if not math.isfinite(line) or line <= 0 or line > 1000 or line * 2 != round(line * 2):
            raise ValueError("La linea debe ser positiva y terminar en .0 o .5.")
        if not math.isfinite(odds) or odds <= 1 or odds > 1000:
            raise ValueError("La cuota decimal debe ser mayor que 1 y menor o igual a 1000.")
        if not sportsbook.strip():
            raise ValueError("Escribe la casa de apuestas.")
        if (key.market_type is MarketType.QUARTER_TOTAL and key.period not in range(1, 5)
                or key.market_type is MarketType.HALF_TOTAL and key.half not in (1, 2)):
            raise ValueError("Selecciona partido, mitad 1/2 o cuarto 1 a 4.")
        state = snapshot.state
        event = " vs ".join(str(v.value) for v in (state.team_a, state.team_b) if v.value)
        bet = LockedBet(sportsbook=sportsbook.strip(), event=event or f"Partido {self.session_id}",
                        key=key, side=Side.UNDER, line=float(line), odds=float(odds),
                        score_a_when_locked=state.score_a_value, score_b_when_locked=state.score_b_value,
                        clock_when_locked=state.clock_value, period_when_locked=state.period_value,
                        session_id=self.session_id)
        bet = replace(bet, bet_id=self.bets.save_manual(bet, snapshot.browser_event_id))
        self.manual_bets = self.bets.list_manual()
        return bet

    def add_manual_bet(
        self,
        key: MarketKey,
        line: float,
        odds: float,
        sportsbook: str,
        event: str = "",
        side: Side = Side.UNDER,
        stake: Optional[float] = None,
        notes: str = "",
    ):
        """Registra una apuesta manual en el flujo correspondiente.

        - Con ``stake``: usa el libro manual persistente con resultado,
          utilidad y ROI.
        - Sin ``stake``: conserva el flujo anterior del Browser Bridge,
          asociado al partido/sesion que se esta leyendo.
        """
        if stake is None:
            return self.add_browser_manual_bet(
                key=key,
                line=line,
                odds=odds,
                sportsbook=sportsbook,
            )

        return self.add_ledger_manual_bet(
            sportsbook=sportsbook,
            event=event,
            key=key,
            side=side,
            line=line,
            odds=odds,
            stake=stake,
            notes=notes,
        )

    def remove_manual_bet(self, bet_id: int) -> None:
        if not any(b.bet_id == bet_id for b, _, _ in self.manual_bets):
            raise ValueError("No existe esa apuesta manual.")
        self.bets.close(bet_id, "RELEASED")
        self.manual_bets = self.bets.list_manual()

    def manual_bet_views(self, snapshot: Optional[ReaderSnapshot]) -> list:
        rows = []
        for bet, event_id, status in self.manual_bets:
            evaluation = None
            reason = "OTRA SESION / HISTORIAL"
            if status != "OPEN":
                reason = "SEGUIMIENTO RETIRADO"
            elif bet.session_id == self.session_id and self.reader is not None:
                reason = "ESPERANDO DATOS"
                if (snapshot is not None and event_id == snapshot.browser_event_id
                        and event_id == self.browser.event_id):
                    if self.reader.is_paused:
                        reason = "LECTURA PAUSADA"
                    elif time.time() - snapshot.ts > self.reader.roi_manager.profile.value_ttl_seconds:
                        reason = "DATOS DESACTUALIZADOS"
                    else:
                        evaluation = entry_mod.evaluate_locked_bet(snapshot.state, bet, self.criteria)
                        reason = ""
            rows.append((bet, evaluation, reason))
        return rows

    # --------------------------------------------------------------- lectura
    def build_view_model(self, snapshot: Optional[ReaderSnapshot]) -> ViewModel:
        """Traduce un ciclo de lectura en el tablero completo.

        Las senales se recalculan en CADA ciclo con los ultimos valores
        confirmados de reloj y marcador, aunque el bloque de mercado se lea a
        menor cadencia: lo que se mueve rapido es el reloj.
        """
        if snapshot is None:
            # Sin sesion todavia, pero el panel tiene que poder decir QUE cubre
            # ya el DOM: es justo lo que hace falta para entender por que no
            # arranca, en vez de un "faltan regiones" que no explica nada.
            return ViewModel(manual_bets=self.manual_bet_views(None),
                             manual_tracking=self.manual_bet_tracking(None),
                             criteria=self.criteria, link_state=self.browser.link_state(),
                             extension_state=self.browser.extension_state(),
                             waiting_for=self.missing_requirements(self.profile),
                             session_state=self.session_state,
                             field_sources=self.dom_field_sources(),
                             link_age_seconds=self.browser.age_seconds())
        state = snapshot.state
        criteria = self.criteria
        general = metrics_mod.compute_general_metrics(state)

        # Un bloque por mercado observado: el radar completo, con la frescura
        # de cada pieza a la vista.
        blocks = entry_mod.evaluate_event(
            state, snapshot.markets, criteria, self.freshness_criteria, general, now=snapshot.ts)

        visible_key = snapshot.markets.visible_key if snapshot.markets else None
        evaluations = next((b.evaluations for b in blocks if b.key == visible_key), [])

        focus = None
        focus_block = None
        if self.manual_line_value is not None and self.manual_market_key is not None:
            focus = entry_mod.find_evaluation(blocks, self.manual_market_key,
                                              self.manual_line_value)
            focus_block = next((b for b in blocks if b.key == self.manual_market_key), None)
        if focus is None:
            # Sin seleccion manual se enfoca dentro del mercado visible, por
            # cuota objetivo. Si no hay mercado visible, el primer bloque.
            focus_block = next((b for b in blocks if b.key == visible_key), None) or \
                (blocks[0] if blocks else None)
            focus = focus_block.focus if focus_block is not None else None

        # La seleccion sigue al foco para que FIJAR APUESTA use lo que se ve.
        if focus is not None:
            self.select_line(focus.line, self.selected_side, manual=False)

        bet = self.locked_bet
        bet_tracking = None
        current_line = None
        if bet is not None:
            bet_tracking = entry_mod.evaluate_locked_bet(state, bet, criteria, general)
            # El mercado actual de la apuesta es el SUYO, no el que se este
            # mirando: la apuesta fijada y la pestana visible son cosas
            # distintas y pueden no coincidir.
            bet_market = snapshot.markets.get(bet.key) if snapshot.markets else None
            if bet_market is not None and bet_market.snapshot is not None:
                current_line = bet_market.snapshot.find(bet.line)
                if current_line is None and bet_market.lines:
                    # La casa movio la linea: se ensena la mas cercana como
                    # referencia, sin tocar la apuesta fijada.
                    current_line = min(bet_market.lines,
                                       key=lambda ln: abs(ln.line - bet.line))

        paquete = self.browser.last_packet
        return ViewModel(
            manual_bets=self.manual_bet_views(snapshot),
            # Cada apuesta manual se recalcula con ESTE snapshot: cuando el
            # marcador pasa de 32 a 34 el seguimiento cambia solo.
            manual_tracking=self.manual_bet_tracking(snapshot),
            link_state=self.browser.link_state(),
            extension_state=self.browser.extension_state(),
            waiting_for=self.missing_requirements(self.profile),
            session_state=self.session_state,
            link_age_seconds=self.browser.age_seconds(),
            link_latency_ms=paquete.latency_ms if paquete else None,
            field_sources=dict(snapshot.field_sources or {}),
            source_conflicts=list(snapshot.source_conflicts or []),
            snapshot=snapshot, general=general, mode=self.mode,
            blocks=blocks, evaluations=evaluations, focus=focus,
            focus_freshness=focus_block.freshness if focus_block else None,
            focus_age_text=focus_block.age_text(snapshot.ts) if focus_block else "",
            bet_tracking=bet_tracking, bet=bet, selected_line=self.selected_line,
            current_market_line=current_line, criteria=criteria,
            freshness=self.freshness_criteria,
        )
