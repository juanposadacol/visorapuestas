"""Captura de pantalla (requisito 2 y 4).

Backends soportados, todos locales y gratuitos:

* MSS      multiplataforma, sin dependencias nativas, ~5-10 ms por ROI
           pequeno. Es el predeterminado por fiabilidad.
* DXCam    solo Windows, usa Desktop Duplication API. Mas rapido en capturas
           grandes, pero mas fragil (falla con algunos drivers y con pantalla
           bloqueada). Se ofrece como opcion.

La aplicacion captura SOLO los rectangulos configurados, no la pantalla
entera, salvo en la pantalla de configuracion de ROIs (requisito 3).
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from .roi import Rect

try:  # numpy es obligatorio en produccion, opcional para los tests de logica
    import numpy as np
except Exception:  # pragma: no cover - entorno sin numpy
    np = None


class CaptureError(RuntimeError):
    """La captura no se pudo realizar."""


class ScreenCapture(ABC):
    """Interfaz comun de captura. Devuelve imagenes BGR (compatibles OpenCV)."""

    @abstractmethod
    def grab(self, rect: Rect) -> Any:
        """Captura un rectangulo. Devuelve un array HxWx3 en BGR."""

    @abstractmethod
    def monitors(self) -> List[Rect]:
        """Lista de monitores disponibles (el indice 0 es el escritorio completo)."""

    def close(self) -> None:
        return None

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class MssCapture(ScreenCapture):
    """Backend MSS. Una instancia por hilo (mss no es thread-safe)."""

    def __init__(self) -> None:
        try:
            import mss  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise CaptureError(
                "Falta la dependencia 'mss'. Instala con: pip install mss"
            ) from exc
        self._local = threading.local()

    def _sct(self):
        import mss
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self, rect: Rect):
        if not rect.is_valid:
            raise CaptureError(f"rectangulo invalido: {rect}")
        if np is None:  # pragma: no cover
            raise CaptureError("numpy no esta instalado")
        raw = self._sct().grab(rect.to_mss())
        frame = np.asarray(raw)  # BGRA
        return frame[:, :, :3].copy()

    def monitors(self) -> List[Rect]:
        return [
            Rect(m["left"], m["top"], m["width"], m["height"])
            for m in self._sct().monitors
        ]

    def close(self) -> None:
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            self._local.sct = None


class DxCamCapture(ScreenCapture):
    """Backend DXCam (solo Windows). Mas rapido, algo menos robusto."""

    def __init__(self, monitor_index: int = 0) -> None:
        try:
            import dxcam
        except ImportError as exc:  # pragma: no cover
            raise CaptureError(
                "Falta la dependencia 'dxcam'. Instala con: pip install dxcam"
            ) from exc
        self._camera = dxcam.create(output_idx=monitor_index, output_color="BGR")
        if self._camera is None:  # pragma: no cover
            raise CaptureError("DXCam no pudo abrir el monitor solicitado")
        self._monitor_index = monitor_index

    def grab(self, rect: Rect):
        if not rect.is_valid:
            raise CaptureError(f"rectangulo invalido: {rect}")
        region = (rect.x, rect.y, rect.right, rect.bottom)
        frame = self._camera.grab(region=region)
        if frame is None:
            # DXCam devuelve None cuando no hubo cambios desde la ultima captura.
            raise CaptureError("sin fotograma nuevo")
        return frame

    def monitors(self) -> List[Rect]:  # pragma: no cover - depende del hardware
        import dxcam
        info = dxcam.device_info()
        del info
        return []

    def close(self) -> None:  # pragma: no cover
        try:
            self._camera.release()
        except Exception:
            pass


class NullCapture(ScreenCapture):
    """Backend de pruebas: devuelve imagenes en blanco. No toca la pantalla."""

    def __init__(self, monitor: Optional[Rect] = None) -> None:
        self._monitor = monitor or Rect(0, 0, 1920, 1080)

    def grab(self, rect: Rect):
        if np is None:  # pragma: no cover
            raise CaptureError("numpy no esta instalado")
        return np.zeros((max(1, rect.height), max(1, rect.width), 3), dtype="uint8")

    def monitors(self) -> List[Rect]:
        return [self._monitor, self._monitor]


def create_capture(backend: str = "auto", monitor_index: int = 0) -> ScreenCapture:
    """Fabrica de backends. 'auto' prueba DXCam en Windows y cae a MSS."""
    backend = (backend or "auto").lower()
    if backend == "mss":
        return MssCapture()
    if backend == "dxcam":
        return DxCamCapture(monitor_index)
    if backend == "null":
        return NullCapture()
    # auto
    import sys
    if sys.platform.startswith("win"):
        try:
            return DxCamCapture(monitor_index)
        except Exception:
            pass
    return MssCapture()


def available_backends() -> List[str]:
    """Backends realmente instalados en esta maquina."""
    found = ["null"]
    try:
        import mss  # noqa: F401
        found.insert(0, "mss")
    except ImportError:
        pass
    try:
        import dxcam  # noqa: F401
        found.insert(0, "dxcam")
    except ImportError:
        pass
    return found
