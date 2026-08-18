"""Re-anclaje de ROIs por correlacion de imagen (requisito 24).

Problema real: el usuario configura los ROIs y despues mueve la ventana del
navegador, hace scroll o cambia el zoom. Las coordenadas absolutas dejan de
servir.

Solucion: al configurar se guarda un recorte pequeno y estable (el "ancla",
por ejemplo la zona del reloj o el logo del marcador). En ejecucion se busca
ese recorte dentro de una ventana de busqueda alrededor de su posicion
original; el desplazamiento encontrado se aplica a todos los ROIs.

Si OpenCV no esta disponible o la correlacion es debil, NO se corrige nada:
antes sin correccion que con una correccion inventada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .roi import Rect

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

#: Correlacion minima para fiarse del re-anclaje.
MIN_MATCH_SCORE = 0.80


@dataclass(frozen=True)
class AnchorResult:
    dx: int = 0
    dy: int = 0
    score: float = 0.0
    applied: bool = False
    reason: str = ""


def find_offset(haystack: Any, template: Any,
                min_score: float = MIN_MATCH_SCORE) -> AnchorResult:
    """Busca `template` dentro de `haystack` y devuelve el desplazamiento."""
    if cv2 is None or np is None:
        return AnchorResult(reason="OpenCV no disponible")
    if haystack is None or template is None:
        return AnchorResult(reason="imagen ausente")
    if template.shape[0] > haystack.shape[0] or template.shape[1] > haystack.shape[1]:
        return AnchorResult(reason="plantilla mayor que la ventana de busqueda")

    hay = cv2.cvtColor(haystack, cv2.COLOR_BGR2GRAY) if haystack.ndim == 3 else haystack
    tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if template.ndim == 3 else template
    result = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val < min_score:
        return AnchorResult(score=float(max_val), reason=f"correlacion baja ({max_val:.2f})")
    return AnchorResult(dx=int(max_loc[0]), dy=int(max_loc[1]), score=float(max_val), applied=True)


class AnchorTracker:
    """Mantiene la plantilla del ancla y calcula la correccion vigente."""

    def __init__(self, search_margin: int = 60, min_score: float = MIN_MATCH_SCORE) -> None:
        self.search_margin = int(search_margin)
        self.min_score = float(min_score)
        self.template: Optional[Any] = None
        self.template_rect: Optional[Rect] = None
        self.offset: Tuple[int, int] = (0, 0)
        self.last_result = AnchorResult(reason="sin ancla configurada")

    @property
    def has_template(self) -> bool:
        return self.template is not None and self.template_rect is not None

    def learn(self, image: Any, rect: Rect) -> None:
        """Guarda el recorte de referencia tal y como se ve ahora."""
        self.template = image
        self.template_rect = rect
        self.offset = (0, 0)
        self.last_result = AnchorResult(applied=True, score=1.0, reason="ancla aprendida")

    def search_rect(self) -> Optional[Rect]:
        if self.template_rect is None:
            return None
        return self.template_rect.expanded(self.search_margin)

    def update(self, search_image: Any) -> AnchorResult:
        """Recalcula el desplazamiento a partir de la ventana de busqueda."""
        if not self.has_template:
            self.last_result = AnchorResult(reason="sin ancla configurada")
            return self.last_result
        result = find_offset(search_image, self.template, self.min_score)
        if result.applied:
            # La plantilla estaba centrada a `search_margin` del borde.
            self.offset = (result.dx - self.search_margin, result.dy - self.search_margin)
        self.last_result = result
        return result

    def correct(self, rect: Rect) -> Rect:
        dx, dy = self.offset
        if dx == 0 and dy == 0:
            return rect
        return rect.translated(dx, dy)

    def reset(self) -> None:
        self.offset = (0, 0)
