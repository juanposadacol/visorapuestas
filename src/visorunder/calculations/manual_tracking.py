"""Seguimiento EN VIVO de una apuesta introducida a mano.

Una apuesta manual no es una linea del historial: es una posicion abierta que
hay que vigilar mientras el partido corre. Este modulo responde, en cada
lectura y para cada apuesta:

    "Cuantos puntos lleva SU mercado, cuanto margen le queda, cuantos puntos
     mas hacen cruzar la linea, que proyecta el ritmo actual y de que lado de
     la linea cae esa proyeccion."

REUTILIZA EL MOTOR QUE YA EXISTE. No hay una segunda matematica:

* `market_scope.resolve` decide QUE puntos y QUE tiempo aplican al mercado de
  la apuesta. Q4 usa los puntos del Q4, 1H usa Q1+Q2, PARTIDO usa el total.
  Anadir un mercado no toca este archivo.
* `metrics.compute_bet_metrics` calcula umbral, puntos que faltan para
  superar la linea, ritmo actual y ritmo necesario. Es exactamente la misma
  funcion que usa el radar y la apuesta fijada, asi que las tres vistas no
  pueden discrepar.

Lo unico propio de aqui es traducir ese estado al vocabulario de quien
apuesta: margen, puntos que todavia caben, puntos que cruzan y proyeccion.

MARGEN Y PUNTOS NO SON LO MISMO
-------------------------------
Con UNDER 40.5 y 32 puntos anotados:

    margen                  = 40.5 - 32 = 8.5   (distancia, con decimales)
    puntos que todavia caben= floor(40.5) - 32 = 8    -> se acabaria en 40
    puntos que cruzan       = floor(40.5) - 32 + 1 = 9 -> se acabaria en 41

El margen es una distancia; los otros dos son puntos ENTEROS, que es lo unico
que puede anotar un equipo. Confundirlos es decir "me quedan 8.5 puntos".

Las formulas no suponen que la linea acabe en .5: se derivan de
`floor(linea)`, asi que una linea entera funciona igual y ademas aparece su
zona de EMPATE (terminar exactamente en la linea devuelve el dinero).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..domain.game_state import GameState, PointsSource
from ..domain.manual_bet import ManualBet
from ..domain.market import MarketKey, Side
from .metrics import (
    BetMetrics,
    compute_bet_metrics,
    points_per_minute,
    projected_points_remaining,
)


class TrackingStatus(str, Enum):
    """Estado de UNA apuesta frente al partido, ahora mismo."""

    #: Falta marcador, reloj o el cuarto: no se inventa nada.
    NO_DATA = "NO_DATA"
    #: El mercado todavia no ha empezado (linea de un cuarto futuro).
    NOT_STARTED = "NOT_STARTED"
    #: La proyeccion del ambito cae del lado de la apuesta.
    FAVORABLE = "FAVORABLE"
    #: La proyeccion cae del lado contrario: todavia se juega, pero va en contra.
    AT_RISK = "AT_RISK"
    #: La linea ya quedo superada. Es un hecho: no se puede deshacer.
    EXCEEDED = "EXCEEDED"
    #: El ambito termino y la apuesta gano.
    WON = "WON"
    #: El ambito termino y la apuesta perdio.
    LOST = "LOST"
    #: El ambito termino exactamente en la linea (solo lineas enteras).
    PUSH = "PUSH"

    @property
    def label(self) -> str:
        return {
            TrackingStatus.NO_DATA: "SIN DATOS",
            TrackingStatus.NOT_STARTED: "SIN EMPEZAR",
            TrackingStatus.FAVORABLE: "FAVORABLE",
            TrackingStatus.AT_RISK: "EN RIESGO",
            TrackingStatus.EXCEEDED: "SUPERADA",
            TrackingStatus.WON: "GANADA",
            TrackingStatus.LOST: "PERDIDA",
            TrackingStatus.PUSH: "NULA (empate)",
        }[self]

    @property
    def is_decided(self) -> bool:
        """True si el resultado deportivo ya no puede cambiar."""
        return self in (TrackingStatus.WON, TrackingStatus.LOST,
                        TrackingStatus.PUSH, TrackingStatus.EXCEEDED)


# --------------------------------------------------------------------------
# Aritmetica de la linea
# --------------------------------------------------------------------------
def margin_to_line(line: float, current_points: Optional[int]) -> Optional[float]:
    """Distancia entre la linea y los puntos anotados.

    Es una DISTANCIA, con decimales, no una cantidad de puntos anotables.

    >>> margin_to_line(40.5, 32)
    8.5
    >>> margin_to_line(40.5, 44)
    -3.5
    >>> margin_to_line(40.5, None) is None
    True
    """
    if current_points is None:
        return None
    return float(line) - int(current_points)


def tolerable_points(line: float, current_points: Optional[int]) -> Optional[int]:
    """Puntos ENTEROS que todavia caben sin que la linea quede superada.

        max(0, floor(linea) - puntos_actuales)

    >>> tolerable_points(40.5, 32)   # puede llegar a 40 y el UNDER aguanta
    8
    >>> tolerable_points(40.5, 40)   # el siguiente punto ya la supera
    0
    >>> tolerable_points(40.5, 44)   # ya superada
    0
    """
    if current_points is None:
        return None
    return max(0, math.floor(float(line)) - int(current_points))


def push_points(line: float, current_points: Optional[int]) -> Optional[int]:
    """Puntos que dejarian el ambito EXACTAMENTE en la linea (empate).

    Solo existe cuando la linea es entera: con .5 nunca hay empate.

    >>> push_points(40.0, 32)
    8
    >>> push_points(40.5, 32) is None
    True
    """
    valor = float(line)
    if valor != int(valor) or current_points is None:
        return None
    return max(0, int(valor) - int(current_points))


def projected_scope_points(current_points: Optional[int],
                           elapsed_seconds: Optional[int],
                           remaining_seconds: Optional[int]) -> Optional[float]:
    """Proyeccion lineal del total del ambito al ritmo observado.

        proyeccion = puntos_actuales + ritmo_actual x minutos_restantes

    Es una proyeccion de PRESENTACION, igual que las del panel principal: dice
    a donde llevaria el ritmo actual, no lo que va a pasar. Si falta el ritmo
    o el tiempo restante devuelve None; nunca un numero inventado.
    """
    if current_points is None:
        return None
    pace = points_per_minute(current_points, elapsed_seconds)
    extra = projected_points_remaining(pace, remaining_seconds)
    if extra is None:
        return None
    return float(current_points) + extra


# --------------------------------------------------------------------------
# Resultado del seguimiento
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ManualBetTracking:
    """Todo lo que hay que ensenar de UNA apuesta manual en vivo.

    Cada apuesta se calcula contra SU mercado y SU linea. Dos apuestas del
    mismo partido en casas distintas, o en mercados distintos, no comparten
    ningun dato derivado: solo el estado del partido.
    """

    bet: ManualBet
    #: Metricas crudas, las mismas que usan el radar y la apuesta fijada.
    metrics: Optional[BetMetrics] = None

    # --- ambito resuelto por el mercado de la apuesta
    scope_points: Optional[int] = None
    scope_elapsed_seconds: Optional[int] = None
    scope_remaining_seconds: Optional[int] = None
    points_source: PointsSource = PointsSource.UNKNOWN

    # --- aritmetica de la linea
    margin: Optional[float] = None
    tolerable_points: Optional[int] = None
    points_to_cross: Optional[int] = None
    push_points: Optional[int] = None
    exceed_threshold: Optional[int] = None
    exceeded: Optional[bool] = None

    # --- ritmo y proyeccion
    current_pace: Optional[float] = None
    required_pace: Optional[float] = None
    projection: Optional[float] = None
    projection_vs_line: Optional[float] = None

    status: TrackingStatus = TrackingStatus.NO_DATA
    #: Por que no se puede evaluar, cuando corresponde. Vacio si todo esta bien.
    unavailable_reason: str = ""
    settled: bool = False
    started: bool = True

    # ---------------------------------------------------------------- atajos
    @property
    def key(self) -> MarketKey:
        return self.bet.key

    @property
    def side(self) -> Side:
        return self.bet.side

    @property
    def line(self) -> float:
        return self.bet.line

    @property
    def sportsbook(self) -> str:
        return self.bet.sportsbook

    @property
    def market_label(self) -> str:
        return self.bet.key.label.replace(" - Total de puntos", "")

    @property
    def description(self) -> str:
        return f"{self.bet.side.value} {self.bet.line:g}"

    @property
    def is_live(self) -> bool:
        """True si hay datos suficientes para seguirla ahora mismo."""
        return self.status not in (TrackingStatus.NO_DATA, TrackingStatus.NOT_STARTED)

    def describe_margin(self) -> str:
        """Frase inequivoca que separa margen de puntos enteros."""
        if self.margin is None or self.points_to_cross is None:
            return "Sin datos del mercado todavia."
        if self.side is Side.UNDER:
            return (
                f"Margen hasta la linea: {self.margin:+.1f}   |   "
                f"caben {self.tolerable_points} puntos mas   |   "
                f"con {self.points_to_cross} se supera la linea"
            )
        return (
            f"Margen hasta la linea: {self.margin:+.1f}   |   "
            f"faltan {self.points_to_cross} puntos para superarla"
        )


# --------------------------------------------------------------------------
# Calculo
# --------------------------------------------------------------------------
def _resolve_status(side: Side, line: float, points: Optional[int],
                    exceeded: Optional[bool], settled: bool, started: bool,
                    projection: Optional[float]) -> TrackingStatus:
    """Traduce el estado observado a una etiqueta, sin inventar nada."""
    if points is None or exceeded is None:
        return TrackingStatus.NO_DATA
    if not started:
        return TrackingStatus.NOT_STARTED

    if settled:
        # El ambito termino: el resultado es un hecho, no una estimacion.
        if exceeded:
            return TrackingStatus.WON if side is Side.OVER else TrackingStatus.LOST
        if float(points) == float(line):
            return TrackingStatus.PUSH
        return TrackingStatus.LOST if side is Side.OVER else TrackingStatus.WON

    if exceeded:
        # Superar la linea es irreversible dentro del ambito: los puntos no
        # se descuentan. Para un OVER eso ya es ganar; para un UNDER, perder.
        return TrackingStatus.EXCEEDED

    if projection is None:
        # Hay marcador pero no hay ritmo ni reloj utilizable: se sigue la
        # apuesta con los puntos, sin fingir una proyeccion.
        return TrackingStatus.FAVORABLE if side is Side.UNDER else TrackingStatus.AT_RISK

    if side is Side.UNDER:
        return TrackingStatus.FAVORABLE if projection < line else TrackingStatus.AT_RISK
    return TrackingStatus.FAVORABLE if projection > line else TrackingStatus.AT_RISK


def _unavailable_reason(metrics: BetMetrics) -> str:
    if metrics.scope_points is None:
        return "ESPERANDO MARCADOR DEL MERCADO"
    if metrics.scope_remaining_seconds is None:
        return "ESPERANDO RELOJ"
    return ""


def track_manual_bet(state: GameState, bet: ManualBet) -> ManualBetTracking:
    """Calcula el seguimiento de UNA apuesta manual contra el partido en vivo.

    El mercado de la apuesta decide el ambito; la casa no interviene en el
    calculo. Por eso una apuesta de Stake se sigue con el marcador que llega
    por el DOM de BetPlay: el partido es el mismo, solo cambian linea y cuota.
    """
    m = compute_bet_metrics(state, bet.key, bet.line, bet.odds, bet.side)

    proyeccion = projected_scope_points(
        m.scope_points, m.scope_elapsed_seconds, m.scope_remaining_seconds)
    diferencia = None if proyeccion is None else proyeccion - float(bet.line)

    estado = _resolve_status(
        side=bet.side, line=bet.line, points=m.scope_points, exceeded=m.exceeded,
        settled=m.settled, started=m.started, projection=proyeccion)

    return ManualBetTracking(
        bet=bet,
        metrics=m,
        scope_points=m.scope_points,
        scope_elapsed_seconds=m.scope_elapsed_seconds,
        scope_remaining_seconds=m.scope_remaining_seconds,
        points_source=m.scope_points_source,
        margin=margin_to_line(bet.line, m.scope_points),
        tolerable_points=tolerable_points(bet.line, m.scope_points),
        points_to_cross=m.points_to_exceed,
        push_points=push_points(bet.line, m.scope_points),
        exceed_threshold=m.exceed_threshold,
        exceeded=m.exceeded,
        current_pace=m.current_pace,
        required_pace=m.required_pace,
        projection=proyeccion,
        projection_vs_line=diferencia,
        status=estado,
        unavailable_reason=_unavailable_reason(m),
        settled=m.settled,
        started=m.started,
    )


def track_manual_bets(state: Optional[GameState], bets) -> list:
    """Seguimiento de VARIAS apuestas a la vez, cada una por su cuenta.

    Sin partido en vivo devuelve el seguimiento vacio de cada apuesta: la
    tabla sigue mostrando casa, mercado, linea y cuota, y las columnas de
    seguimiento quedan como no disponibles en lugar de inventarse.
    """
    if state is None:
        return [ManualBetTracking(bet=b, unavailable_reason="SIN PARTIDO EN VIVO")
                for b in bets]
    return [track_manual_bet(state, b) for b in bets]


def suggested_status(tracking: ManualBetTracking):
    """Resultado que el sistema puede afirmar con seguridad, o None.

    Solo se propone liquidar cuando el ambito del mercado TERMINO de verdad
    (o cuando la linea quedo superada, que ya es irreversible). Mientras el
    mercado siga vivo no se marca nada: el objetivo es el seguimiento, y una
    apuesta no se da por ganada porque la proyeccion pinte bien.
    """
    from ..domain.manual_bet import ManualBetStatus

    if tracking.status is TrackingStatus.WON:
        return ManualBetStatus.WON
    if tracking.status is TrackingStatus.LOST:
        return ManualBetStatus.LOST
    if tracking.status is TrackingStatus.PUSH:
        return ManualBetStatus.VOID
    if tracking.status is TrackingStatus.EXCEEDED:
        # Superada es definitivo dentro del ambito: el UNDER ya no se salva y
        # el OVER ya no se pierde, aunque queden minutos por jugar.
        return (ManualBetStatus.WON if tracking.side is Side.OVER
                else ManualBetStatus.LOST)
    return None
