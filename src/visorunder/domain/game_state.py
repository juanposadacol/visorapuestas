"""Estado del partido y contabilidad de puntos por periodo.

Requisito 9 (critico): NUNCA inventar los puntos de un cuarto.
Si la aplicacion arranca a mitad del Q3, los puntos observados (43-31) NO son
los puntos del Q3. El orden de prioridad para conocerlos es:

    1. BREAKDOWN  la casa muestra el desglose por cuarto -> se lee.
    2. HISTORY    la app estaba abierta al empezar el cuarto -> marcador base.
    3. MANUAL     el usuario introduce el marcador al comenzar el cuarto.
    4. UNKNOWN    no hay informacion -> la UI muestra "--".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Mapping, Optional, Tuple

from .rules import FIBA, GameRules
from .values import Observed, ValueStatus


class PointsSource(str, Enum):
    BREAKDOWN = "BREAKDOWN"
    HISTORY = "HISTORY"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"


class GamePhase(str, Enum):
    """Estados especiales del requisito 32."""

    UNKNOWN = "UNKNOWN"
    PERIOD_START = "PERIOD_START"
    IN_PLAY = "IN_PLAY"
    CLOCK_STOPPED = "CLOCK_STOPPED"
    PERIOD_END = "PERIOD_END"
    HALFTIME = "HALFTIME"
    GAME_OVER = "GAME_OVER"


@dataclass
class PeriodScore:
    """Puntos anotados DENTRO de un periodo concreto."""

    period: int
    points_a: Optional[int] = None
    points_b: Optional[int] = None
    source: PointsSource = PointsSource.UNKNOWN
    closed: bool = False  # el periodo ya termino: el dato es definitivo

    @property
    def total(self) -> Optional[int]:
        if self.points_a is None or self.points_b is None:
            return None
        return self.points_a + self.points_b

    @property
    def known(self) -> bool:
        return self.total is not None


class PeriodPointsTracker:
    """Lleva la cuenta de puntos por periodo a partir de marcadores base.

    `baselines[p]` es el MARCADOR TOTAL (acumulado del partido) justo cuando
    empezo el periodo p. Los puntos del periodo son la diferencia contra el
    marcador actual. Si no hay baseline y no hay desglose, el resultado es
    desconocido: se devuelve None y la interfaz muestra "--".
    """

    def __init__(self, rules: GameRules = FIBA) -> None:
        self.rules = rules
        self.baselines: Dict[int, Tuple[int, int, PointsSource]] = {}
        self.breakdown: Dict[int, Tuple[int, int]] = {}
        #: Foto completa del desglose estructural del DOM. Cada lado puede ser
        #: None: una celda desconocida no equivale a cero.
        self.dom_breakdown: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        self.closed_periods: Dict[int, Tuple[int, int, PointsSource]] = {}

    # ---------------------------------------------------------------- fuentes
    def set_baseline(self, period: int, score_a: int, score_b: int,
                     source: PointsSource = PointsSource.HISTORY) -> None:
        """Registra el marcador acumulado al comenzar `period`."""
        if period <= 0:
            raise ValueError("periodo invalido")
        existing = self.baselines.get(period)
        # Un baseline MANUAL no se pisa con uno inferido automaticamente.
        if existing and existing[2] is PointsSource.MANUAL and source is not PointsSource.MANUAL:
            return
        self.baselines[period] = (int(score_a), int(score_b), source)

    def set_manual_baseline(self, period: int, score_a: int, score_b: int) -> None:
        self.set_baseline(period, score_a, score_b, PointsSource.MANUAL)

    def set_breakdown(self, period: int, points_a: int, points_b: int) -> None:
        """Desglose leido directamente de la casa (maxima prioridad)."""
        self.breakdown[period] = (int(points_a), int(points_b))

    def replace_dom_breakdown(self, periods_a: Mapping[str, Optional[int]],
                              periods_b: Mapping[str, Optional[int]]) -> None:
        """Reemplaza atomica y completamente los parciales observados por DOM.

        La extension envia etiquetas Q1..Q4 y OT1..OTn. Al reemplazar en vez
        de acumular, una celda que deja de estar disponible no conserva un
        valor viejo ni contamina un partido nuevo.
        """
        merged: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
        for label in set(periods_a) | set(periods_b):
            period = self._period_from_label(label)
            if period is None:
                continue
            value_a = periods_a.get(label)
            value_b = periods_b.get(label)
            merged[period] = (
                int(value_a) if value_a is not None else None,
                int(value_b) if value_b is not None else None,
            )
        self.dom_breakdown = merged

    def _period_from_label(self, label: str) -> Optional[int]:
        text = str(label or "").upper()
        if text.startswith("Q") and text[1:].isdigit():
            value = int(text[1:])
            return value if 1 <= value <= self.rules.regulation_quarters else None
        if text.startswith("OT") and text[2:].isdigit() and int(text[2:]) >= 1:
            return self.rules.regulation_quarters + int(text[2:])
        return None

    @property
    def has_dom_breakdown(self) -> bool:
        return bool(self.dom_breakdown)

    def has_baseline(self, period: int) -> bool:
        dom = self.dom_breakdown.get(period)
        return (dom is not None and dom[0] is not None and dom[1] is not None) or \
            period in self.baselines or period in self.breakdown

    def baseline_source(self, period: int) -> PointsSource:
        dom = self.dom_breakdown.get(period)
        if dom is not None and dom[0] is not None and dom[1] is not None:
            return PointsSource.BREAKDOWN
        if period in self.breakdown:
            return PointsSource.BREAKDOWN
        entry = self.baselines.get(period)
        return entry[2] if entry else PointsSource.UNKNOWN

    # ------------------------------------------------------------- transicion
    def on_period_change(self, previous_period: Optional[int], new_period: int,
                         score_a: int, score_b: int) -> None:
        """Cierra el periodo anterior y abre el nuevo con el marcador actual.

        Al cambiar de cuarto el marcador acumulado es, por definicion, el
        marcador con el que arranca el cuarto nuevo y con el que termino el
        anterior. Esto da fuente HISTORY sin ninguna suposicion.
        """
        if previous_period is not None and previous_period in self.baselines:
            base_a, base_b, src = self.baselines[previous_period]
            self.closed_periods[previous_period] = (
                int(score_a) - base_a,
                int(score_b) - base_b,
                src,
            )
        self.set_baseline(new_period, score_a, score_b, PointsSource.HISTORY)

    # --------------------------------------------------------------- consulta
    def period_score(self, period: int, current_period: Optional[int],
                     score_a: Optional[int], score_b: Optional[int]) -> PeriodScore:
        """Puntos del periodo pedido. Devuelve UNKNOWN si no se puede saber."""
        # 1. Desglose estructural del DOM: dato mas directo y actualizado.
        dom = self.dom_breakdown.get(period)
        if dom is not None and dom[0] is not None and dom[1] is not None:
            closed = current_period is not None and period < current_period
            return PeriodScore(period, dom[0], dom[1], PointsSource.BREAKDOWN, closed)

        # 2. Desglose leido por OCR.
        if period in self.breakdown:
            pa, pb = self.breakdown[period]
            closed = current_period is not None and period < current_period
            return PeriodScore(period, pa, pb, PointsSource.BREAKDOWN, closed)

        # 3. Periodo ya cerrado durante esta sesion.
        if period in self.closed_periods:
            pa, pb, src = self.closed_periods[period]
            return PeriodScore(period, pa, pb, src, True)

        # 4. Periodo pasado del que se conocen los marcadores de inicio y de
        #    fin: la diferencia entre dos bases consecutivas son exactamente
        #    los puntos de ese periodo. Es un hecho, no una inferencia, y es
        #    lo que permite evaluar el mercado de la 2.a mitad cuando ya se
        #    juega el Q4 habiendo entrado a mitad del Q3.
        if current_period is not None and period < current_period:
            base = self.baselines.get(period)
            siguiente = self.baselines.get(period + 1)
            if base is not None and siguiente is not None:
                order = [PointsSource.BREAKDOWN, PointsSource.HISTORY,
                         PointsSource.MANUAL, PointsSource.UNKNOWN]
                peor = base[2] if order.index(base[2]) >= order.index(siguiente[2]) else siguiente[2]
                return PeriodScore(period, siguiente[0] - base[0], siguiente[1] - base[1],
                                   peor, True)

        # 5. Periodo en curso con baseline conocido.
        if current_period is not None and period == current_period:
            entry = self.baselines.get(period)
            if entry is not None and score_a is not None and score_b is not None:
                base_a, base_b, src = entry
                return PeriodScore(period, int(score_a) - base_a, int(score_b) - base_b, src, False)
            return PeriodScore(period)

        # 6. Periodo futuro: todavia no se ha jugado, 0 puntos es un hecho.
        if current_period is not None and period > current_period:
            return PeriodScore(period, 0, 0, PointsSource.HISTORY, False)

        return PeriodScore(period)

    def grid_scores(self, current_period: Optional[int], score_a: Optional[int],
                    score_b: Optional[int]) -> List[PeriodScore]:
        """Filas/columnas que puede pintar el cuadro de resultados.

        Si existe una rejilla DOM se conserva exactamente: una celda ausente o
        vacia se pinta desconocida. Solo se agregan columnas OT observadas.
        Sin DOM se muestran las fuentes fallback, pero no se inventan ceros en
        periodos futuros para la tabla visual.
        """
        periods = list(range(1, self.rules.regulation_quarters + 1))
        periods += sorted(p for p in self.dom_breakdown
                          if p > self.rules.regulation_quarters)
        if self.has_dom_breakdown:
            return [PeriodScore(
                period=p,
                points_a=self.dom_breakdown.get(p, (None, None))[0],
                points_b=self.dom_breakdown.get(p, (None, None))[1],
                source=PointsSource.BREAKDOWN
                if p in self.dom_breakdown else PointsSource.UNKNOWN,
                closed=current_period is not None and p < current_period,
            ) for p in periods]
        rows: List[PeriodScore] = []
        for p in periods:
            if current_period is not None and p > current_period:
                rows.append(PeriodScore(p))
            else:
                rows.append(self.period_score(p, current_period, score_a, score_b))
        return rows

    def half_score(self, half: int, rules: GameRules, current_period: Optional[int],
                   score_a: Optional[int], score_b: Optional[int]) -> PeriodScore:
        """Suma de los periodos de una mitad. UNKNOWN si falta alguno."""
        per_half = rules.regulation_quarters // 2
        first = 1 + (half - 1) * per_half
        periods = range(first, first + per_half)
        total_a = 0
        total_b = 0
        worst = PointsSource.BREAKDOWN
        order = [PointsSource.BREAKDOWN, PointsSource.HISTORY, PointsSource.MANUAL, PointsSource.UNKNOWN]
        for p in periods:
            ps = self.period_score(p, current_period, score_a, score_b)
            if not ps.known:
                return PeriodScore(period=first, source=PointsSource.UNKNOWN)
            total_a += ps.points_a or 0
            total_b += ps.points_b or 0
            if order.index(ps.source) > order.index(worst):
                worst = ps.source
        closed = current_period is not None and current_period > (first + per_half - 1)
        return PeriodScore(first, total_a, total_b, worst, closed)


@dataclass
class GameState:
    """Estado consolidado del partido, alimentado solo con datos utilizables."""

    rules: GameRules = FIBA
    team_a: Observed[str] = field(default_factory=Observed.unknown)
    team_b: Observed[str] = field(default_factory=Observed.unknown)
    score_a: Observed[int] = field(default_factory=Observed.unknown)
    score_b: Observed[int] = field(default_factory=Observed.unknown)
    period: Observed[int] = field(default_factory=Observed.unknown)
    clock_seconds: Observed[int] = field(default_factory=Observed.unknown)
    phase: GamePhase = GamePhase.UNKNOWN
    tracker: PeriodPointsTracker = field(default_factory=PeriodPointsTracker)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.tracker.rules = self.rules

    # ------------------------------------------------------------- accesores
    @property
    def score_a_value(self) -> Optional[int]:
        return self.score_a.usable_value()

    @property
    def score_b_value(self) -> Optional[int]:
        return self.score_b.usable_value()

    @property
    def period_value(self) -> Optional[int]:
        return self.period.usable_value()

    @property
    def clock_value(self) -> Optional[int]:
        return self.clock_seconds.usable_value()

    @property
    def total_points(self) -> Optional[int]:
        """Requisito 11.B: puntos del partido = A + B."""
        a, b = self.score_a_value, self.score_b_value
        if a is None or b is None:
            return None
        return a + b

    # ---------------------------------------------------------------- tiempos
    @property
    def period_duration(self) -> Optional[int]:
        p = self.period_value
        return self.rules.period_seconds(p) if p else None

    @property
    def elapsed_period_seconds(self) -> Optional[int]:
        """Requisito 11.A: tiempo jugado del cuarto = duracion - restante."""
        p, c = self.period_value, self.clock_value
        if p is None or c is None:
            return None
        return max(0, self.rules.period_seconds(p) - c)

    @property
    def remaining_period_seconds(self) -> Optional[int]:
        return self.clock_value

    @property
    def elapsed_game_seconds(self) -> Optional[int]:
        """Tiempo de juego efectivo transcurrido (requisito 11.E)."""
        p = self.period_value
        elapsed_q = self.elapsed_period_seconds
        if p is None or elapsed_q is None:
            return None
        return self.rules.seconds_before_period(p) + elapsed_q

    @property
    def remaining_game_seconds(self) -> Optional[int]:
        """Requisito 16: restante del cuarto + cuartos aun no jugados."""
        p, c = self.period_value, self.clock_value
        if p is None or c is None:
            return None
        if self.rules.is_overtime(p):
            # En prorroga no se puede saber si habra otra: solo cuenta la actual.
            return c
        remaining_periods = range(p + 1, self.rules.regulation_quarters + 1)
        return c + sum(self.rules.period_seconds(x) for x in remaining_periods)

    @property
    def remaining_to_halftime_seconds(self) -> Optional[int]:
        """Requisito 15. Devuelve None si no se sabe; -1 si ya paso el descanso."""
        p, c = self.period_value, self.clock_value
        if p is None or c is None:
            return None
        last_first_half = self.rules.halftime_after_period
        if p > last_first_half:
            return -1  # YA PASO
        remaining_periods = range(p + 1, last_first_half + 1)
        return c + sum(self.rules.period_seconds(x) for x in remaining_periods)

    # ------------------------------------------------------------ puntos/periodo
    def current_period_score(self) -> PeriodScore:
        p = self.period_value
        if p is None:
            return PeriodScore(period=0)
        return self.tracker.period_score(p, p, self.score_a_value, self.score_b_value)

    def period_score(self, period: int) -> PeriodScore:
        return self.tracker.period_score(period, self.period_value, self.score_a_value, self.score_b_value)

    def half_score(self, half: int) -> PeriodScore:
        return self.tracker.half_score(half, self.rules, self.period_value,
                                       self.score_a_value, self.score_b_value)

    def period_grid_scores(self) -> List[PeriodScore]:
        return self.tracker.grid_scores(self.period_value, self.score_a_value,
                                        self.score_b_value)

    def label(self) -> str:
        p = self.period_value
        return self.rules.label(p) if p else "--"
