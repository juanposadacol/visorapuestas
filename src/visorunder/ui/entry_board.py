"""Tablero de entrada: la pantalla principal mientras buscas el momento.

Muestra TODAS las lineas que la casa ofrece ahora mismo, cada una con sus
numeros y su senal, para poder leer la situacion de un vistazo de uno o dos
segundos.

Columnas acordadas:
    LINEA | CUOTA U | PUNTOS PARA SUPERAR | RITMO NECESARIO |
    VS REFERENCIA | VS CUARTO | VS PARTIDO | SENAL

La senal se transmite SIEMPRE con etiqueta de texto ademas del color, para no
depender de la vista cromatica ni de la iluminacion de la pantalla.
"""

from __future__ import annotations

import math
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calculations.entry import LineEvaluation
from ..config.criteria import EntryCriteria
from ..domain.market import MarketSnapshot, Side
from . import formatters as fmt

COLUMNS = ["LINEA", "CUOTA U", "PUNTOS", "RITMO NEC.", "VS REF.", "VS Q", "VS PARTIDO", "SENAL"]
COL_LINE, COL_ODDS, COL_POINTS, COL_PACE, COL_REF, COL_QUARTER, COL_GAME, COL_SIGNAL = range(8)


def _margin_text(value: Optional[float]) -> str:
    if value is None:
        return fmt.UNKNOWN
    if math.isinf(value):
        return "INF"
    return f"{value:+.2f}"


def _pace_text(value: Optional[float]) -> str:
    if value is None:
        return fmt.UNKNOWN
    if math.isinf(value):
        return "IMPOSIBLE"
    return f"{value:.2f}"


