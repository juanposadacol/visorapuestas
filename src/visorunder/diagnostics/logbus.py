"""Bus de diagnostico (requisito 22).

Guarda en memoria (y opcionalmente en fichero) todo lo necesario para
averiguar por que un dato se leyo mal:

    region, OCR bruto, OCR normalizado, confianza, valor confirmado,
    motivo del rechazo, tiempo empleado y marca temporal.

Es un anillo acotado: no crece sin limite durante un partido largo.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


@dataclass
class LogEntry:
    ts: float = field(default_factory=time.time)
    level: str = "INFO"
    region: str = ""
    raw: str = ""
    normalized: str = ""
    confidence: float = 0.0
    value: str = ""
    status: str = ""
    reason: str = ""
    elapsed_ms: float = 0.0
    message: str = ""

    @property
    def clock_text(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%H:%M:%S.%f")[:-3]

    def as_row(self) -> List[str]:
        return [
            self.clock_text, self.level, self.region, self.raw, self.normalized,
            f"{self.confidence:.2f}" if self.confidence else "",
            self.value, self.status, self.reason,
            f"{self.elapsed_ms:.0f}" if self.elapsed_ms else "",
        ]

    def as_text(self) -> str:
        parts = [self.clock_text, self.level]
        if self.region:
            parts.append(self.region)
        if self.message:
            parts.append(self.message)
        if self.raw:
            parts.append(f"raw={self.raw!r}")
        if self.normalized and self.normalized != self.raw:
            parts.append(f"norm={self.normalized!r}")
        if self.value:
            parts.append(f"valor={self.value}")
        if self.status:
            parts.append(f"[{self.status}]")
        if self.reason:
            parts.append(f"motivo={self.reason}")
        return " | ".join(parts)


class LogBus:
    """Anillo de entradas con suscriptores. Seguro entre hilos."""

    COLUMNS = ["Hora", "Nivel", "Region", "OCR bruto", "Normalizado",
               "Conf.", "Valor", "Estado", "Motivo", "ms"]

    def __init__(self, capacity: int = 2000, file_path: Optional[Any] = None) -> None:
        self._entries: Deque[LogEntry] = deque(maxlen=capacity)
        self._lock = threading.RLock()
        self._subscribers: List[Callable[[LogEntry], None]] = []
        self.file_path = Path(file_path) if file_path else None
        self.min_level = "DEBUG"
        if self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def subscribe(self, callback: Callable[[LogEntry], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[LogEntry], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _should_keep(self, level: str) -> bool:
        try:
            return LEVELS.index(level) >= LEVELS.index(self.min_level)
        except ValueError:
            return True

    def emit(self, entry: LogEntry) -> None:
        if not self._should_keep(entry.level):
            return
        with self._lock:
            self._entries.append(entry)
            subscribers = list(self._subscribers)
            if self.file_path:
                try:
                    with self.file_path.open("a", encoding="utf-8") as handle:
                        handle.write(entry.as_text() + "\n")
                except OSError:
                    pass
        for callback in subscribers:
            try:
                callback(entry)
            except Exception:  # pragma: no cover - un suscriptor no debe tumbar el bus
                pass

    # ------------------------------------------------------------- atajos
    def log(self, level: str, message: str, **kwargs: Any) -> None:
        self.emit(LogEntry(level=level, message=message, **kwargs))

    def debug(self, message: str, **kwargs: Any) -> None:
        self.log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self.log("INFO", message, **kwargs)

    def warn(self, message: str, **kwargs: Any) -> None:
        self.log("WARN", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.log("ERROR", message, **kwargs)

    def reading(self, region: str, raw: str, normalized: str, confidence: float,
                value: str, status: str, reason: str = "", elapsed_ms: float = 0.0) -> None:
        """Registra una lectura completa de un ROI."""
        level = "DEBUG" if status in ("CONFIRMED", "RAW") and not reason else "WARN"
        if status == "CONFIRMED":
            level = "INFO"
        self.emit(LogEntry(level=level, region=region, raw=raw, normalized=normalized,
                           confidence=confidence, value=value, status=status,
                           reason=reason, elapsed_ms=elapsed_ms))

    # ------------------------------------------------------------- consulta
    def entries(self, limit: Optional[int] = None, region: str = "",
                level: str = "") -> List[LogEntry]:
        with self._lock:
            items = list(self._entries)
        if region:
            items = [e for e in items if e.region == region]
        if level:
            items = [e for e in items if e.level == level]
        if limit:
            items = items[-limit:]
        return items

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def export(self, path: Any) -> int:
        """Vuelca el log a un fichero de texto y devuelve las lineas escritas."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        items = self.entries()
        with target.open("w", encoding="utf-8") as handle:
            for entry in items:
                handle.write(entry.as_text() + "\n")
        return len(items)
