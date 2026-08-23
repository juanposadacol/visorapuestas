"""Panel principal de metricas (requisitos 8 y 17).

Jerarquia visual, de mas grande a mas pequeno:

    1. FALTAN PARA PERDER   (el numero mas grande de la pantalla)
    2. PROMEDIO FALTANTE (RITMO NECESARIO)
    3. mi apuesta / limite de perdida
    4. marcador, reloj, puntos del cuarto y promedios

No aparece ninguna prediccion ni recomendacion: solo estado matematico.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calculations.entry import LineEvaluation
from ..calculations.metrics import GeneralMetrics
from ..calculations.signals import SignalLevel
from ..domain.event_markets import FreshnessState
from ..config.criteria import EntryCriteria
from ..domain.bet import LockedBet
from ..domain.game_state import GamePhase, GameState, PointsSource
from ..domain.market import MarketLine
from . import formatters as fmt
from .styles import COLOR_DANGER, COLOR_MUTED, COLOR_OK, COLOR_WARN


def _card(highlight: bool = False) -> QFrame:
    frame = QFrame()
    frame.setObjectName("cardHighlight" if highlight else "card")
    return frame


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


class MetricsPanel(QWidget):
    """Muestra el estado del partido y las metricas de la apuesta."""

    #: El usuario pide introducir el marcador con el que empezo el cuarto.
    baselineRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Sin un ancho minimo el divisor estrangula esta columna y los
        # numeros se recortan justo cuando mas rapido hay que leerlos.
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_scoreboard())
        layout.addWidget(self._build_clock())
        layout.addWidget(self._build_quarter())
        layout.addWidget(self._build_bet())
        layout.addWidget(self._build_critical())
        layout.addWidget(self._build_horizons())
        layout.addStretch(1)

    # ----------------------------------------------------------- construccion
    def _build_scoreboard(self) -> QFrame:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        layout.addWidget(_title("RESULTADOS ACTUALES"))

        # Alias conservados para compatibilidad con consumidores existentes;
        # la vista real es ahora la tabla compacta por periodo.
        self.team_a_label = QLabel(fmt.UNKNOWN)
        self.team_a_score = QLabel(fmt.UNKNOWN)
        self.team_b_label = QLabel(fmt.UNKNOWN)
        self.team_b_score = QLabel(fmt.UNKNOWN)
        self.total_label = QLabel(fmt.UNKNOWN)

        self.results_table = QTableWidget(3, 6)
        self.results_table.setObjectName("resultsTable")
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.results_table.setFocusPolicy(Qt.NoFocus)
        self.results_table.setShowGrid(False)
        self.results_table.setWordWrap(False)
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.results_table.verticalHeader().setDefaultSectionSize(23)
        self.results_table.horizontalHeader().setFixedHeight(23)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 6):
            self.results_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)
        self.results_table.setHorizontalHeaderLabels(["", "Q1", "Q2", "Q3", "Q4", "TOTAL"])
        self.results_table.setFixedHeight(96)
        layout.addWidget(self.results_table)
        return card

    def _build_clock(self) -> QFrame:
        card = _card()
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(4)

        self.period_label = QLabel(fmt.UNKNOWN)
        self.period_label.setObjectName("bigValue")
        self.clock_label = QLabel(fmt.UNKNOWN)
        self.clock_label.setObjectName("bigValue")
        self.clock_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.played_label = QLabel(fmt.UNKNOWN)
        self.played_label.setObjectName("metricValue")
        self.played_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.phase_label = QLabel("")
        self.phase_label.setObjectName("status")

        grid.addWidget(self.period_label, 0, 0)
        grid.addWidget(self.clock_label, 0, 1)
        grid.addWidget(_title("JUGADO DEL CUARTO"), 1, 0)
        grid.addWidget(self.played_label, 1, 1)
        grid.addWidget(self.phase_label, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(1, 110)
        return card

    def _build_quarter(self) -> QFrame:
        card = _card()
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(4)

        self.period_points_title = _title("PUNTOS DEL CUARTO")
        self.period_points_label = QLabel(fmt.UNKNOWN)
        self.period_points_label.setObjectName("metricValue")
        self.period_points_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.period_pace_label = QLabel(fmt.UNKNOWN)
        self.period_pace_label.setObjectName("metricValue")
        self.period_pace_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.half_points_title = _title("PUNTOS DE LA MITAD")
        self.half_points_label = QLabel(fmt.UNKNOWN)
        self.half_points_label.setObjectName("metricValue")
        self.half_points_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.half_pace_title = _title("PROMEDIO ACTUAL DE LA MITAD")
        self.half_pace_label = QLabel(fmt.UNKNOWN)
        self.half_pace_label.setObjectName("metricValue")
        self.half_pace_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.first_half_points_title = _title("PUNTOS 1H")
        self.first_half_points_label = QLabel(fmt.UNKNOWN)
        self.first_half_points_label.setObjectName("metricValue")
        self.first_half_points_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.first_half_pace_title = _title("PROMEDIO ACTUAL 1H")
        self.first_half_pace_label = QLabel(fmt.UNKNOWN)
        self.first_half_pace_label.setObjectName("metricValue")
        self.first_half_pace_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.game_points_label = QLabel(fmt.UNKNOWN)
        self.game_points_label.setObjectName("metricValue")
        self.game_points_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.game_pace_label = QLabel(fmt.UNKNOWN)
        self.game_pace_label.setObjectName("metricValue")
        self.game_pace_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.reference_label = QLabel(fmt.UNKNOWN)
        self.reference_label.setObjectName("metricValue")
        self.reference_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.target_odds_label = QLabel(fmt.UNKNOWN)
        self.target_odds_label.setObjectName("metricValue")
        self.target_odds_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.points_source_label = QLabel("")
        self.points_source_label.setObjectName("status")
        self.points_source_label.setWordWrap(True)

        # Aviso NO bloqueante (requisito 9): nunca una ventana modal automatica
        # encima del navegador; un boton visible que el usuario pulsa cuando
        # quiere. Mientras tanto los puntos del cuarto se muestran como "--".
        self.baseline_button = QPushButton("Introducir marcador al empezar el cuarto")
        self.baseline_button.clicked.connect(self.baselineRequested.emit)
        self.baseline_button.setVisible(False)

        grid.addWidget(self.period_points_title, 0, 0)
        grid.addWidget(self.period_points_label, 0, 1)
        self.period_pace_title = _title("PROMEDIO ACTUAL DEL CUARTO")
        grid.addWidget(self.period_pace_title, 1, 0)
        grid.addWidget(self.period_pace_label, 1, 1)
        grid.addWidget(self.half_points_title, 2, 0)
        grid.addWidget(self.half_points_label, 2, 1)
        grid.addWidget(self.half_pace_title, 3, 0)
        grid.addWidget(self.half_pace_label, 3, 1)
        grid.addWidget(self.first_half_points_title, 4, 0)
        grid.addWidget(self.first_half_points_label, 4, 1)
        grid.addWidget(self.first_half_pace_title, 5, 0)
        grid.addWidget(self.first_half_pace_label, 5, 1)
        grid.addWidget(_title("PUNTOS DEL PARTIDO"), 6, 0)
        grid.addWidget(self.game_points_label, 6, 1)
        grid.addWidget(_title("PROMEDIO ACTUAL PARTIDO"), 7, 0)
        grid.addWidget(self.game_pace_label, 7, 1)
        grid.addWidget(_title("MI REFERENCIA"), 8, 0)
        grid.addWidget(self.reference_label, 8, 1)
        grid.addWidget(_title("MI CUOTA UNDER OBJETIVO"), 9, 0)
        grid.addWidget(self.target_odds_label, 9, 1)
        grid.addWidget(self.points_source_label, 10, 0, 1, 2)
        grid.addWidget(self.baseline_button, 11, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(1, 110)
        return card

    def _build_bet(self) -> QFrame:
        card = _card(highlight=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self.bet_title = _title("MI APUESTA")
        self.bet_label = QLabel("Sin apuesta fijada")
        self.bet_label.setObjectName("betLine")
        self.bet_market_label = QLabel("")
        self.bet_market_label.setObjectName("status")
        self.market_now_label = QLabel("")
        self.market_now_label.setObjectName("status")
        self.freshness_label = QLabel("")
        self.freshness_label.setObjectName("status")

        layout.addWidget(self.bet_title)
        layout.addWidget(self.bet_label)
        layout.addWidget(self.bet_market_label)
        layout.addWidget(self.market_now_label)
        layout.addWidget(self.freshness_label)
        return card

    def _build_critical(self) -> QFrame:
        card = _card(highlight=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)
        layout.addWidget(_title("SEGUIMIENTO"))

        limit_row = QHBoxLayout()
        limit_row.addWidget(_title("LIMITE PARA PERDER"))
        self.threshold_label = QLabel(fmt.UNKNOWN)
        self.threshold_label.setObjectName("metricValue")
        self.threshold_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.threshold_label.setMinimumWidth(110)
        limit_row.addWidget(self.threshold_label)
        layout.addLayout(limit_row)

        self.points_title = _title("PUNTOS PARA SUPERAR LA LINEA")
        layout.addWidget(self.points_title)
        self.points_to_exceed_label = QLabel(fmt.UNKNOWN)
        self.points_to_exceed_label.setObjectName("hugeValue")
        self.points_to_exceed_label.setAlignment(Qt.AlignCenter)
        self.points_to_exceed_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.points_to_exceed_label)

        self.exceeded_label = QLabel("")
        self.exceeded_label.setObjectName("danger")
        self.exceeded_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.exceeded_label)

        layout.addWidget(_title("PROMEDIO FALTANTE (RITMO NECESARIO)"))
        self.required_pace_label = QLabel(fmt.UNKNOWN)
        self.required_pace_label.setObjectName("paceValue")
        self.required_pace_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.required_pace_label)

        self.signal_label = QLabel("")
        self.signal_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.signal_label)

        margins = QGridLayout()
        margins.setContentsMargins(0, 6, 0, 0)
        margins.setSpacing(2)
        self.margin_reference_label = QLabel(fmt.UNKNOWN)
        self.margin_period_label = QLabel(fmt.UNKNOWN)
        self.margin_half_label = QLabel(fmt.UNKNOWN)
        self.margin_game_label = QLabel(fmt.UNKNOWN)
        self.margin_reference_title = _title("MARGEN VS REFERENCIA")
        self.margin_period_title = _title("MARGEN VS CUARTO")
        self.margin_half_title = _title("MARGEN VS MITAD")
        for row, (title, widget) in enumerate((
            (self.margin_reference_title, self.margin_reference_label),
            (self.margin_period_title, self.margin_period_label),
            (self.margin_half_title, self.margin_half_label),
            (_title("MARGEN VS PARTIDO"), self.margin_game_label),
        )):
            widget.setObjectName("metricValue")
            widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            margins.addWidget(title, row, 0)
            margins.addWidget(widget, row, 1)
        margins.setColumnStretch(0, 1)
        margins.setColumnMinimumWidth(1, 110)
        layout.addLayout(margins)

        self.scope_label = QLabel("")
        self.scope_label.setObjectName("status")
        self.scope_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.scope_label)
        return card

    def _build_horizons(self) -> QFrame:
        card = _card()
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(4)

        self.halftime_label = QLabel(fmt.UNKNOWN)
        self.halftime_label.setObjectName("metricValue")
        self.halftime_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.end_label = QLabel(fmt.UNKNOWN)
        self.end_label.setObjectName("metricValue")
        self.end_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        grid.addWidget(_title("PARA EL DESCANSO"), 0, 0)
        grid.addWidget(self.halftime_label, 0, 1)
        grid.addWidget(_title("PARA EL FINAL"), 1, 0)
        grid.addWidget(self.end_label, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(1, 110)
        return card

    # -------------------------------------------------------------- refresco
    def update_view(self, state: GameState, general: GeneralMetrics,
                    bet: Optional[LockedBet] = None,
                    evaluation: Optional[LineEvaluation] = None,
                    current_market_line: Optional[MarketLine] = None,
                    criteria: Optional[EntryCriteria] = None,
                    needs_baseline: bool = False,
                    focus_freshness: Optional[FreshnessState] = None,
                    focus_age_text: str = "") -> None:
        """Vuelca un ciclo completo de datos en la interfaz."""
        self.team_a_label.setText(fmt.text(state.team_a.usable_value()) or "EQUIPO A")
        self.team_b_label.setText(fmt.text(state.team_b.usable_value()) or "EQUIPO B")
        self.team_a_score.setText(fmt.integer(state.score_a_value))
        self.team_b_score.setText(fmt.integer(state.score_b_value))
        self.total_label.setText(fmt.integer(general.total_points))
        self._update_results_table(state)

        self.period_label.setText(state.label())
        self.clock_label.setText(fmt.clock(general.remaining_period_seconds))
        self.played_label.setText(fmt.clock(general.elapsed_period_seconds))
        self.phase_label.setText(_phase_text(state.phase))

        period_label = state.label()
        self.period_points_title.setText(
            f"PUNTOS {period_label}" if period_label != "--" else "PUNTOS DEL CUARTO")
        self.period_pace_title.setText(
            f"PROMEDIO ACTUAL {period_label}" if period_label != "--"
            else "PROMEDIO ACTUAL DEL CUARTO")
        self.margin_period_title.setText(
            f"MARGEN VS {period_label}" if period_label != "--" else "MARGEN VS CUARTO")
        self.period_points_label.setText(_period_points_text(general))
        self.period_pace_label.setText(fmt.pace(general.period_pace))
        half_label = f"{general.half_number}H" if general.half_number else "MITAD"
        self.half_points_title.setText(f"PUNTOS {half_label}")
        self.half_pace_title.setText(f"PROMEDIO ACTUAL {half_label}")
        self.half_points_label.setText(_score_total_text(
            general.half_points_a, general.half_points_b, general.half_points))
        self.half_pace_label.setText(fmt.pace(general.half_pace))
        show_first_half = general.half_number == 2 and general.first_half_points is not None
        for widget in (self.first_half_points_title, self.first_half_points_label,
                       self.first_half_pace_title, self.first_half_pace_label):
            widget.setVisible(show_first_half)
        self.first_half_points_label.setText(_score_total_text(
            general.first_half_points_a, general.first_half_points_b,
            general.first_half_points))
        self.first_half_pace_label.setText(fmt.pace(general.first_half_pace))
        self.game_points_label.setText(_score_total_text(
            state.score_a_value, state.score_b_value, general.total_points))
        self.game_pace_label.setText(fmt.pace(general.game_pace))
        self.points_source_label.setText(_points_source_text(general.period_points_source))
        self.baseline_button.setVisible(bool(needs_baseline))
        if criteria is not None:
            self.reference_label.setText(f"{criteria.reference_pace:.2f} pts/min")
            self.target_odds_label.setText(f"{criteria.target_under_odds:.2f}")

        self._update_bet(bet, evaluation, current_market_line, criteria)
        self._update_market_state(focus_freshness, focus_age_text)
        self.halftime_label.setText(fmt.halftime(general.seconds_to_halftime))
        self.end_label.setText(fmt.clock(general.remaining_game_seconds))

    def _update_market_state(self, estado, edad: str) -> None:
        texto = _freshness_text(estado, edad)
        self.freshness_label.setText(texto)
        if estado is not None and not estado.is_trustworthy_now:
            self.freshness_label.setStyleSheet(f"color: {COLOR_WARN};")
        else:
            self.freshness_label.setStyleSheet("")

    def _update_bet(self, bet: Optional[LockedBet], m: Optional[LineEvaluation],
                    current_line: Optional[MarketLine],
                    criteria: Optional[EntryCriteria] = None) -> None:
        if bet is not None:
            self.bet_title.setText("MI APUESTA (FIJADA)")
            self.bet_label.setText(bet.describe())
            self.bet_market_label.setText(bet.key.label)
        elif m is not None:
            self.bet_title.setText("LINEA ENFOCADA (SIN FIJAR)")
            self.bet_label.setText(m.describe_under())
            self.bet_market_label.setText(m.key.label if m.key else "")
        else:
            self.bet_title.setText("MI APUESTA")
            self.bet_label.setText("Sin apuesta fijada")
            self.bet_market_label.setText("Selecciona una linea UNDER en el panel de mercado")

        # Requisito 7: la apuesta fijada y el mercado actual conviven en pantalla.
        if bet is not None and current_line is not None:
            moved = abs(current_line.line - bet.line) > 1e-6
            texto = f"MERCADO ACTUAL: UNDER {fmt.line(current_line.line)} @ {fmt.odds(current_line.under_odds)}"
            self.market_now_label.setText(texto + ("   (la casa movio la linea)" if moved else ""))
        else:
            self.market_now_label.setText("")

        if m is None:
            self.threshold_label.setText(fmt.UNKNOWN)
            self.points_to_exceed_label.setText(fmt.UNKNOWN)
            self.required_pace_label.setText(fmt.UNKNOWN)
            self.exceeded_label.setText("")
            self.signal_label.setText("")
            for widget in (self.margin_reference_label, self.margin_period_label,
                           self.margin_half_label, self.margin_game_label):
                widget.setText(fmt.UNKNOWN)
            self.scope_label.setText("")
            return

        self.threshold_label.setText(fmt.integer(m.exceed_threshold))
        # "Faltan para perder" solo cuando hay una apuesta UNDER fijada; si
        # todavia estas buscando entrada, el dato es neutro: puntos que faltan
        # para que la linea quede superada.
        self.points_title.setText("FALTAN PARA PERDER" if bet is not None
                                  else "PUNTOS PARA SUPERAR LA LINEA")
        if m.points_to_exceed is None:
            self.points_to_exceed_label.setText(fmt.UNKNOWN)
            self.points_to_exceed_label.setStyleSheet(f"color: {COLOR_MUTED};")
            self.exceeded_label.setText(m.unavailable_reason or "DATOS NO CONFIRMADOS")
        else:
            self.points_to_exceed_label.setText(f"{m.points_to_exceed} PUNTOS")
            color = (criteria.color_for(m.signal.value) if criteria is not None
                     else COLOR_OK)
            if not m.signal.is_evaluable:
                color = COLOR_MUTED
            self.points_to_exceed_label.setStyleSheet(f"color: {color};")
            if m.exceeded:
                self.exceeded_label.setText("LINEA SUPERADA" if bet is None
                                            else "UNDER SUPERADO")
            elif m.unavailable_reason:
                self.exceeded_label.setText(m.unavailable_reason)
            else:
                self.exceeded_label.setText("")

        self.required_pace_label.setText(fmt.pace(m.required_pace))
        self.signal_label.setText(_signal_text(m))
        if criteria is not None:
            self.signal_label.setStyleSheet(
                f"color: {criteria.color_for(m.signal.value)}; font-weight: 700;")
            self.margin_reference_title.setText(
                f"MARGEN VS REFERENCIA ({criteria.reference_pace:.2f})")
        self.margin_period_label.setText(_margin(m.margin_vs_period_pace))
        self.margin_half_label.setText(_margin(m.margin_vs_half_pace))
        self.margin_game_label.setText(_margin(m.margin_vs_game_pace))
        self.margin_reference_label.setText(_margin(m.margin_vs_reference))
        self.scope_label.setText(_scope_text(m))

    def _update_results_table(self, state: GameState) -> None:
        scores = state.period_grid_scores()
        headers = ["", *(state.rules.label(score.period) for score in scores), "TOTAL"]
        self.results_table.setColumnCount(len(headers))
        self.results_table.setHorizontalHeaderLabels(headers)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(headers)):
            self.results_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents)

        names = [
            fmt.text(state.team_a.usable_value()) or "EQUIPO A",
            fmt.text(state.team_b.usable_value()) or "EQUIPO B",
            "TOTAL",
        ]
        for row, name in enumerate(names):
            values = [name]
            for score in scores:
                if row == 0:
                    values.append(fmt.integer(score.points_a))
                elif row == 1:
                    values.append(fmt.integer(score.points_b))
                else:
                    values.append(fmt.integer(score.total))
            values.append(fmt.integer(
                state.score_a_value if row == 0 else
                state.score_b_value if row == 1 else state.total_points))
            for column, text in enumerate(values):
                item = self.results_table.item(row, column) or QTableWidgetItem()
                item.setText(text)
                item.setTextAlignment(
                    Qt.AlignLeft | Qt.AlignVCenter if column == 0
                    else Qt.AlignCenter)
                if column == 0:
                    item.setToolTip(name)
                font = item.font()
                font.setBold(column == len(values) - 1 or row == 2)
                item.setFont(font)
                self.results_table.setItem(row, column, item)


def _freshness_text(estado: Optional[FreshnessState], edad: str) -> str:
    """La tarjeta nunca oculta cuando se leyo por ultima vez ese mercado."""
    if estado is None:
        return ""
    if estado.is_trustworthy_now:
        return f"ESTADO DEL MERCADO: {estado.label}"
    return f"ESTADO DEL MERCADO: {estado.label}   ·   ultima lectura {edad}"


def _phase_text(phase: GamePhase) -> str:
    return {
        GamePhase.UNKNOWN: "",
        GamePhase.PERIOD_START: "Inicio del cuarto",
        GamePhase.IN_PLAY: "",
        GamePhase.CLOCK_STOPPED: "Reloj detenido",
        GamePhase.PERIOD_END: "Cuarto terminado",
        GamePhase.HALFTIME: "DESCANSO",
        GamePhase.GAME_OVER: "PARTIDO TERMINADO",
    }.get(phase, "")


def _period_points_text(general: GeneralMetrics) -> str:
    if general.period_points is None:
        return fmt.UNKNOWN
    if general.period_points_a is None or general.period_points_b is None:
        return str(general.period_points)
    return f"{general.period_points}   ({general.period_points_a} - {general.period_points_b})"


def _score_total_text(points_a: Optional[int], points_b: Optional[int],
                      total: Optional[int]) -> str:
    if total is None:
        return fmt.UNKNOWN
    if points_a is None or points_b is None:
        return f"{total} pts"
    return f"{points_a} - {points_b}   ·   {total} pts"


def _points_source_text(source: PointsSource) -> str:
    return {
        PointsSource.BREAKDOWN: "Puntos del cuarto leidos del desglose de la casa",
        PointsSource.HISTORY: "Puntos del cuarto calculados desde el inicio del cuarto",
        PointsSource.MANUAL: "Puntos del cuarto segun el marcador inicial que introdujiste",
        PointsSource.UNKNOWN: "Marcador al empezar el cuarto DESCONOCIDO: introducelo para ver los puntos del cuarto",
    }[source]


def _signal_text(m: LineEvaluation) -> str:
    """Etiqueta textual siempre visible: nunca se depende solo del color."""
    if not m.signal.is_evaluable:
        return m.unavailable_reason or m.signal.label
    texto = m.signal.label
    if m.final_stretch:
        # Indicador independiente: no altera ritmo, margen ni clasificacion.
        texto += "   ·   TRAMO FINAL"
    return texto


def _margin(value: Optional[float]) -> str:
    if value is None:
        return fmt.UNKNOWN
    import math
    if math.isinf(value):
        return "INF"
    return f"{value:+.2f}"


def _scope_text(m: LineEvaluation) -> str:
    if m.key is None:
        return ""
    parts = [f"Ambito: {m.key.label}"]
    parts.append(f"puntos {fmt.integer(m.scope_points)}")
    parts.append(f"tiempo jugado {fmt.clock(m.scope_elapsed_seconds)}")
    parts.append(f"promedio actual {fmt.pace(m.current_pace)}")
    parts.append(f"tiempo restante {fmt.clock(m.scope_remaining_seconds)}")
    if not m.started:
        parts.append("(el cuarto todavia no ha empezado)")
    if m.settled:
        parts.append("(ambito terminado)")
    return " | ".join(parts)