class EntryBoard(QWidget):
    """Tabla de lineas evaluadas + acciones de seleccion y fijado."""

    lineSelected = Signal(object)      # LineEvaluation elegida a mano
    lockRequested = Signal()
    unlockRequested = Signal()
    autoFocusRequested = Signal()      # volver al enfoque por cuota objetivo

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._evaluations: List[LineEvaluation] = []
        self._criteria = EntryCriteria()
        self._locked = False
        self._signature: tuple = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.market_label = QLabel("MERCADO: --")
        self.market_label.setObjectName("sectionTitle")
        self.mode_label = QLabel("BUSCANDO ENTRADA")
        self.mode_label.setObjectName("sectionTitle")
        self.mode_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.market_label, 1)
        header.addWidget(self.mode_label)
        layout.addLayout(header)

        self.review_label = QLabel("")
        self.review_label.setObjectName("danger")
        self.review_label.setWordWrap(True)
        self.review_label.setVisible(False)
        layout.addWidget(self.review_label)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_SIGNAL, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self.lockRequested.emit())
        layout.addWidget(self.table, 1)

        self.status_label = QLabel("Sin lineas leidas todavia")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.lock_button = QPushButton("FIJAR APUESTA (F9)")
        self.lock_button.setObjectName("primary")
        self.lock_button.setEnabled(False)
        self.lock_button.clicked.connect(self.lockRequested.emit)
        self.unlock_button = QPushButton("Liberar apuesta")
        self.unlock_button.setEnabled(False)
        self.unlock_button.clicked.connect(self.unlockRequested.emit)
        self.auto_button = QPushButton("Enfoque automatico")
        self.auto_button.setToolTip(
            "Vuelve a enfocar la linea cuya cuota UNDER este mas cerca de tu cuota objetivo")
        self.auto_button.clicked.connect(self.autoFocusRequested.emit)
        buttons.addWidget(self.lock_button, 2)
        buttons.addWidget(self.unlock_button, 1)
        buttons.addWidget(self.auto_button, 1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------- seleccion
    @property
    def selected_evaluation(self) -> Optional[LineEvaluation]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self._evaluations):
            return self._evaluations[index]
        return None

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.unlock_button.setEnabled(locked)
        self.lock_button.setEnabled(not locked and bool(self._evaluations))
        self.lock_button.setText("APUESTA FIJADA" if locked else "FIJAR APUESTA (F9)")
        self.mode_label.setText("APUESTA FIJADA" if locked else "BUSCANDO ENTRADA")

    def _on_selection_changed(self) -> None:
        evaluation = self.selected_evaluation
        if evaluation is not None:
            self.lineSelected.emit(evaluation)

    def _select_line_value(self, value: Optional[float]) -> None:
        if value is None:
            return
        for row, evaluation in enumerate(self._evaluations):
            if abs(evaluation.line_value - value) < 1e-6:
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.blockSignals(False)
                return

    # -------------------------------------------------------------- refresco
    def update_board(self, evaluations: List[LineEvaluation], criteria: EntryCriteria,
                     snapshot: Optional[MarketSnapshot] = None,
                     focus: Optional[LineEvaluation] = None,
                     under_review: bool = False,
                     pending_lines: tuple = (),
                     from_label: bool = True) -> None:
        """Repinta el tablero con la propuesta ACTUAL de la casa."""
        self._evaluations = evaluations
        self._criteria = criteria

        if snapshot is not None and snapshot.key is not None:
            origen = "" if from_label else "   (mercado por defecto del perfil)"
            self.market_label.setText(f"MERCADO: {snapshot.key.label}{origen}")
        else:
            self.market_label.setText("MERCADO: --")

        # Aviso explicito: la casa ya ensena otras lineas y se estan validando.
        if under_review:
            pendientes = ", ".join(f"{v:g}" for v in pending_lines) or "nuevas lineas"
            self.review_label.setText(
                f"LINEA EN REVISION: la casa ofrece {pendientes} y se esta confirmando. "
                "Las senales quedan en espera para no mostrar una linea antigua como vigente.")
            self.review_label.setVisible(True)
        else:
            self.review_label.setVisible(False)

        if not evaluations:
            self.table.setRowCount(0)
            self._signature = ()
            if snapshot is not None and snapshot.suspended:
                self.status_label.setText("Mercado SUSPENDIDO por la casa")
            else:
                self.status_label.setText(
                    "Sin lineas confirmadas. Revisa el ROI del bloque de mercado.")
            self.lock_button.setEnabled(False)
            return

        signature = tuple(e.line_value for e in evaluations)
        rebuild = signature != self._signature
        if rebuild:
            self.table.blockSignals(True)
            self.table.setRowCount(len(evaluations))
            self._signature = signature

        for row, e in enumerate(evaluations):
            values = [
                fmt.line(e.line_value),
                fmt.odds(e.under_odds),
                fmt.integer(e.points_to_exceed),
                _pace_text(e.required_pace),
                _margin_text(e.margin_vs_reference),
                _margin_text(e.margin_vs_period_pace),
                _margin_text(e.margin_vs_game_pace),
                e.signal.label if e.is_evaluable else (e.unavailable_reason or e.signal.label),
            ]
            color = QColor(criteria.color_for(e.signal.value))
            for column, text in enumerate(values):
                item = self.table.item(row, column)
                if item is None or rebuild:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, column, item)
                item.setText(text)
                if column in (COL_SIGNAL, COL_REF):
                    item.setForeground(QBrush(color))
                if column == COL_SIGNAL:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
            if e.final_stretch and e.is_evaluable:
                signal_item = self.table.item(row, COL_SIGNAL)
                signal_item.setText(f"{e.signal.label} · TRAMO FINAL")

        if rebuild:
            self.table.blockSignals(False)
            if focus is not None:
                self._select_line_value(focus.line_value)
        elif focus is not None and self.selected_evaluation is None:
            self._select_line_value(focus.line_value)

        evaluables = sum(1 for e in evaluations if e.is_evaluable)
        if evaluables == 0:
            motivo = evaluations[0].unavailable_reason or "faltan datos confirmados"
            self.status_label.setText(f"Ninguna linea evaluable: {motivo}")
        else:
            self.status_label.setText(
                f"{len(evaluations)} linea(s) | referencia {criteria.reference_pace:.2f} pts/min | "
                f"cuota objetivo {criteria.target_under_odds:.2f}. "
                "Haz clic en una linea para enfocarla; F9 la fija.")
        self.lock_button.setEnabled(not self._locked)
