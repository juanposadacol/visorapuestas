"""Motor simulado: no lee la pantalla, devuelve el texto que se le indique.

Sirve para dos cosas:

* pruebas automaticas del pipeline completo sin depender de un OCR real;
* MODO DEMO de la aplicacion, para practicar con la interfaz y verificar los
  calculos sin tener que configurar ROIs ni abrir una casa de apuestas.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ...capture.roi import OcrHints
from ..base import OcrEngine, OcrResult, timed

#: Funcion que, dado el identificador del ROI, devuelve (texto, confianza).
TextProvider = Callable[[str], Optional[tuple]]


class StubEngine(OcrEngine):
    name = "stub"

    def __init__(self, provider: Optional[TextProvider] = None,
                 texts: Optional[Dict[str, str]] = None,
                 confidence: float = 0.95) -> None:
        self.provider = provider
        self.texts: Dict[str, str] = dict(texts or {})
        self.confidence = confidence

    def set_text(self, roi_kind: str, text: str) -> None:
        self.texts[roi_kind] = text

    @timed
    def recognize(self, image: Any, hints: Optional[OcrHints] = None) -> OcrResult:
        key = (hints.roi_kind if hints else "") or ""
        if self.provider is not None:
            produced = self.provider(key)
            if produced is None:
                return OcrResult(engine=self.name, text="", confidence=0.0)
            text, confidence = produced
            return OcrResult(text=str(text), confidence=float(confidence), engine=self.name)
        text = self.texts.get(key, "")
        return OcrResult(text=text, confidence=self.confidence if text else 0.0, engine=self.name)
