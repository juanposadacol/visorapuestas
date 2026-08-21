"""Fuente de datos del navegador.

La aplicacion pasa a tener varias fuentes para el mismo dato:

    BrowserSource   la extension, via el puente local
    OCR             la lectura de pantalla que ya existia
    Manual          lo que introduce el usuario

Esta clase representa la primera. Guarda lo ultimo que llego, decide si sigue
vigente y NO inventa nada: si hace demasiado que no se recibe un paquete, lo
dice en vez de seguir mostrando lo viejo como si fuera actual.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from ..domain.market import MarketKey, MarketSnapshot
from . import converter


class SourceKind(str, Enum):
    """De donde salio un dato. La capa de adquisicion lo sabe; el dominio no."""

    BROWSER_DOM = "BROWSER_DOM"
    OCR = "OCR"
    MANUAL = "MANUAL"
    NONE = "NONE"

    @property
    def label(self) -> str:
        return {"BROWSER_DOM": "DOM", "OCR": "OCR",
                "MANUAL": "manual", "NONE": "--"}[self.value]


class LinkState(str, Enum):
    """Frescura de los DATOS que llegan del navegador.

    Ojo con la distincion, que costo una prueba real entera: esto habla de los
    DATOS, no de la extension. Que no llegue ningun mercado no significa que la
    extension este caida; puede estar perfectamente conectada y todavia sin
    reconocer un mercado que enviar. Para eso esta `ExtensionState`.
    """

    DISCONNECTED = "DISCONNECTED"   # nunca llego nada, o hace mucho
    LIVE = "LIVE"                   # paquetes recientes
    STALE = "STALE"                 # llego algo, pero hace demasiado

    @property
    def label(self) -> str:
        return {"DISCONNECTED": "SIN DATOS DEL DOM",
                "LIVE": "BETPLAY CONECTADO",
                "STALE": "DATOS DOM DESACTUALIZADOS"}[self.value]


class ExtensionState(str, Enum):
    """Estado de la EXTENSION, independiente de que traiga datos o no.

    La extension consulta /health cada pocos segundos aunque no tenga nada que
    enviar. Esa senal es la que decide este estado.
    """

    DISCONNECTED = "DISCONNECTED"   # no da senales de vida
    CONNECTED = "CONNECTED"         # latido reciente
    STALE = "STALE"                 # dio senales, pero hace demasiado

    @property
    def label(self) -> str:
        return {"DISCONNECTED": "EXTENSION DESCONECTADA",
                "CONNECTED": "EXTENSION CONECTADA",
                "STALE": "EXTENSION SIN CONFIRMAR"}[self.value]


@dataclass
class BrowserSourceSettings:
    """Cuando dejar de fiarse de lo que llego del navegador."""

    #: Mas alla de esto, el enlace deja de considerarse en vivo.
    live_within_seconds: float = 3.0
    #: Mas alla de esto, se da por desconectado.
    disconnected_after_seconds: float = 12.0
    #: La extension late cada 5 s: con el doble de margen basta para no
    #: parpadear si un latido se pierde.
    extension_alive_within_seconds: float = 12.0
    #: Sin latidos durante este tiempo, la extension se da por caida.
    extension_lost_after_seconds: float = 30.0

    def validate(self) -> "BrowserSourceSettings":
        self.live_within_seconds = max(0.5, float(self.live_within_seconds))
        self.disconnected_after_seconds = max(self.live_within_seconds + 1.0,
                                              float(self.disconnected_after_seconds))
        self.extension_alive_within_seconds = max(1.0,
                                                  float(self.extension_alive_within_seconds))
        self.extension_lost_after_seconds = max(self.extension_alive_within_seconds + 1.0,
                                                float(self.extension_lost_after_seconds))
        return self


@dataclass
class BrowserPacket:
    """Un paquete recibido, con los tiempos para poder medir la latencia."""

    payload: Dict[str, Any]
    observed_at: float
    received_at: float
    processed_at: float = 0.0

    @property
    def latency_ms(self) -> float:
        """Desde que el navegador lo observo hasta que la app lo proceso.

        Puede salir negativa si los relojes no coinciden exactamente; se acota
        a cero en lugar de mostrar un numero imposible.
        """
        fin = self.processed_at or self.received_at
        return max(0.0, (fin - self.observed_at) * 1000.0)


class BrowserSource:
    """Estado de la fuente DOM. Seguro entre hilos: escribe el hilo del puente."""

    def __init__(self, settings: Optional[BrowserSourceSettings] = None) -> None:
        self.settings = (settings or BrowserSourceSettings()).validate()
        self._lock = threading.RLock()
        self._last: Optional[BrowserPacket] = None
        self._snapshot: Optional[MarketSnapshot] = None
        self._game_state: Dict[str, Any] = {}
        self._event_id: Optional[str] = None
        self._event_name: str = ""
        self.packets = 0
        self.event_changes = 0
        self.last_error: str = ""
        #: Ultimo latido de la extension, con mercado o sin el.
        self._last_contact: Optional[float] = None
        #: Se marca cuando cambia el evento, para que la aplicacion decida.
        self.pending_event_change: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------- recepcion
    def accept(self, payload: Dict[str, Any], now: Optional[float] = None) -> BrowserPacket:
        """Registra un paquete ya validado por el esquema."""
        now = now if now is not None else time.time()
        with self._lock:
            observado = converter.parse_observed_at(payload.get("observedAt"))
            paquete = BrowserPacket(payload=payload, observed_at=observado, received_at=now)

            identificador = converter.event_id(payload)
            if identificador and self._event_id and identificador != self._event_id:
                # Cambio de partido: no se mezclan mercados de eventos distintos.
                self.pending_event_change = {
                    "from": self._event_id, "to": identificador,
                    "name": converter.event_name(payload), "at": now,
                }
                self.event_changes += 1
                self._snapshot = None
            self._event_id = identificador or self._event_id
            self._event_name = converter.event_name(payload) or self._event_name

            try:
                self._snapshot = converter.payload_to_snapshot(payload)
                self._game_state = converter.payload_to_game_state(payload)
                self.last_error = ""
            except (ValueError, KeyError, TypeError) as exc:
                self.last_error = f"payload no convertible: {exc}"
                paquete.processed_at = time.time()
                self._last = paquete
                return paquete

            paquete.processed_at = time.time()
            self._last = paquete
            self.packets += 1
            return paquete

    def note_contact(self, now: Optional[float] = None) -> None:
        """La extension ha dado senales de vida.

        Se llama desde el puente en CADA /health, no solo cuando llega un
        mercado. Es lo que separa "la extension no esta" de "la extension esta
        pero todavia no reconoce ningun mercado", que el panel confundia.
        """
        with self._lock:
            self._last_contact = now if now is not None else time.time()

    def contact_age_seconds(self, now: Optional[float] = None) -> Optional[float]:
        with self._lock:
            if self._last_contact is None:
                return None
            return max(0.0, (now if now is not None else time.time()) - self._last_contact)

    def extension_state(self, now: Optional[float] = None) -> ExtensionState:
        """Estado de la EXTENSION. No mira los datos, solo los latidos.

        Un paquete de mercado tambien cuenta como latido: si llega un mercado,
        evidentemente la extension esta ahi.
        """
        edades = [e for e in (self.contact_age_seconds(now), self.age_seconds(now))
                  if e is not None]
        if not edades:
            return ExtensionState.DISCONNECTED
        edad = min(edades)
        if edad <= self.settings.extension_alive_within_seconds:
            return ExtensionState.CONNECTED
        if edad <= self.settings.extension_lost_after_seconds:
            return ExtensionState.STALE
        return ExtensionState.DISCONNECTED

    def clear_event_change(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            cambio, self.pending_event_change = self.pending_event_change, None
            return cambio

    def reset(self) -> None:
        with self._lock:
            self._last = None
            self._snapshot = None
            self._game_state = {}
            self._event_id = None
            self._event_name = ""
            self.pending_event_change = None
            # El contacto NO se borra: la extension sigue estando ahi aunque se
            # reinicie la sesion de lectura.

    # -------------------------------------------------------------- consulta
    def age_seconds(self, now: Optional[float] = None) -> Optional[float]:
        with self._lock:
            if self._last is None:
                return None
            return max(0.0, (now if now is not None else time.time()) - self._last.received_at)

    def link_state(self, now: Optional[float] = None) -> LinkState:
        edad = self.age_seconds(now)
        if edad is None:
            return LinkState.DISCONNECTED
        if edad <= self.settings.live_within_seconds:
            return LinkState.LIVE
        if edad <= self.settings.disconnected_after_seconds:
            return LinkState.STALE
        return LinkState.DISCONNECTED

    @property
    def is_live(self) -> bool:
        return self.link_state() is LinkState.LIVE

    def snapshot(self, now: Optional[float] = None) -> Optional[MarketSnapshot]:
        """Mercado vigente. None si el enlace ya no es de fiar."""
        if self.link_state(now) is LinkState.DISCONNECTED:
            return None
        with self._lock:
            return self._snapshot

    def last_snapshot_any_age(self) -> Optional[MarketSnapshot]:
        """Ultimo mercado observado, sin importar la antiguedad.

        Sirve para poder decir ULTIMA LINEA OBSERVADA con su hora, que no es lo
        mismo que la linea actual de la casa.
        """
        with self._lock:
            return self._snapshot

    def game_state(self, now: Optional[float] = None) -> Dict[str, Any]:
        if self.link_state(now) is LinkState.DISCONNECTED:
            return {}
        with self._lock:
            return dict(self._game_state)

    def available_fields(self, now: Optional[float] = None) -> List[str]:
        """Que datos esta aportando el DOM ahora mismo."""
        campos: List[str] = []
        if self.snapshot(now) is not None:
            campos += ["market", "lines"]
        estado = self.game_state(now)
        for clave in ("score_a", "score_b", "period"):
            if clave in estado:
                campos.append(clave)
        # El reloj cuenta como cubierto tanto si la casa da directamente el
        # restante del cuarto como si da el tiempo acumulado del partido: la
        # conversion la hace el lector, que es quien conoce las reglas.
        if "clock_seconds" in estado or "clock_raw_seconds" in estado:
            campos.append("clock_seconds")
        return campos

    @property
    def event_id(self) -> Optional[str]:
        with self._lock:
            return self._event_id

    @property
    def event_name(self) -> str:
        with self._lock:
            return self._event_name

    @property
    def last_packet(self) -> Optional[BrowserPacket]:
        with self._lock:
            return self._last

    def latency_ms(self) -> Optional[float]:
        paquete = self.last_packet
        return paquete.latency_ms if paquete else None

    def describe(self, now: Optional[float] = None) -> str:
        extension = self.extension_state(now)
        estado = self.link_state(now)
        edad = self.age_seconds(now)
        if edad is None:
            # Sin datos, lo que importa es si la extension esta o no: decir
            # "desconectada" cuando esta conectada mandaba el diagnostico por
            # el camino contrario.
            if extension is ExtensionState.CONNECTED:
                return f"{extension.label} · todavia sin mercado reconocido"
            return extension.label
        return f"{estado.label} · ultimo paquete hace {edad:.1f} s"
