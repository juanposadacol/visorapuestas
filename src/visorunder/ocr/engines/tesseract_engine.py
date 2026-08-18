"""Motor Tesseract (pytesseract) -- alternativa rapida para ROIs de digitos.

Ventaja: con `whitelist` de caracteres y modo "una sola linea" es muy rapido
y muy preciso en recortes minusculos como el reloj o el marcador.
Inconveniente: requiere instalar el binario de Tesseract aparte, por eso no es
el motor predeterminado.
"""

from __future__ import annotations

import shutil
from typing import Any, List, Optional

from ...capture.roi import OcrHints
from ..base import EngineNotAvailable, OcrBox, OcrEngine, OcrResult, timed


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def __init__(self, cmd: str = "", lang: str = "spa+eng") -> None:
        self.cmd = cmd
        self.lang = lang
        self._ready = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return shutil.which("tesseract") is not None

    def _ensure(self):
        import pytesseract
        if not self._ready:
            if self.cmd:
                pytesseract.pytesseract.tesseract_cmd = self.cmd
            elif shutil.which("tesseract") is None:
                raise EngineNotAvailable(
                    "No se encuentra el ejecutable de Tesseract. Instalalo o "
                    "indica su ruta en la configuracion del perfil."
                )
            self._ready = True
        return pytesseract

    def _config(self, hints: OcrHints) -> str:
        parts = [f"--psm {hints.psm or 7}", "--oem 1"]
        if hints.whitelist:
            parts.append(f"-c tessedit_char_whitelist={hints.whitelist}")
        return " ".join(parts)

    @timed
    def recognize(self, image: Any, hints: Optional[OcrHints] = None) -> OcrResult:
        if image is None:
            return OcrResult(engine=self.name, error="imagen vacia")
        hints = hints or OcrHints()
        try:
            pytesseract = self._ensure()
            data = pytesseract.image_to_data(
                image, lang=self.lang, config=self._config(hints),
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:  # pragma: no cover - depende del entorno
            return OcrResult(engine=self.name, error=f"{type(exc).__name__}: {exc}")

        boxes: List[OcrBox] = []
        confidences: List[float] = []
        for i, word in enumerate(data.get("text", [])):
            word = (word or "").strip()
            if not word:
                continue
            try:
                conf = float(data["conf"][i])
            except (KeyError, ValueError, IndexError):
                conf = -1.0
            if conf < 0:
                continue
            confidences.append(conf / 100.0)
            boxes.append(OcrBox(text=word, confidence=conf / 100.0,
                                top=int(data["top"][i]), left=int(data["left"][i])))

        boxes.sort(key=lambda b: (round(b.top / 12), b.left))
        # Agrupa por filas para conservar la estructura visual del bloque.
        lines: List[str] = []
        current_row = None
        buffer: List[str] = []
        for box in boxes:
            row = round(box.top / 12)
            if current_row is None or row == current_row:
                buffer.append(box.text)
            else:
                lines.append(" ".join(buffer))
                buffer = [box.text]
            current_row = row
        if buffer:
            lines.append(" ".join(buffer))

        confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrResult(text="\n".join(lines), confidence=confidence,
                         boxes=boxes, engine=self.name)
