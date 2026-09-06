"""Regiones de interes (requisitos 3, 24 y 25).

Las coordenadas NO se guardan en pixeles absolutos. Se guardan como
FRACCIONES de un marco de referencia (normalmente la ventana del navegador o
el monitor completo). Ventajas:

* la misma configuracion sirve en 1920x1080 y en 2560x1440;
* sobrevive a cambios de escala de Windows (100/125/150 %);
* si el navegador se mueve, basta con reajustar el marco, no los 8 ROIs.

Ademas un perfil puede guardar un ROI de ANCLA: un recorte de imagen estable
(por ejemplo el logo del marcador) que permite recolocar todo el conjunto por
correlacion cuando la pagina se desplaza unos pixeles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class RoiKind(str, Enum):
    """Que representa cada region. Determina el parser que se le aplica."""

    SCORE_A = "SCORE_A"
    SCORE_B = "SCORE_B"
    SCORE_PAIR = "SCORE_PAIR"          # los dos marcadores en un solo recorte
    PERIOD = "PERIOD"
    CLOCK = "CLOCK"
    MARKET_LABEL = "MARKET_LABEL"      # "3.er Cuarto - Total de puntos"
    MARKET_BLOCK = "MARKET_BLOCK"      # lineas + cuotas OVER/UNDER
    LINES = "LINES"                    # solo la columna de lineas
    OVER_ODDS = "OVER_ODDS"
    UNDER_ODDS = "UNDER_ODDS"
    TEAM_A = "TEAM_A"
    TEAM_B = "TEAM_B"
    BREAKDOWN_A = "BREAKDOWN_A"        # desglose por cuartos del equipo A
    BREAKDOWN_B = "BREAKDOWN_B"
    #: Tablero superior COMPLETO, con encabezados y las dos filas de equipo.
    #: Pensado para casas cuyo tablero cambia de columnas durante el partido
    #: (Stake anade una columna al empezar cada cuarto): al leerlo entero, el
    #: parser localiza cada columna por su encabezado y la region no se queda
    #: obsoleta. De aqui salen equipos, cuarto, reloj, parciales y totales.
    SCOREBOARD = "SCOREBOARD"
    ANCHOR = "ANCHOR"                  # recorte estable para re-anclar

    @property
    def display_name(self) -> str:
        return _ROI_LABELS[self]

    @property
    def is_required(self) -> bool:
        """ROIs sin los cuales la V1 no puede funcionar."""
        return self in (RoiKind.CLOCK, RoiKind.PERIOD, RoiKind.MARKET_BLOCK)

    @property
    def content_type(self) -> str:
        """'digits' o 'text': orienta el preprocesado y el motor OCR."""
        if self in (RoiKind.SCORE_A, RoiKind.SCORE_B, RoiKind.SCORE_PAIR,
                    RoiKind.CLOCK, RoiKind.LINES, RoiKind.OVER_ODDS,
                    RoiKind.UNDER_ODDS, RoiKind.BREAKDOWN_A, RoiKind.BREAKDOWN_B):
            return "digits"
        # El tablero mezcla nombres de equipo, encabezados y numeros: es texto.
        return "text"

    @property
    def covers(self) -> tuple:
        """Que datos aporta esta region por si sola.

        El tablero completo cubre reloj, cuarto y marcador de una vez, asi que
        configurarlo evita tener que dibujar esas tres regiones por separado.
        """
        if self is RoiKind.SCOREBOARD:
            return (RoiKind.CLOCK, RoiKind.PERIOD, RoiKind.SCORE_PAIR,
                    RoiKind.TEAM_A, RoiKind.TEAM_B,
                    RoiKind.BREAKDOWN_A, RoiKind.BREAKDOWN_B)
        return ()


_ROI_LABELS: Dict[RoiKind, str] = {
    RoiKind.SCORE_A: "Marcador equipo A",
    RoiKind.SCORE_B: "Marcador equipo B",
    RoiKind.SCORE_PAIR: "Marcador (ambos equipos)",
    RoiKind.PERIOD: "Cuarto",
    RoiKind.CLOCK: "Reloj",
    RoiKind.MARKET_LABEL: "Titulo del mercado",
    RoiKind.MARKET_BLOCK: "Bloque de lineas y cuotas",
    RoiKind.LINES: "Columna de lineas",
    RoiKind.OVER_ODDS: "Cuotas OVER",
    RoiKind.UNDER_ODDS: "Cuotas UNDER",
    RoiKind.TEAM_A: "Nombre equipo A",
    RoiKind.TEAM_B: "Nombre equipo B",
    RoiKind.BREAKDOWN_A: "Desglose por cuartos equipo A",
    RoiKind.BREAKDOWN_B: "Desglose por cuartos equipo B",
    RoiKind.SCOREBOARD: "Tablero completo / marcador dinamico",
    RoiKind.ANCHOR: "Ancla de referencia",
}


@dataclass(frozen=True)
class Rect:
    """Rectangulo en pixeles absolutos de la pantalla virtual."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def to_mss(self) -> Dict[str, int]:
        return {"left": self.x, "top": self.y, "width": self.width, "height": self.height}

    def normalized(self) -> Tuple[int, int, int, int]:
        """Normaliza rectangulos dibujados de derecha a izquierda."""
        x = min(self.x, self.x + self.width)
        y = min(self.y, self.y + self.height)
        return (x, y, abs(self.width), abs(self.height))

    @staticmethod
    def from_points(x1: int, y1: int, x2: int, y2: int) -> "Rect":
        return Rect(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

    def clamp_to(self, frame: "Rect") -> "Rect":
        x = max(frame.x, min(self.x, frame.right))
        y = max(frame.y, min(self.y, frame.bottom))
        w = max(0, min(self.width, frame.right - x))
        h = max(0, min(self.height, frame.bottom - y))
        return Rect(x, y, w, h)

    def expanded(self, margin: int) -> "Rect":
        return Rect(self.x - margin, self.y - margin,
                    self.width + 2 * margin, self.height + 2 * margin)

    def translated(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.width, self.height)


@dataclass(frozen=True)
class NormalizedRect:
    """Rectangulo expresado como fraccion (0..1) del marco de referencia."""

    fx: float
    fy: float
    fw: float
    fh: float

    def to_rect(self, frame: Rect) -> Rect:
        return Rect(
            x=int(round(frame.x + self.fx * frame.width)),
            y=int(round(frame.y + self.fy * frame.height)),
            width=max(1, int(round(self.fw * frame.width))),
            height=max(1, int(round(self.fh * frame.height))),
        )

    @staticmethod
    def from_rect(rect: Rect, frame: Rect) -> "NormalizedRect":
        if frame.width <= 0 or frame.height <= 0:
            raise ValueError("marco de referencia invalido")
        return NormalizedRect(
            fx=(rect.x - frame.x) / frame.width,
            fy=(rect.y - frame.y) / frame.height,
            fw=rect.width / frame.width,
            fh=rect.height / frame.height,
        )

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class OcrHints:
    """Ajustes de preprocesado y OCR especificos de un ROI."""

    scale: float = 3.0            # ampliacion antes de reconocer texto pequeno
    invert: bool = False          # texto claro sobre fondo oscuro
    threshold: str = "adaptive"   # "none" | "otsu" | "adaptive"
    denoise: bool = True
    engine: str = ""              # vacio = motor por defecto del perfil
    whitelist: str = ""           # caracteres permitidos (motores que lo soporten)
    psm: int = 7                  # una sola linea de texto (Tesseract)
    roi_kind: str = ""            # que region es: lo usan los motores simulados
    #: True si el recorte contiene UNA sola linea de texto. Permite saltarse la
    #: deteccion de texto del motor, que es con diferencia la etapa mas cara.
    single_line: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def for_kind(kind: RoiKind) -> "OcrHints":
        if kind is RoiKind.CLOCK:
            return OcrHints(scale=3.0, whitelist="0123456789:.", psm=7,
                            roi_kind=kind.value, single_line=True)
        if kind in (RoiKind.SCORE_A, RoiKind.SCORE_B):
            return OcrHints(scale=3.0, whitelist="0123456789", psm=7,
                            roi_kind=kind.value, single_line=True)
        if kind is RoiKind.SCORE_PAIR:
            return OcrHints(scale=3.0, whitelist="0123456789-: ", psm=7,
                            roi_kind=kind.value, single_line=True)
        if kind in (RoiKind.MARKET_BLOCK, RoiKind.LINES, RoiKind.OVER_ODDS,
                    RoiKind.UNDER_ODDS, RoiKind.BREAKDOWN_A, RoiKind.BREAKDOWN_B):
            # Varias filas: aqui si hace falta la deteccion de texto.
            return OcrHints(scale=2.0, psm=6, roi_kind=kind.value, single_line=False)
        if kind is RoiKind.SCOREBOARD:
            # Bloque grande con encabezados, nombres y numeros. Sin lista
            # blanca: las palabras del encabezado son las que identifican las
            # columnas, y recortarlas dejaria el tablero sin referencia.
            return OcrHints(scale=2.0, psm=6, roi_kind=kind.value, single_line=False)
        return OcrHints(scale=2.0, psm=7, roi_kind=kind.value, single_line=True)


@dataclass
class Roi:
    """Una region configurada dentro de un perfil."""

    kind: RoiKind
    rect: NormalizedRect
    label: str = ""
    enabled: bool = True
    hints: OcrHints = field(default_factory=OcrHints)

    def resolve(self, frame: Rect) -> Rect:
        return self.rect.to_rect(frame)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "rect": self.rect.as_dict(),
            "label": self.label,
            "enabled": self.enabled,
            "hints": self.hints.as_dict(),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Roi":
        return Roi(
            kind=RoiKind(data["kind"]),
            rect=NormalizedRect(**data["rect"]),
            label=data.get("label", ""),
            enabled=bool(data.get("enabled", True)),
            hints=OcrHints(**data.get("hints", {})),
        )

    @staticmethod
    def create(kind: RoiKind, rect: Rect, frame: Rect) -> "Roi":
        return Roi(
            kind=kind,
            rect=NormalizedRect.from_rect(rect, frame),
            label=kind.display_name,
            hints=OcrHints.for_kind(kind),
        )
