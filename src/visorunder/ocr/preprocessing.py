"""Preprocesado de imagen antes del OCR.

El texto de una web es nitido pero pequeno. Lo que mas mejora el acierto es
AMPLIAR el recorte antes de reconocerlo; despues, binarizar ayuda cuando el
tema es oscuro (texto claro sobre fondo oscuro es lo habitual en las casas).

Todas las funciones son tolerantes: si OpenCV no esta disponible devuelven la
imagen tal cual en lugar de romper el ciclo de lectura.
"""

from __future__ import annotations

from typing import Any, Optional

from ..capture.roi import OcrHints

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


def to_gray(image: Any) -> Any:
    if cv2 is None or image is None:
        return image
    if getattr(image, "ndim", 2) == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def upscale(image: Any, factor: float) -> Any:
    if cv2 is None or image is None or factor is None or factor <= 1.0:
        return image
    height, width = image.shape[:2]
    return cv2.resize(image, (int(width * factor), int(height * factor)),
                      interpolation=cv2.INTER_CUBIC)


def invert(image: Any) -> Any:
    if cv2 is None or image is None:
        return image
    return cv2.bitwise_not(image)


def autodetect_dark_theme(gray: Any) -> bool:
    """True si el recorte parece texto claro sobre fondo oscuro."""
    if np is None or gray is None:
        return False
    try:
        return float(np.mean(gray)) < 110.0
    except Exception:  # pragma: no cover
        return False


def binarize(image: Any, mode: str = "adaptive") -> Any:
    if cv2 is None or image is None or mode == "none":
        return image
    if mode == "otsu":
        _, out = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return out
    return cv2.adaptiveThreshold(image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 31, 10)


def denoise(image: Any) -> Any:
    if cv2 is None or image is None:
        return image
    return cv2.medianBlur(image, 3)


def add_border(image: Any, size: int = 10, value: int = 255) -> Any:
    """Los motores OCR aciertan mas si el texto no toca el borde."""
    if cv2 is None or image is None:
        return image
    return cv2.copyMakeBorder(image, size, size, size, size, cv2.BORDER_CONSTANT, value=value)


#: Altura util para el reconocedor de texto. Ampliar mas alla de esto no
#: mejora el acierto y multiplica el coste de cada lectura.
TARGET_LINE_HEIGHT = 64


def effective_scale(image: Any, hints: OcrHints) -> float:
    """Factor de ampliacion real, acotado por la altura util del reconocedor."""
    if image is None or not hints.single_line:
        return hints.scale
    height = image.shape[0]
    if height <= 0:
        return hints.scale
    needed = TARGET_LINE_HEIGHT / float(height)
    return max(1.0, min(hints.scale, needed))


def prepare(image: Any, hints: Optional[OcrHints] = None) -> Any:
    """Pipeline completo de preprocesado segun los ajustes del ROI."""
    if image is None:
        return None
    hints = hints or OcrHints()
    out = to_gray(image)
    if out is None:
        return None

    should_invert = hints.invert or autodetect_dark_theme(out)
    if should_invert:
        out = invert(out)

    out = upscale(out, effective_scale(out, hints))
    if hints.denoise:
        out = denoise(out)
    out = binarize(out, hints.threshold)
    out = add_border(out, 10, 255)
    return out
