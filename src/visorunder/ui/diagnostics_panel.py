"""Panel de diagnostico (requisito 22).

Tabla en vivo con: hora, nivel, region, OCR bruto, OCR normalizado, confianza,
valor confirmado, estado y motivo del rechazo. Permite exportar a fichero.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..capture.roi import RoiKind
from ..diagnostics.logbus import LEVELS, LogBus
from .styles import COLOR_DANGER, COLOR_MUTED, COLOR_WARN
from .flow_layout import FlowRow


class DiagnosticsPanel(QWidget):
    """Vista del log. Se refresca por temporizador, no por cada entrada."""

    def __init__(self, logbus: LogBus, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.logbus = logbus
        self._max_rows = 300

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # La fila de filtros tambien se parte: si no, sus 781 px de minimo
        # subian el minimo de TODA la ventana (la pestana mas exigente manda)
        # y esta no cabia en una pantalla vertical.
        controls = FlowRow(spacing=6, vertical_spacing=4)
        self.region_filter = QComboBox()
        self.region_filter.addItem("Todas las regiones", "")
        for kind in RoiKind:
            self.region_filter.addItem(kind.display_name, kind.value)
        self.level_filter = QComboBox()
        self.level_filter.addItem("Todos los niveles", "")
        for level in LEVELS:
            self.level_filter.addItem(level, level)
        self.autoscroll = QCheckBox("Seguir en vivo")
        self.autoscroll.setChecked(True)
        self.export_button = QPushButton("Exportar log")
        self.export_button.clicked.connect(self._export)
        self.clear_button = QPushButton("Limpiar")
        self.clear_button.clicked.connect(self.logbus.clear)

        controls.add(QLabel("Filtros:"))
        controls.add(self.region_filter)
        controls.add(self.level_filter)
        controls.add(self.autoscroll)
        controls.add_stretch()
        controls.add(self.export_button)
        controls.add(self.clear_button)
        layout.addWidget(controls)

        self.table = QTableWidget(0, len(LogBus.COLUMNS))
        self.table.setHorizontalHeaderLabels(LogBus.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def refresh(self) -> None:
        if not self.autoscroll.isChecked() and self.table.rowCount():
            return
        region = self.region_filter.currentData() or ""
        level = self.level_filter.currentData() or ""
        entries = self.logbus.entries(limit=self._max_rows, region=region, level=level)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            for column, value in enumerate(entry.as_row()):
                item = QTableWidgetItem(value)
                if entry.level == "ERROR":
                    item.setForeground(Qt.red)
                elif entry.level == "WARN":
                    item.setForeground(Qt.yellow)
                self.table.setItem(row, column, item)
        if self.autoscroll.isChecked():
            self.table.scrollToBottom()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar log", "visorunder-log.txt",
                                              "Texto (*.txt)")
        if path:
            self.logbus.export(path)
