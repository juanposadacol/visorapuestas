"""Panel principal de metricas (requisitos 8 y 17).

Jerarquia visual, de mas grande a mas pequeno:

    1. FALTAN PARA PERDER   (el numero mas grande de la pantalla)
    2. RITMO NECESARIO PARA PERDER
    3. mi apuesta / limite de perdida
    4. marcador, reloj, puntos del cuarto y promedios

No aparece ninguna prediccion ni recomendacion: solo estado matematico.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..calculations.metrics import BetMetrics, GeneralMetrics
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
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(4)

        self.team_a_label = QLabel(fmt.UNKNOWN)
        self.team_a_label.setObjectName("teamName")
        self.team_a_score = QLabel(fmt.UNKNOWN)
        self.team_a_score.setObjectName("teamScore")
        self.team_a_score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.team_b_label = QLabel(fmt.UNKNOWN)
        self.team_b_label.setObjectName("teamName")
        self.team_b_score = QLabel(fmt.UNKNOWN)
        self.team_b_score.setObjectName("teamScore")
        self.team_b_score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.total_label = QLabel(fmt.UNKNOWN)
        self.total_label.setObjectName("metricValue")
        self.total_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        grid.addWidget(self.team_a_label, 0, 0)
        grid.addWidget(self.team_a_score, 0, 1)
        grid.addWidget(self.team_b_label, 1, 0)
        grid.addWidget(self.team_b_score, 1, 1)
        grid.addWidget(_title("TOTAL PARTIDO"), 2, 0)
        grid.addWidget(self.total_label, 2, 1)
        grid.setColumnStretch(0, 1)
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

        self.game_pace_label = QLabel(fmt.UNKNOWN)
        self.game_pace_label.setObjectName("metricValue")
        self.game_pace_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

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
        grid.addWidget(_title("PROMEDIO DEL CUARTO"), 1, 0)
        grid.addWidget(self.period_pace_label, 1, 1)
        grid.addWidget(_title("PROMEDIO DEL PARTIDO"), 2, 0)
        grid.addWidget(self.game_pace_label, 2, 1)
        grid.addWidget(self.points_source_label, 3, 0, 1, 2)
        grid.addWidget(self.baseline_button, 4, 0, 1, 2)
        grid.setColumnStretch(0, 1)
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

        layout.addWidget(self.bet_title)
        layout.addWidget(self.bet_label)
        layout.addWidget(self.bet_market_label)
        layout.addWidget(self.market_now_label)
        return card

    def _build_critical(self) -> QFrame:
        card = _card(highlight=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(2)

        limit_row = QHBoxLayout()
        limit_row.addWidget(_title("LIMITE PARA PERDER"))
        self.threshold_label = QLabel(fmt.UNKNOWN)
        self.threshold_label.setObjectName("metricValue")
        self.threshold_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        limit_row.addWidget(self.threshold_label)
        layout.addLayout(limit_row)

        layout.addWidget(_title("FALTAN PARA PERDER"))
        self.points_to_exceed_label = QLabel(fmt.UNKNOWN)
        self.points_to_exceed_label.setObjectName("hugeValue")
        self.points_to_exceed_label.setAlignment(Qt.AlignCenter)
        self.points_to_exceed_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.points_to_exceed_label)

        self.exceeded_label = QLabel("")
        self.exceeded_label.setObjectName("danger")
        self.exceeded_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.exceeded_label)

        layout.addWidget(_title("RITMO NECESARIO PARA PERDER"))
        self.required_pace_label = QLabel(fmt.UNKNOWN)
        self.required_pace_label.setObjectName("paceValue")
        self.required_pace_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.required_pace_label)

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
        return card

    # -------------------------------------------------------------- refresco
    def update_view(self, state: GameState, general: GeneralMetrics,
                    bet: Optional[LockedBet] = None,
                    bet_metrics: Optional[BetMetrics] = None,
                    current_market_line: Optional[MarketLine] = None,
                    selection_is_bet: bool = True,
                    needs_baseline: bool = False) -> None:
        """Vuelca un ciclo completo de datos en la interfaz."""
        self.team_a_label.setText(fmt.text(state.team_a.usable_value()) or "EQUIPO A")
        self.team_b_label.setText(fmt.text(state.team_b.usable_value()) or "EQUIPO B")
        self.team_a_score.setText(fmt.integer(state.score_a_value))
        self.team_b_score.setText(fmt.integer(state.score_b_value))
        self.total_label.setText(fmt.integer(general.total_points))

        self.period_label.setText(state.label())
        self.clock_label.setText(fmt.clock(general.remaining_period_seconds))
        self.played_label.setText(fmt.clock(general.elapsed_period_seconds))
        self.phase_label.setText(_phase_text(state.phase))

        period_label = state.label()
        self.period_points_title.setText(
            f"PUNTOS {period_label}" if period_label != "--" else "PUNTOS DEL CUARTO")
        self.period_points_label.setText(_period_points_text(general))
        self.period_pace_label.setText(fmt.pace(general.period_pace))
        self.game_pace_label.setText(fmt.pace(general.game_pace))
        self.points_source_label.setText(_points_source_text(general.period_points_source))
        self.baseline_button.setVisible(bool(needs_baseline))

        self._update_bet(bet, bet_metrics, current_market_line, selection_is_bet)
        self.halftime_label.setText(fmt.halftime(general.seconds_to_halftime))
        self.end_label.setText(fmt.clock(general.remaining_game_seconds))

    def _update_bet(self, bet: Optional[LockedBet], m: Optional[BetMetrics],
                    current_line: Optional[MarketLine], selection_is_bet: bool) -> None:
        if bet is not None:
            self.bet_title.setText("MI APUESTA (FIJADA)")
            self.bet_label.setText(bet.describe())
            self.bet_market_label.setText(bet.key.label)
        elif m is not None and m.line is not None:
            self.bet_title.setText("LINEA SELECCIONADA (SIN FIJAR)")
            odds = fmt.odds(m.odds)
            self.bet_label.setText(f"{m.side.value} {fmt.line(m.line)} @ {odds}")
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
            self.scope_label.setText("")
            return

        self.threshold_label.setText(fmt.integer(m.exceed_threshold))
        if m.points_to_exceed is None:
            self.points_to_exceed_label.setText(fmt.UNKNOWN)
            self.points_to_exceed_label.setStyleSheet(f"color: {COLOR_MUTED};")
            self.exceeded_label.setText("PUNTOS DEL AMBITO NO CONFIRMADOS")
        else:
            self.points_to_exceed_label.setText(f"{m.points_to_exceed} PUNTOS")
            color = COLOR_DANGER if m.exceeded else (
                COLOR_WARN if m.points_to_exceed <= 6 else COLOR_OK)
            self.points_to_exceed_label.setStyleSheet(f"color: {color};")
            self.exceeded_label.setText("UNDER SUPERADO" if m.exceeded else "")

        self.required_pace_label.setText(fmt.pace(m.required_pace))
        self.scope_label.setText(_scope_text(m))


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


def _points_source_text(source: PointsSource) -> str:
    return {
        PointsSource.BREAKDOWN: "Puntos del cuarto leidos del desglose de la casa",
        PointsSource.HISTORY: "Puntos del cuarto calculados desde el inicio del cuarto",
        PointsSource.MANUAL: "Puntos del cuarto segun el marcador inicial que introdujiste",
        PointsSource.UNKNOWN: "Marcador al empezar el cuarto DESCONOCIDO: introducelo para ver los puntos del cuarto",
    }[source]


def _scope_text(m: BetMetrics) -> str:
    if m.key is None:
        return ""
    parts = [f"Ambito: {m.key.label}"]
    parts.append(f"puntos {fmt.integer(m.scope_points)}")
    parts.append(f"tiempo restante {fmt.clock(m.scope_remaining_seconds)}")
    if not m.started:
        parts.append("(el cuarto todavia no ha empezado)")
    if m.settled:
        parts.append("(ambito terminado)")
    return " | ".join(parts)
