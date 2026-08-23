"""Motor de deteccion de entrada: el nucleo funcional de la aplicacion.

Responde, para CADA linea que la casa ofrece ahora mismo:

    "Dada esta linea, los puntos que ya se anotaron y el tiempo que queda,
     que ritmo tendrian que mantener desde este instante para superarla, y
     como se compara con mi referencia y con el ritmo real del juego?"

No escoge la apuesta. No proyecta el resultado final. No calcula
probabilidades. Transforma datos cambiantes en numeros comparables.

Todas las lineas se evaluan a la vez, cada una contra SU mercado: una linea
del Q3 se calcula con los puntos y el tiempo del Q3 aunque se este jugando
el Q2 (lo resuelve `market_scope`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from ..config.criteria import EntryCriteria
from ..domain.bet import LockedBet
from ..domain.event_markets import EventMarkets, FreshnessState, MarketState
from ..domain.game_state import GameState, PointsSource
from ..domain.market import MarketKey, MarketLine, MarketSnapshot, MarketType, Side
from ..domain.rules import GameRules
from .metrics import BetMetrics, GeneralMetrics, compute_bet_metrics
from .signals import SignalLevel, classify, is_final_stretch


@dataclass(frozen=True)
class LineEvaluation:
    """Todo lo que hay que saber de UNA linea en este instante."""

    line: MarketLine
    key: MarketKey

    # --- ambito resuelto por el mercado
    scope_points: Optional[int] = None
    scope_elapsed_seconds: Optional[int] = None
    scope_remaining_seconds: Optional[int] = None
    points_source: PointsSource = PointsSource.UNKNOWN
    started: bool = True
    settled: bool = False

    # --- calculo central
    exceed_threshold: Optional[int] = None
    points_to_exceed: Optional[int] = None
    current_pace: Optional[float] = None
    required_pace: Optional[float] = None
    exceeded: Optional[bool] = None

    # --- comparaciones
    margin_vs_reference: Optional[float] = None
    margin_vs_period_pace: Optional[float] = None
    margin_vs_half_pace: Optional[float] = None
    margin_vs_game_pace: Optional[float] = None

    # --- lectura rapida
    signal: SignalLevel = SignalLevel.NO_EVALUABLE
    unavailable_reason: str = ""
    final_stretch: bool = False
    under_review: bool = False

    @property
    def under_odds(self) -> Optional[float]:
        return self.line.under_odds

    @property
    def over_odds(self) -> Optional[float]:
        return self.line.over_odds

    @property
    def line_value(self) -> float:
        return self.line.line

    @property
    def is_evaluable(self) -> bool:
        return self.signal.is_evaluable

    def describe_under(self) -> str:
        odds = f"{self.under_odds:.2f}" if self.under_odds is not None else "--"
        return f"UNDER {self.line_value:g} @ {odds}"


def _unavailable_reason(key: MarketKey, m: BetMetrics, state: GameState) -> str:
    """Explica en lenguaje claro por que una linea no se puede evaluar.

    Requisito acordado: la linea queda NO EVALUABLE con su motivo visible, sin
    senal parcial y sin datos inventados; y esto es POR LINEA, de modo que un
    mercado de partido puede seguir operativo mientras el de un cuarto no lo
    este.
    """
    rules: GameRules = state.rules
    if m.scope_points is None:
        if key.market_type is MarketType.QUARTER_TOTAL:
            if state.period_value is None:
                return "FALTA CONFIRMAR EL CUARTO EN JUEGO"
            return f"FALTA MARCADOR INICIAL {rules.label(key.period)}"
        if key.market_type is MarketType.HALF_TOTAL:
            return f"FALTA MARCADOR INICIAL {key.half}H"
        return "MARCADOR NO CONFIRMADO"
    if m.scope_remaining_seconds is None:
        return "RELOJ NO CONFIRMADO"
    return ""


def evaluate_line(state: GameState, line: MarketLine, criteria: EntryCriteria,
                  general: Optional[GeneralMetrics] = None,
                  under_review: bool = False) -> LineEvaluation:
    """Evalua una linea concreta contra el estado actual del partido."""
    key = line.key
    # El calculo base (ambito, umbral, puntos que faltan y ritmo necesario) es
    # el mismo que usa el seguimiento de una apuesta: se reutiliza en vez de
    # reimplementarlo, para que las dos vistas no puedan divergir jamas.
    m = compute_bet_metrics(state, key, line.line, line.under_odds, Side.UNDER)
    reason = _unavailable_reason(key, m, state)
    pace = m.required_pace

    margin_reference: Optional[float] = None
    margin_period: Optional[float] = None
    margin_half: Optional[float] = None
    margin_game: Optional[float] = None
    if pace is not None:
        margin_reference = pace - criteria.reference_pace
        if general is not None and general.period_pace is not None:
            margin_period = pace - general.period_pace
        if general is not None and general.half_pace is not None:
            margin_half = pace - general.half_pace
        if general is not None and general.game_pace is not None:
            margin_game = pace - general.game_pace

    if reason or under_review:
        signal = SignalLevel.NO_EVALUABLE
    else:
        signal = classify(margin_reference, criteria)

    return LineEvaluation(
        line=line,
        key=key,
        scope_points=m.scope_points,
        scope_elapsed_seconds=m.scope_elapsed_seconds,
        scope_remaining_seconds=m.scope_remaining_seconds,
        points_source=m.scope_points_source,
        started=m.started,
        settled=m.settled,
        exceed_threshold=m.exceed_threshold,
        points_to_exceed=m.points_to_exceed,
        current_pace=m.current_pace,
        required_pace=pace,
        exceeded=m.exceeded,
        margin_vs_reference=margin_reference,
        margin_vs_period_pace=margin_period,
        margin_vs_half_pace=margin_half,
        margin_vs_game_pace=margin_game,
        signal=signal,
        unavailable_reason=reason if reason else ("LINEA EN REVISION" if under_review else ""),
        final_stretch=is_final_stretch(m.scope_remaining_seconds, criteria),
        under_review=under_review,
    )


def evaluate_market(state: GameState, snapshot: Optional[MarketSnapshot],
                    criteria: EntryCriteria,
                    general: Optional[GeneralMetrics] = None,
                    under_review: bool = False) -> List[LineEvaluation]:
    """Evalua TODAS las lineas del mercado, ordenadas por valor de linea."""
    if snapshot is None or snapshot.is_empty:
        return []
    return [
        evaluate_line(state, line, criteria, general, under_review)
        for line in snapshot.sorted_lines()
    ]


def choose_focus(evaluations: List[LineEvaluation], criteria: EntryCriteria,
                 manual_line: Optional[float] = None) -> Optional[LineEvaluation]:
    """Decide que linea ocupa la tarjeta grande.

    1. Si has seleccionado una linea a mano, manda tu seleccion.
    2. Si no, se enfoca la linea cuya CUOTA UNDER este mas cerca de tu cuota
       objetivo. Es un criterio de enfoque VISUAL: todas las lineas siguen
       visibles con su senal, y esto no recomienda apostar nada.

    Nunca se enfoca por margen: un margen mayor suele venir acompanado de una
    cuota bastante peor, asi que no es lo que interesa mirar por defecto.
    """
    if not evaluations:
        return None

    if manual_line is not None:
        for evaluation in evaluations:
            if abs(evaluation.line_value - manual_line) < 1e-6:
                return evaluation

    with_odds = [e for e in evaluations if e.under_odds is not None]
    if not with_odds:
        return evaluations[0]

    target = criteria.target_under_odds
    return min(with_odds, key=lambda e: (abs(e.under_odds - target), e.line_value))


def evaluate_locked_bet(state: GameState, bet: LockedBet, criteria: EntryCriteria,
                        general: Optional[GeneralMetrics] = None) -> LineEvaluation:
    """Evalua la apuesta FIJADA usando su linea y su cuota congeladas.

    Aunque la casa haya movido su linea, aqui se calcula siempre contra la que
    tu fijaste. Por eso se reconstruye una MarketLine a partir de la apuesta en
    vez de buscarla en el mercado actual.
    """
    frozen = MarketLine(
        sportsbook=bet.sportsbook,
        event=bet.event,
        key=bet.key,
        line=bet.line,
        over_odds=bet.odds if bet.side is Side.OVER else None,
        under_odds=bet.odds if bet.side is Side.UNDER else None,
        timestamp=bet.placed_at,
        confirmed=True,
    )
    return evaluate_line(state, frozen, criteria, general)


def summarize(evaluations: List[LineEvaluation]) -> str:
    """Resumen corto para el log de diagnostico."""
    if not evaluations:
        return "sin lineas"
    partes = []
    for e in evaluations:
        pace = "--" if e.required_pace is None else (
            "INF" if math.isinf(e.required_pace) else f"{e.required_pace:.2f}")
        partes.append(f"{e.line_value:g}:{pace}/{e.signal.value}")
    return " ".join(partes)


@dataclass(frozen=True)
class MarketEvaluation:
    """Un mercado del evento con todas sus lineas evaluadas.

    Es el bloque que la interfaz pinta: cabecera con el estado de frescura y
    debajo tantas filas como lineas ofrezca la casa en ese mercado.
    """

    state: "MarketState"
    evaluations: List[LineEvaluation] = field(default_factory=list)
    freshness: "FreshnessState" = None
    focus: Optional[LineEvaluation] = None

    @property
    def key(self) -> MarketKey:
        return self.state.key

    @property
    def label(self) -> str:
        return self.state.key.label

    @property
    def is_live(self) -> bool:
        return bool(self.freshness and self.freshness.is_trustworthy_now)

    def age_text(self, now: Optional[float] = None) -> str:
        return self.state.describe_age(now)


def evaluate_event(state: GameState, markets: "EventMarkets", criteria: EntryCriteria,
                   freshness_criteria, general: Optional[GeneralMetrics] = None,
                   now: Optional[float] = None) -> List[MarketEvaluation]:
    """Evalua TODOS los mercados del evento, cada uno con sus propias lineas.

    Reune en un solo radar lo que la casa reparte en pestanas, pero sin
    disimular la frescura: cada bloque lleva su estado y su antiguedad.
    """
    if markets is None:
        return []
    resultado: List[MarketEvaluation] = []
    for market_state in markets.all_states():
        if not market_state.has_lines:
            continue
        estado = market_state.freshness(freshness_criteria, now)
        evaluaciones = [
            evaluate_line(state, line, criteria, general,
                          under_review=market_state.under_review)
            for line in market_state.lines
        ]
        resultado.append(MarketEvaluation(
            state=market_state,
            evaluations=evaluaciones,
            freshness=estado,
            focus=choose_focus(evaluaciones, criteria),
        ))
    return resultado


def find_evaluation(blocks: List[MarketEvaluation], key: MarketKey,
                    line_value: float) -> Optional[LineEvaluation]:
    """Localiza una linea concreta dentro del radar completo."""
    for block in blocks:
        if block.key != key:
            continue
        for evaluation in block.evaluations:
            if abs(evaluation.line_value - line_value) < 1e-6:
                return evaluation
    return None
