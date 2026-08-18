"""Abstraccion del motor OCR (requisito 2).

Toda la aplicacion habla con esta interfaz, nunca con RapidOCR ni con
Tesseract directamente. Cambiar de motor mas adelante (o anadir uno nuevo)
consiste en implementar `OcrEngine` y registrarlo en la fabrica.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from ..capture.roi import OcrHints


@dataclass(frozen=True)
class OcrBox:
    """Una linea de texto reconocida dentro del recorte."""

    text: str
    confidence: float = 0.0
    top: int = 0
    left: int = 0


@dataclass(frozen=True)
class OcrResult:
    """Salida cruda del motor. La interpretacion la hacen los parsers."""

    text: str = ""
    confidence: float = 0.0
    boxes: List[OcrBox] = field(default_factory=list)
    engine: str = ""
    elapsed_ms: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error

    @property
    def lines(self) -> List[str]:
        return [ln for ln in self.text.splitlines() if ln.strip()]


class OcrEngine(ABC):
    """Contrato minimo de un motor OCR local."""

    name: str = "base"

    @abstractmethod
    def recognize(self, image: Any, hints: Optional[OcrHints] = None) -> OcrResult:
        """Reconoce el texto de una imagen ya preprocesada."""

    @classmethod
    def is_available(cls) -> bool:
        """True si el motor puede usarse en esta maquina."""
        return True

    def warmup(self) -> None:
        """Carga perezosa de modelos. Opcional."""
        return None

    def close(self) -> None:
        return None

    def describe(self) -> str:
        return self.name


class EngineNotAvailable(RuntimeError):
    """El motor pedido no esta instalado o no se puede inicializar."""


def timed(fn):
    """Decorador que mide el tiempo de reconocimiento."""

    def wrapper(self, image, hints=None):
        start = time.perf_counter()
        result = fn(self, image, hints)
        elapsed = (time.perf_counter() - start) * 1000.0
        return OcrResult(
            text=result.text,
            confidence=result.confidence,
            boxes=result.boxes,
            engine=result.engine or self.name,
            elapsed_ms=elapsed,
            error=result.error,
        )

    return wrapper
