"""Motor RapidOCR (ONNXRuntime) -- motor PREDETERMINADO.

Por que este y no otro:

* Es 100 % local y gratuito, sin claves ni servicios en la nube.
* Se instala con pip y TRAE LOS MODELOS DENTRO del paquete, asi que el .exe
  generado con PyInstaller funciona sin pedirle al usuario que instale nada
  aparte (Tesseract exige un instalador externo y configurar el PATH).
* Detecta varias lineas de texto dentro del mismo recorte, que es justo lo
  que necesita el bloque de lineas y cuotas (varias filas 37.5 / 1.55 / 2.25).
* Va sobrado para 2-4 lecturas por segundo sobre ROIs pequenos en CPU.
"""

from __future__ import annotations

from typing import Any, List, Optional

from ...capture.roi import OcrHints
from ..base import EngineNotAvailable, OcrBox, OcrEngine, OcrResult, timed


class RapidOcrEngine(OcrEngine):
    name = "rapidocr"

    def __init__(self, **options: Any) -> None:
        self._options = options
        self._engine = None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except ImportError:
            try:
                import rapidocr  # noqa: F401
                return True
            except ImportError:
                return False

    def warmup(self) -> None:
        self._ensure()

    def _ensure(self):
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            try:
                from rapidocr import RapidOCR  # paquete nuevo
            except ImportError as exc:
                raise EngineNotAvailable(
                    "RapidOCR no esta instalado. Instala con: "
                    "pip install rapidocr-onnxruntime"
                ) from exc
        self._engine = RapidOCR(**self._options)
        return self._engine

    @timed
    def recognize(self, image: Any, hints: Optional[OcrHints] = None) -> OcrResult:
        if image is None:
            return OcrResult(engine=self.name, error="imagen vacia")
        try:
            engine = self._ensure()
            output = engine(image)
        except Exception as exc:  # pragma: no cover - depende del entorno
            return OcrResult(engine=self.name, error=f"{type(exc).__name__}: {exc}")

        detections = output[0] if isinstance(output, (tuple, list)) else getattr(output, "boxes", None)
        if not detections:
            return OcrResult(engine=self.name, text="", confidence=0.0)

        boxes: List[OcrBox] = []
        for item in detections:
            try:
                points, text, score = item[0], item[1], float(item[2])
                top = min(p[1] for p in points)
                left = min(p[0] for p in points)
            except Exception:  # pragma: no cover - formatos alternativos
                continue
            boxes.append(OcrBox(text=str(text), confidence=score, top=int(top), left=int(left)))

        # Orden de lectura: por filas y, dentro de la fila, de izquierda a derecha.
        boxes.sort(key=lambda b: (round(b.top / 12), b.left))
        text = "\n".join(b.text for b in boxes)
        confidence = sum(b.confidence for b in boxes) / len(boxes) if boxes else 0.0
        return OcrResult(text=text, confidence=confidence, boxes=boxes, engine=self.name)
