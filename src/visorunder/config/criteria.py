"""Criterios de entrada: TUS parametros, no verdades estadisticas.

Estos valores son referencias operativas del usuario. La aplicacion no los
trata como probabilidades ni como recomendaciones: solo compara el ritmo que
haria falta para superar una linea contra los numeros que tu defines.

Viven en las preferencias de la aplicacion y no en el perfil de casa: el
perfil describe DONDE mirar en la pantalla (cambia con la casa y con la
resolucion), mientras que estos criterios son tuyos y valen igual en
Sportium que en BetPlay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict

#: Ritmo de referencia inicial, en puntos combinados por minuto.
#: Es un punto de partida configurable, NO una constante del baloncesto.
DEFAULT_REFERENCE_PACE = 4.00

#: Cuota UNDER que sueles buscar. Solo sirve para decidir que linea se enfoca
#: en la tarjeta grande cuando todavia no has elegido ninguna a mano.
DEFAULT_TARGET_UNDER_ODDS = 1.80


@dataclass
class EntryCriteria:
    """Parametros configurables del tablero de entrada."""

    #: pts/min de referencia con los que comparas el ritmo necesario.
    reference_pace: float = DEFAULT_REFERENCE_PACE

    #: Cuota UNDER objetivo: criterio de ENFOQUE VISUAL, jamas una
    #: recomendacion de apuesta ni un filtro que oculte lineas.
    target_under_odds: float = DEFAULT_TARGET_UNDER_ODDS

    # ------------------------------------------------------------- umbrales
    # Se aplican sobre el margen:  ritmo_necesario - ritmo_referencia
    # Margen alto  = superar la linea exige acelerar mucho.
    # Margen bajo  = la linea se supera incluso bajando el ritmo.
    threshold_very_demanding: float = 1.00   # margen >= -> MUY EXIGENTE
    threshold_demanding: float = 0.30        # margen >= -> EXIGENTE
    threshold_neutral: float = -0.30         # margen >= -> NEUTRO
    #                                          por debajo -> PELIGROSO

    #: Indicador INDEPENDIENTE. Marca el tramo final del ambito del mercado,
    #: pero NO altera el ritmo necesario, ni el margen, ni la clasificacion.
    final_stretch_seconds: int = 60
    show_final_stretch: bool = True

    #: Paleta configurable. Si `invert_palette` es True se intercambian el
    #: color favorable y el desfavorable, por si prefieres la lectura opuesta.
    palette: Dict[str, str] = field(default_factory=lambda: {
        "MUY_EXIGENTE": "#2ecc71",
        "EXIGENTE": "#7fd18a",
        "NEUTRO": "#ffbf3f",
        "PELIGROSO": "#ff5c5c",
        "NO_EVALUABLE": "#8b97a8",
    })
    invert_palette: bool = False

    # ------------------------------------------------------------ utilidades
    def validate(self) -> "EntryCriteria":
        """Corrige incoherencias evidentes sin inventar criterios nuevos."""
        self.reference_pace = max(0.1, float(self.reference_pace))
        self.target_under_odds = max(1.01, float(self.target_under_odds))
        # Los umbrales deben ir de mayor a menor para que la escala tenga sentido.
        umbrales = sorted(
            [self.threshold_very_demanding, self.threshold_demanding, self.threshold_neutral],
            reverse=True,
        )
        self.threshold_very_demanding, self.threshold_demanding, self.threshold_neutral = umbrales
        self.final_stretch_seconds = max(0, int(self.final_stretch_seconds))
        return self

    def color_for(self, level_name: str) -> str:
        if self.invert_palette:
            swap = {"MUY_EXIGENTE": "PELIGROSO", "EXIGENTE": "NEUTRO",
                    "NEUTRO": "EXIGENTE", "PELIGROSO": "MUY_EXIGENTE"}
            level_name = swap.get(level_name, level_name)
        return self.palette.get(level_name, "#8b97a8")

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EntryCriteria":
        criteria = EntryCriteria()
        for key, value in (data or {}).items():
            if hasattr(criteria, key):
                setattr(criteria, key, value)
        return criteria.validate()

    def describe(self) -> str:
        return (f"referencia {self.reference_pace:.2f} pts/min | "
                f"cuota objetivo {self.target_under_odds:.2f}")
