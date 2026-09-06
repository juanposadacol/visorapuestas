"""Perfiles de casa de apuestas (requisitos 3, 24 y 25).

Un perfil describe DONDE mirar en la pantalla para una casa concreta. La
aplicacion no esta programada para Sportium ni para ninguna otra: todas se
soportan igual porque todas son "un perfil mas".

Robustez ante cambios de posicion:
* los ROIs se guardan normalizados respecto a un marco de referencia;
* el marco se reescala si la resolucion actual difiere de la de configuracion;
* opcionalmente se re-ancla por correlacion de imagen (ver capture/anchor.py).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..capture.roi import NormalizedRect, Rect, Roi, RoiKind
from ..domain.market import MarketKey

#: Casas preconfiguradas por nombre. La geometria SIEMPRE la dibuja el usuario;
#: aqui solo se ofrecen los nombres para no obligar a teclearlos. El combo de
#: la interfaz sigue siendo editable, por lo que cualquier otra casa funciona.
KNOWN_SPORTSBOOKS: List[str] = [
    "Stake",
    "Sportium",
    "BetPlay",
    "Wplay",
    "RushBet",
    "Codere",
    "Betano",
    "bet365",
    "Betsson",
    "Rivalo",
    "Otra",
]


@dataclass
class ScreenContext:
    """Condiciones de pantalla en las que se configuro (o se ejecuta) el perfil."""

    width: int = 1920
    height: int = 1080
    dpi_scale: float = 1.0
    monitor_index: int = 1

    def as_dict(self) -> Dict[str, Any]:
        return {"width": self.width, "height": self.height,
                "dpi_scale": self.dpi_scale, "monitor_index": self.monitor_index}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ScreenContext":
        return ScreenContext(
            width=int(data.get("width", 1920)),
            height=int(data.get("height", 1080)),
            dpi_scale=float(data.get("dpi_scale", 1.0)),
            monitor_index=int(data.get("monitor_index", 1)),
        )

    def matches(self, other: "ScreenContext") -> bool:
        return (self.width, self.height) == (other.width, other.height) and \
            abs(self.dpi_scale - other.dpi_scale) < 0.01


@dataclass
class SportsbookProfile:
    """Configuracion completa de una casa."""

    name: str
    sportsbook: str = ""
    frame: Rect = field(default_factory=lambda: Rect(0, 0, 1920, 1080))
    screen: ScreenContext = field(default_factory=ScreenContext)
    rois: Dict[RoiKind, Roi] = field(default_factory=dict)
    rules_name: str = "FIBA"
    #: Mercado al que pertenecen las lineas cuando NO se lee el titulo del
    #: mercado en pantalla. Es una eleccion EXPLICITA del usuario, nunca una
    #: suposicion del programa (ver requisito 5).
    #: "GAME" | "CURRENT_QUARTER" | "Q1" | "Q2" | "Q3" | "Q4" | "H1" | "H2"
    default_market: str = "GAME"
    engine: str = "auto"
    reads_per_second: float = 3.0
    #: Cadencia de lectura del bloque de lineas. 0 = en cada ciclo, que es el
    #: valor por defecto porque el mercado es el objeto principal de analisis
    #: y un cambio de linea debe reflejarse cuanto antes. Bajarlo (p. ej. a
    #: 1.5) ahorra CPU en equipos justos a costa de reaccionar mas tarde.
    market_reads_per_second: float = 0.0
    stabilization_required: int = 3
    value_ttl_seconds: float = 3.0
    notes: str = ""
    profile_id: Optional[int] = None
    updated_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------ ROIs
    def set_roi(self, kind: RoiKind, rect: Rect, frame: Optional[Rect] = None) -> Roi:
        roi = Roi.create(kind, rect, frame or self.frame)
        self.rois[kind] = roi
        return roi

    def remove_roi(self, kind: RoiKind) -> None:
        self.rois.pop(kind, None)

    def get_roi(self, kind: RoiKind) -> Optional[Roi]:
        return self.rois.get(kind)

    def has(self, kind: RoiKind) -> bool:
        roi = self.rois.get(kind)
        return roi is not None and roi.enabled

    def missing_required(self) -> List[RoiKind]:
        """ROIs imprescindibles que faltan por configurar.

        Una region puede cubrir varias: el tablero completo aporta reloj,
        cuarto y marcador de una vez, asi que configurarlo evita tener que
        dibujar esas tres por separado.
        """
        cubiertas = set()
        for roi in self.rois:
            cubiertas.update(roi.covers)

        missing = [k for k in RoiKind
                   if k.is_required and not self.has(k) and k not in cubiertas]
        # El marcador puede venir por pareja, por equipo separado o del tablero.
        if (RoiKind.SCORE_PAIR not in cubiertas
                and not self.has(RoiKind.SCORE_PAIR)
                and not (self.has(RoiKind.SCORE_A) and self.has(RoiKind.SCORE_B))):
            missing.append(RoiKind.SCORE_PAIR)
        return missing

    @property
    def is_ready(self) -> bool:
        return not self.missing_required()

    # ---------------------------------------------------------------- marcos
    def resolve_frame(self, current: Optional[ScreenContext] = None,
                      override: Optional[Rect] = None) -> Rect:
        """Marco de referencia adaptado a la pantalla actual (requisito 25).

        Si la resolucion de ahora no es la de la configuracion, el marco se
        reescala proporcionalmente. Los ROIs, al ser fracciones del marco,
        acompanan el cambio sin tocarlos.
        """
        if override is not None:
            return override
        if current is None or current.matches(self.screen):
            return self.frame
        sx = current.width / max(1, self.screen.width)
        sy = current.height / max(1, self.screen.height)
        return Rect(
            x=int(round(self.frame.x * sx)),
            y=int(round(self.frame.y * sy)),
            width=max(1, int(round(self.frame.width * sx))),
            height=max(1, int(round(self.frame.height * sy))),
        )

    def resolve_rois(self, current: Optional[ScreenContext] = None,
                     override: Optional[Rect] = None) -> Dict[RoiKind, Rect]:
        frame = self.resolve_frame(current, override)
        return {kind: roi.resolve(frame) for kind, roi in self.rois.items() if roi.enabled}

    # --------------------------------------------------------- serializacion
    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "sportsbook": self.sportsbook,
            "frame": {"x": self.frame.x, "y": self.frame.y,
                      "width": self.frame.width, "height": self.frame.height},
            "screen": self.screen.as_dict(),
            "rois": [roi.as_dict() for roi in self.rois.values()],
            "rules_name": self.rules_name,
            "default_market": self.default_market,
            "engine": self.engine,
            "reads_per_second": self.reads_per_second,
            "market_reads_per_second": self.market_reads_per_second,
            "stabilization_required": self.stabilization_required,
            "value_ttl_seconds": self.value_ttl_seconds,
            "notes": self.notes,
            "updated_at": self.updated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)

    @staticmethod
    def from_dict(data: Dict[str, Any], profile_id: Optional[int] = None) -> "SportsbookProfile":
        frame = data.get("frame", {})
        profile = SportsbookProfile(
            name=data["name"],
            sportsbook=data.get("sportsbook", ""),
            frame=Rect(int(frame.get("x", 0)), int(frame.get("y", 0)),
                       int(frame.get("width", 1920)), int(frame.get("height", 1080))),
            screen=ScreenContext.from_dict(data.get("screen", {})),
            rules_name=data.get("rules_name", "FIBA"),
            default_market=data.get("default_market", "GAME"),
            engine=data.get("engine", "auto"),
            reads_per_second=float(data.get("reads_per_second", 3.0)),
            market_reads_per_second=float(data.get("market_reads_per_second", 1.5)),
            stabilization_required=int(data.get("stabilization_required", 3)),
            value_ttl_seconds=float(data.get("value_ttl_seconds", 3.0)),
            notes=data.get("notes", ""),
            profile_id=profile_id,
            updated_at=float(data.get("updated_at", time.time())),
        )
        for roi_data in data.get("rois", []):
            roi = Roi.from_dict(roi_data)
            profile.rois[roi.kind] = roi
        return profile

    @staticmethod
    def from_json(text: str, profile_id: Optional[int] = None) -> "SportsbookProfile":
        return SportsbookProfile.from_dict(json.loads(text), profile_id)


#: Opciones del mercado por defecto, con su etiqueta para la interfaz.
DEFAULT_MARKET_CHOICES = [
    ("GAME", "Partido - Total de puntos"),
    ("CURRENT_QUARTER", "El cuarto que se este jugando"),
    ("Q1", "1.er cuarto - Total de puntos"),
    ("Q2", "2.o cuarto - Total de puntos"),
    ("Q3", "3.er cuarto - Total de puntos"),
    ("Q4", "4.o cuarto - Total de puntos"),
    ("H1", "1.a mitad - Total de puntos"),
    ("H2", "2.a mitad - Total de puntos"),
]


def resolve_default_market(choice: str, current_period: Optional[int]) -> Optional[MarketKey]:
    """Traduce la opcion elegida por el usuario en un MarketKey concreto.

    Devuelve None cuando la opcion depende del cuarto en juego y este todavia
    no se conoce: en ese caso las lineas se quedan sin publicar, que es
    preferible a atribuirlas a un mercado equivocado.
    """
    choice = (choice or "GAME").upper()
    if choice == "GAME":
        return MarketKey.game()
    if choice == "CURRENT_QUARTER":
        return MarketKey.quarter(current_period) if current_period else None
    if choice.startswith("Q") and choice[1:].isdigit():
        return MarketKey.quarter(int(choice[1:]))
    if choice.startswith("H") and choice[1:].isdigit():
        return MarketKey.half_market(int(choice[1:]))
    return MarketKey.game()
