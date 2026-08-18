"""Clasificacion de senales de entrada.

La senal responde a UNA pregunta: cuanto se aleja el ritmo que haria falta
para superar la linea del ritmo de referencia que tu has definido.

    margen = ritmo_necesario - ritmo_referencia

Margen alto  -> superar la linea exigiria acelerar mucho  -> MUY EXIGENTE
Margen bajo  -> la linea se supera incluso bajando el ritmo -> PELIGROSO

Reglas que este modulo respeta de forma estricta:

* NO hay heuristicas ocultas. La clasificacion depende solo del margen y de
  los umbrales configurables. Que queden pocos puntos o poco tiempo NO
  cambia la senal: eso se informa aparte con el indicador TRAMO FINAL.
* NO afirma que una apuesta vaya a ganar. Es una escala matematica.
* Si falta algun dato, la senal es NO EVALUABLE, nunca una senal parcial.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

from ..config.criteria import EntryCriteria


class SignalLevel(str, Enum):
    """Escala de senal, de mas favorable a mas peligrosa para un UNDER."""

    MUY_EXIGENTE = "MUY_EXIGENTE"
    EXIGENTE = "EXIGENTE"
    NEUTRO = "NEUTRO"
    PELIGROSO = "PELIGROSO"
    NO_EVALUABLE = "NO_EVALUABLE"

    @property
    def label(self) -> str:
        """Etiqueta textual: la interfaz NUNCA depende solo del color."""
        return {
            SignalLevel.MUY_EXIGENTE: "MUY EXIGENTE",
            SignalLevel.EXIGENTE: "EXIGENTE",
            SignalLevel.NEUTRO: "NEUTRO",
            SignalLevel.PELIGROSO: "PELIGROSO",
            SignalLevel.NO_EVALUABLE: "NO EVALUABLE",
        }[self]

    @property
    def explanation(self) -> str:
        return {
            SignalLevel.MUY_EXIGENTE:
                "superar la linea exigiria un ritmo muy superior a tu referencia",
            SignalLevel.EXIGENTE:
                "superar la linea exigiria un ritmo superior a tu referencia",
            SignalLevel.NEUTRO:
                "el ritmo necesario esta cerca de tu referencia",
            SignalLevel.PELIGROSO:
                "la linea se superaria con un ritmo inferior a tu referencia",
            SignalLevel.NO_EVALUABLE:
                "faltan datos confirmados para calcular esta linea",
        }[self]

    @property
    def is_evaluable(self) -> bool:
        return self is not SignalLevel.NO_EVALUABLE


def classify(margin: Optional[float], criteria: EntryCriteria) -> SignalLevel:
    """Clasifica un margen segun los umbrales configurados.

    `margin` None -> NO EVALUABLE. Un margen infinito (no queda tiempo para
    anotar los puntos que faltan) es legitimamente el caso mas exigente.
    """
    if margin is None:
        return SignalLevel.NO_EVALUABLE
    if math.isnan(margin):
        return SignalLevel.NO_EVALUABLE
    if margin >= criteria.threshold_very_demanding:
        return SignalLevel.MUY_EXIGENTE
    if margin >= criteria.threshold_demanding:
        return SignalLevel.EXIGENTE
    if margin >= criteria.threshold_neutral:
        return SignalLevel.NEUTRO
    return SignalLevel.PELIGROSO


def color_for(level: SignalLevel, criteria: EntryCriteria) -> str:
    return criteria.color_for(level.value)


def is_final_stretch(remaining_seconds: Optional[int], criteria: EntryCriteria) -> bool:
    """Indicador INDEPENDIENTE del tramo final del ambito del mercado.

    Solo informa. No toca el ritmo necesario, ni el margen, ni la senal.
    """
    if not criteria.show_final_stretch or remaining_seconds is None:
        return False
    if criteria.final_stretch_seconds <= 0:
        return False
    return 0 <= remaining_seconds <= criteria.final_stretch_seconds
