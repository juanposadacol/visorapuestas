"""Orquesta la captura de todas las regiones de un perfil.

Responsabilidades:
* resolver las coordenadas de cada ROI para la pantalla actual;
* aplicar la correccion del ancla si existe;
* capturar solo esos rectangulos (nunca la pantalla completa);
* informar de los fallos sin romper el ciclo de lectura.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config.profiles import ScreenContext, SportsbookProfile
from .anchor import AnchorTracker
from .roi import Rect, Roi, RoiKind
from .screen_capture import CaptureError, ScreenCapture


@dataclass
class RoiFrame:
    """Imagen capturada de un ROI concreto."""

    kind: RoiKind
    image: Any
    rect: Rect
    timestamp: float = field(default_factory=time.time)
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.image is not None and not self.error


class RoiManager:
    """Captura el conjunto de ROIs de un perfil en cada ciclo."""

    def __init__(self, profile: SportsbookProfile, capture: ScreenCapture,
                 screen: Optional[ScreenContext] = None,
                 frame_override: Optional[Rect] = None,
                 use_anchor: bool = True) -> None:
        self.profile = profile
        self.capture = capture
        self.screen = screen
        self.frame_override = frame_override
        self.anchor = AnchorTracker() if use_anchor else None
        self._resolved: Dict[RoiKind, Rect] = {}
        self.last_error: str = ""
        self.refresh_layout()

    # ------------------------------------------------------------- geometria
    def refresh_layout(self) -> None:
        """Recalcula los rectangulos absolutos para la pantalla actual."""
        self._resolved = self.profile.resolve_rois(self.screen, self.frame_override)

    def rect_for(self, kind: RoiKind) -> Optional[Rect]:
        rect = self._resolved.get(kind)
        if rect is None:
            return None
        if self.anchor is not None:
            return self.anchor.correct(rect)
        return rect

    def configured_kinds(self) -> List[RoiKind]:
        return list(self._resolved.keys())

    # --------------------------------------------------------------- captura
    def grab(self, kind: RoiKind) -> Optional[RoiFrame]:
        rect = self.rect_for(kind)
        if rect is None:
            return None
        try:
            image = self.capture.grab(rect)
            return RoiFrame(kind=kind, image=image, rect=rect)
        except CaptureError as exc:
            self.last_error = str(exc)
            return RoiFrame(kind=kind, image=None, rect=rect, error=str(exc))

    def grab_all(self, kinds: Optional[List[RoiKind]] = None) -> Dict[RoiKind, RoiFrame]:
        """Captura todas las regiones pedidas (por defecto, todas las activas)."""
        wanted = kinds if kinds is not None else self.configured_kinds()
        frames: Dict[RoiKind, RoiFrame] = {}
        for kind in wanted:
            if kind is RoiKind.ANCHOR:
                continue
            frame = self.grab(kind)
            if frame is not None:
                frames[kind] = frame
        return frames

    # ----------------------------------------------------------------- ancla
    def learn_anchor(self) -> bool:
        """Memoriza el recorte del ancla en su posicion actual."""
        if self.anchor is None:
            return False
        rect = self._resolved.get(RoiKind.ANCHOR)
        if rect is None:
            return False
        try:
            image = self.capture.grab(rect)
        except CaptureError as exc:
            self.last_error = str(exc)
            return False
        self.anchor.learn(image, rect)
        return True

    def update_anchor(self) -> bool:
        """Recalcula el desplazamiento buscando el ancla en pantalla."""
        if self.anchor is None or not self.anchor.has_template:
            return False
        search = self.anchor.search_rect()
        if search is None:
            return False
        try:
            image = self.capture.grab(search)
        except CaptureError as exc:
            self.last_error = str(exc)
            return False
        return self.anchor.update(image).applied
