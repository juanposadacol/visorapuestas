"""Fabrica de motores OCR (capa de abstraccion del requisito 2).

Cambiar de motor no obliga a tocar el resto de la aplicacion: basta con
registrar una clase nueva que implemente `OcrEngine`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Type

from .base import EngineNotAvailable, OcrEngine
from .engines.rapidocr_engine import RapidOcrEngine
from .engines.stub_engine import StubEngine
from .engines.tesseract_engine import TesseractEngine

REGISTRY: Dict[str, Type[OcrEngine]] = {
    RapidOcrEngine.name: RapidOcrEngine,
    TesseractEngine.name: TesseractEngine,
    StubEngine.name: StubEngine,
}

#: Orden de preferencia cuando el perfil pide "auto".
AUTO_ORDER = [RapidOcrEngine.name, TesseractEngine.name]


def register(engine_cls: Type[OcrEngine]) -> None:
    REGISTRY[engine_cls.name] = engine_cls


def available_engines() -> List[str]:
    """Motores realmente utilizables en esta maquina."""
    return [name for name, cls in REGISTRY.items() if cls.is_available()]


def create_engine(name: str = "auto", **options: Any) -> OcrEngine:
    """Crea el motor pedido. 'auto' elige el mejor disponible."""
    requested = (name or "auto").lower()
    if requested == "auto":
        for candidate in AUTO_ORDER:
            cls = REGISTRY[candidate]
            if cls.is_available():
                return cls(**options)
        raise EngineNotAvailable(
            "No hay ningun motor OCR instalado. Instala RapidOCR con:\n"
            "    pip install rapidocr-onnxruntime"
        )
    cls = REGISTRY.get(requested)
    if cls is None:
        raise EngineNotAvailable(f"motor OCR desconocido: {name}")
    if not cls.is_available():
        raise EngineNotAvailable(
            f"El motor '{name}' no esta disponible en este equipo. "
            f"Disponibles: {', '.join(available_engines()) or 'ninguno'}"
        )
    return cls(**options)
