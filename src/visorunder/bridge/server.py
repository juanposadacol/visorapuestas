"""Servidor local del puente.

Decisiones de seguridad, todas deliberadas:

* Escucha SOLO en 127.0.0.1. Nunca en 0.0.0.0, asi que nada de la red local
  puede alcanzarlo.
* Solo acepta DATOS. No hay ningun endpoint que ejecute comandos, abra
  ficheros, apueste o controle el navegador. El puente va en un solo sentido:
  extension -> datos -> aplicacion.
* Exige la cabecera `X-VisorApuestas-Bridge`. Una cabecera personalizada obliga
  al navegador a hacer preflight, de modo que una pagina web cualquiera no
  puede colar peticiones sin que el servidor apruebe antes su origen.
* CORS restringido: se responde con el origen concreto que hizo la peticion y
  solo si es una extension. Nunca `*`.
* Limite de tamano del cuerpo y validacion de esquema antes de tocar nada.

Se usa `http.server` de la libreria estandar a proposito: el requisito es
recibir un JSON pequeno en bucle local, y no compensa arrastrar FastAPI o
Flask para eso.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

from .schema import BridgeValidationError, ensure_valid

#: Puerto por defecto. Configurable desde las preferencias.
DEFAULT_PORT = 8765
#: Cabecera del protocolo: su presencia fuerza el preflight del navegador.
BRIDGE_HEADER = "X-VisorApuestas-Bridge"


@dataclass
class BridgeSettings:
    """Ajustes del puente local."""

    enabled: bool = True
    #: Nunca 0.0.0.0. Se valida al arrancar.
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    max_body_bytes: int = 64 * 1024
    require_header: bool = True
    #: Origenes aceptados. Un ID de extension sin empaquetar depende de la ruta
    #: de instalacion, asi que no se puede fijar de antemano: se acepta
    #: cualquier origen de extension y se responde con ESE origen concreto.
    #: Si prefieres cerrarlo del todo, pon aqui el ID exacto una vez instalada.
    allowed_origin_prefixes: tuple = ("chrome-extension://", "moz-extension://", "extension://")
    pinned_origin: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled, "host": self.host, "port": self.port,
            "max_body_bytes": self.max_body_bytes, "require_header": self.require_header,
            "pinned_origin": self.pinned_origin,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "BridgeSettings":
        settings = BridgeSettings()
        for clave, valor in (data or {}).items():
            if hasattr(settings, clave):
                setattr(settings, clave, valor)
        return settings.validate()

    def validate(self) -> "BridgeSettings":
        # Cinturon: aunque alguien edite el fichero de preferencias a mano, el
        # puente no puede acabar escuchando en toda la red.
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            self.host = "127.0.0.1"
        self.port = int(self.port) if 1024 <= int(self.port) <= 65535 else DEFAULT_PORT
        self.max_body_bytes = max(1024, min(int(self.max_body_bytes), 1024 * 1024))
        return self


@dataclass
class BridgeStats:
    started_at: Optional[float] = None
    accepted: int = 0
    rejected: int = 0
    last_accepted_at: Optional[float] = None
    last_rejected_at: Optional[float] = None
    last_error: str = ""
    last_origin: str = ""
    #: Latidos de /health que vienen de la extension.
    health_checks: int = 0
    #: Ultima vez que la EXTENSION dio senales de vida, con mercado o sin el.
    #: Es lo que permite decir "extension conectada, todavia sin mercado" en
    #: lugar de "extension desconectada", que es lo que se veia antes.
    last_extension_contact_at: Optional[float] = None
    extension_version: str = ""


class _Handler(BaseHTTPRequestHandler):
    """Maneja las dos unicas rutas del puente."""

    server_version = "VisorApuestasBridge/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- utilidades
    @property
    def settings(self) -> BridgeSettings:
        return self.server.bridge_settings  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        # El log del puente va al bus de diagnostico de la aplicacion, no a
        # stderr: si no, ensucia la consola en cada latido.
        bus = getattr(self.server, "bridge_log", None)
        if bus is not None:
            bus("DEBUG", fmt % args)

    def _origin_allowed(self, origin: str) -> bool:
        if not origin:
            # Una peticion sin Origin no viene de una pagina web; con la
            # cabecera del protocolo exigida, es aceptable.
            return True
        if self.settings.pinned_origin:
            return origin == self.settings.pinned_origin
        return any(origin.startswith(p) for p in self.settings.allowed_origin_prefixes)

    def _send(self, status: int, body: Optional[Dict[str, Any]] = None) -> None:
        payload = json.dumps(body if body is not None else {}).encode("utf-8")
        origin = self.headers.get("Origin", "")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if origin and self._origin_allowed(origin):
            # Se devuelve el origen EXACTO, nunca "*".
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    # ----------------------------------------------------------------- rutas
    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self.headers.get("Origin", "")
        if not self._origin_allowed(origin):
            self._send(403, {"error": "origen no permitido"})
            return
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, {BRIDGE_HEADER}")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _note_extension_contact(self) -> None:
        """Anota que la extension esta ahi, aunque no traiga mercado.

        La extension consulta /health cada pocos segundos aunque no haya nada
        que enviar. Sin esta marca, la aplicacion solo sabia de ella cuando
        llegaba un mercado, y el panel decia EXTENSION DESCONECTADA mientras la
        extension estaba perfectamente conectada esperando a reconocer uno.
        """
        stats: BridgeStats = self.server.bridge_stats  # type: ignore[attr-defined]
        if self.headers.get(BRIDGE_HEADER) != "1":
            return                       # no viene de la extension
        stats.last_extension_contact_at = time.time()
        aviso = getattr(self.server, "bridge_contact", None)
        if aviso is not None:
            aviso()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/health":
            self._send(404, {"error": "ruta desconocida"})
            return
        server = self.server
        stats: BridgeStats = server.bridge_stats  # type: ignore[attr-defined]
        stats.health_checks += 1
        self._note_extension_contact()
        self._send(200, {
            "status": "ok",
            "app": "VisorApuestas",
            "version": getattr(server, "bridge_version", "0"),
            "protocol": 1,
            "uptimeSeconds": round(time.time() - (server.bridge_stats.started_at or time.time()), 1),
        })

    def do_POST(self) -> None:  # noqa: N802
        server = self.server
        stats: BridgeStats = server.bridge_stats  # type: ignore[attr-defined]

        if self.path.split("?")[0] != "/v1/browser-state":
            self._send(404, {"error": "ruta desconocida"})
            return

        origin = self.headers.get("Origin", "")
        stats.last_origin = origin
        if not self._origin_allowed(origin):
            stats.rejected += 1
            stats.last_error = f"origen no permitido: {origin}"
            self._send(403, {"error": "origen no permitido"})
            return

        if self.settings.require_header and self.headers.get(BRIDGE_HEADER) != "1":
            stats.rejected += 1
            stats.last_error = "falta la cabecera del protocolo"
            self._send(400, {"error": f"falta {BRIDGE_HEADER}"})
            return
        self._note_extension_contact()

        tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if tipo != "application/json":
            stats.rejected += 1
            stats.last_error = f"content-type invalido: {tipo}"
            self._send(415, {"error": "se espera application/json"})
            return

        try:
            longitud = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            longitud = -1
        if longitud <= 0:
            stats.rejected += 1
            stats.last_error = "cuerpo vacio"
            self._send(400, {"error": "cuerpo vacio"})
            return
        if longitud > self.settings.max_body_bytes:
            stats.rejected += 1
            stats.last_error = f"cuerpo demasiado grande: {longitud}"
            self._send(413, {"error": "cuerpo demasiado grande"})
            return

        crudo = self.rfile.read(longitud)
        try:
            datos = json.loads(crudo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            stats.rejected += 1
            stats.last_error = f"json invalido: {exc}"
            self._send(400, {"error": "json invalido"})
            return

        try:
            ensure_valid(datos)
        except BridgeValidationError as exc:
            stats.rejected += 1
            stats.last_error = "; ".join(exc.errors[:4])
            self._send(422, {"error": "payload invalido", "details": exc.errors[:10]})
            return

        try:
            server.bridge_callback(datos)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - el puente nunca tumba la app
            stats.rejected += 1
            stats.last_error = f"error al procesar: {type(exc).__name__}: {exc}"
            self._send(500, {"error": "error al procesar"})
            return

        stats.accepted += 1
        stats.last_accepted_at = time.time()
        stats.last_error = ""
        self._send(200, {"status": "ok", "accepted": True})


class BridgeServer:
    """Arranca y para el servidor local en un hilo aparte."""

    def __init__(self, settings: Optional[BridgeSettings] = None,
                 on_payload: Optional[Callable[[Dict[str, Any]], None]] = None,
                 version: str = "1.0.0",
                 log: Optional[Callable[[str, str], None]] = None,
                 on_contact: Optional[Callable[[], None]] = None) -> None:
        # `port=0` es la convencion del sistema operativo para un puerto
        # efimero. Se usa en tests e integraciones locales para no colisionar
        # con una instancia real de VisorApuestas ya abierta. Los ajustes
        # persistidos siguen saneandose a 8765 mediante BridgeSettings.validate.
        ephemeral = settings is not None and settings.port == 0
        self.settings = (settings or BridgeSettings()).validate()
        if ephemeral:
            self.settings.port = 0
        self.on_payload = on_payload or (lambda _payload: None)
        #: Se llama en CADA senal de vida de la extension, traiga mercado o no.
        self.on_contact = on_contact or (lambda: None)
        self.version = version
        self.log = log
        self.stats = BridgeStats()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        if self._httpd is None:
            return self.settings.port
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.settings.host}:{self.port}"

    def start(self) -> bool:
        """Arranca el servidor. Devuelve False si el puerto esta ocupado."""
        if self._httpd is not None:
            return True
        try:
            httpd = ThreadingHTTPServer((self.settings.host, self.settings.port), _Handler)
        except OSError as exc:
            self.stats.last_error = f"no se pudo abrir el puerto {self.settings.port}: {exc}"
            return False

        httpd.bridge_settings = self.settings          # type: ignore[attr-defined]
        httpd.bridge_callback = self._handle_payload   # type: ignore[attr-defined]
        httpd.bridge_contact = self._handle_contact    # type: ignore[attr-defined]
        httpd.bridge_stats = self.stats                # type: ignore[attr-defined]
        httpd.bridge_version = self.version            # type: ignore[attr-defined]
        httpd.bridge_log = (lambda nivel, mensaje: self.log(nivel, mensaje)) if self.log else None
        httpd.daemon_threads = True

        self.stats.started_at = time.time()
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="visorunder-bridge", daemon=True)
        self._thread.start()
        return True

    def _handle_payload(self, payload: Dict[str, Any]) -> None:
        self.on_payload(payload)

    def _handle_contact(self) -> None:
        try:
            self.on_contact()
        except Exception:            # noqa: BLE001 - un aviso no puede tumbar el puente
            pass

    def stop(self) -> None:
        """Cierra el servidor y libera el puerto. Seguro de llamar dos veces."""
        httpd, self._httpd = self._httpd, None
        thread, self._thread = self._thread, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def __enter__(self) -> "BridgeServer":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()
