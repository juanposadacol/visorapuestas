"""Panel de mercado actual (requisitos 6, 7 y 18).

Muestra TODAS las lineas que ofrece la casa en el mercado detectado y permite
seleccionar una para fijarla como "mi apuesta". La seleccion del usuario se
respeta: aunque el mercado se refresque, la fila elegida sigue elegida
mientras esa linea siga existiendo.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
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

from ..domain.market import MarketLine, MarketSnapshot, Side
from . import formatters as fmt


class MarketPanel(QWidget):
    """Tabla de lineas seleccionables + boton FIJAR APUESTA."""

    lineSelected = Signal(object, object)   # (MarketLine, Side)
    lockRequested = Signal()
    unlockRequested = Signal()

    COLUMNS = ["LINEA", "OVER", "UNDER"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._snapshot: Optional[MarketSnapshot] = None
        self._selected_line_value: Optional[float] = None
        self._selected_side: Side = Side.UNDER
        self._locked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.market_label = QLabel("MERCADO: --")
        self.market_label.setObjectName("sectionTitle")
        layout.addWidget(self.market_label)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
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
        buttons.addWidget(self.lock_button, 2)
        buttons.addWidget(self.unlock_button, 1)
        layout.addLayout(buttons)

    # ------------------------------------------------------------- seleccion
    @property
    def selected_line(self) -> Optional[MarketLine]:
        if self._snapshot is None or self._selected_line_value is None:
            return None
        return self._snapshot.find(self._selected_line_value)

    @property
    def selected_side(self) -> Side:
        return self._selected_side

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.lock_button.setEnabled(not locked and self.selected_line is not None)
        self.unlock_button.setEnabled(locked)
        self.lock_button.setText("APUESTA FIJADA" if locked else "FIJAR APUESTA (F9)")

    def select_line_value(self, value: float) -> None:
        self._selected_line_value = value
        self._highlight_selection()

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or self._snapshot is None:
            return
        row = rows[0].row()
        item = self.table.item(row, 0)
        if item is None:
            return
        value = item.data(Qt.UserRole)
        if value is None:
            return
        self._selected_line_value = float(value)
        line = self._snapshot.find(self._selected_line_value)
        if line is not None:
            self.lock_button.setEnabled(not self._locked)
            self.lineSelected.emit(line, self._selected_side)

    def _highlight_selection(self) -> None:
        if self._selected_line_value is None:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and abs(float(item.data(Qt.UserRole)) - self._selected_line_value) < 1e-6:
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.blockSignals(False)
                return

    # -------------------------------------------------------------- refresco
    def update_market(self, snapshot: Optional[MarketSnapshot],
                      raw: Optional[MarketSnapshot] = None) -> None:
        """Redibuja la tabla conservando la fila seleccionada."""
        self._snapshot = snapshot
        if snapshot is None or snapshot.is_empty:
            self.table.setRowCount(0)
            self.market_label.setText("MERCADO: --")
            if raw is not None and raw.suspended:
                self.status_label.setText("Mercado SUSPENDIDO por la casa")
            else:
                self.status_label.setText(
                    "Sin lineas confirmadas. Revisa el ROI del bloque de mercado.")
            self.lock_button.setEnabled(False)
            return

        self.market_label.setText(
            f"MERCADO: {snapshot.key.label if snapshot.key else 'sin identificar'}")

        lines = snapshot.sorted_lines()
        self.table.setRowCount(len(lines))
        for row, line in enumerate(lines):
            line_item = QTableWidgetItem(fmt.line(line.line))
            line_item.setData(Qt.UserRole, float(line.line))
            line_item.setTextAlignment(Qt.AlignCenter)
            over_item = QTableWidgetItem(fmt.odds(line.over_odds))
            over_item.setTextAlignment(Qt.AlignCenter)
            under_item = QTableWidgetItem(fmt.odds(line.under_odds))
            under_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, line_item)
            self.table.setItem(row, 1, over_item)
            self.table.setItem(row, 2, under_item)

        if self._selected_line_value is None and lines:
            self._selected_line_value = lines[0].line
        self._highlight_selection()

        suspended = " (SUSPENDIDO)" if snapshot.suspended else ""
        self.status_label.setText(
            f"{len(lines)} linea(s) confirmadas{suspended}. "
            "Selecciona el UNDER que estas considerando y pulsa FIJAR APUESTA."
        )
        self.lock_button.setEnabled(not self._locked and self.selected_line is not None)
