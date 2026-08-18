"""Pantalla de CONFIGURAR: perfiles y regiones (requisitos 3, 23 y 24).

Aqui el usuario:
1. crea o elige un perfil de casa (Sportium, BetPlay, Wplay, RushBet, otra);
2. dibuja con el raton cada region sobre una captura real de su pantalla;
3. PRUEBA la lectura de cada region antes de guardar, viendo el texto que
   saca el OCR y el valor que se interpreta.

El paso 3 es el que evita configuraciones que "parecen bien" pero leen mal.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..capture.roi import Rect, RoiKind
from ..capture.screen_capture import CaptureError, ScreenCapture, available_backends
from ..config.profiles import KNOWN_SPORTSBOOKS, ScreenContext, SportsbookProfile
from ..domain.rules import preset_names
from ..ocr import preprocessing
from ..ocr.base import OcrEngine
from ..ocr.engine import available_engines
from .roi_selector import RoiOverlay, grab_desktop

#: Orden en que se ofrecen las regiones: primero las imprescindibles.
ROI_ORDER = [
    RoiKind.CLOCK,
    RoiKind.PERIOD,
    RoiKind.SCORE_PAIR,
    RoiKind.SCORE_A,
    RoiKind.SCORE_B,
    RoiKind.MARKET_LABEL,
    RoiKind.MARKET_BLOCK,
    RoiKind.LINES,
    RoiKind.OVER_ODDS,
    RoiKind.UNDER_ODDS,
    RoiKind.TEAM_A,
    RoiKind.TEAM_B,
    RoiKind.BREAKDOWN_A,
    RoiKind.BREAKDOWN_B,
    RoiKind.ANCHOR,
]


class ProfileDialog(QDialog):
    """Editor de perfil con seleccion visual de ROIs."""

    def __init__(self, profile: SportsbookProfile, capture: ScreenCapture,
                 engine: Optional[OcrEngine] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurar perfil de casa de apuestas")
        self.setMinimumSize(820, 620)
        self.profile = profile
        self.capture = capture
        self.engine = engine
        self._overlay: Optional[RoiOverlay] = None
        self._test_results: Dict[RoiKind, str] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_settings())
        layout.addWidget(self._build_regions(), 1)
        layout.addWidget(self._build_buttons())
        self._load_profile_into_form()
        self._refresh_table()

    # ---------------------------------------------------------- construccion
    def _build_settings(self) -> QGroupBox:
        box = QGroupBox("Perfil")
        form = QFormLayout(box)

        self.name_edit = QLineEdit()
        self.sportsbook_combo = QComboBox()
        self.sportsbook_combo.setEditable(True)
        self.sportsbook_combo.addItems(KNOWN_SPORTSBOOKS)

        self.rules_combo = QComboBox()
        self.rules_combo.addItems(preset_names())

        self.engine_combo = QComboBox()
        self.engine_combo.addItem("auto")
        self.engine_combo.addItems(available_engines())

        self.backend_label = QLabel(", ".join(available_backends()) or "ninguno")

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.5, 10.0)
        self.rate_spin.setSingleStep(0.5)
        self.rate_spin.setSuffix(" lecturas/s")

        self.confirm_spin = QSpinBox()
        self.confirm_spin.setRange(1, 10)
        self.confirm_spin.setSuffix(" lecturas iguales")

        self.ttl_spin = QDoubleSpinBox()
        self.ttl_spin.setRange(0.5, 30.0)
        self.ttl_spin.setSingleStep(0.5)
        self.ttl_spin.setSuffix(" s hasta caducar")

        self.screen_label = QLabel("")

        form.addRow("Nombre del perfil", self.name_edit)
        form.addRow("Casa de apuestas", self.sportsbook_combo)
        form.addRow("Reglas del partido", self.rules_combo)
        form.addRow("Motor OCR", self.engine_combo)
        form.addRow("Backends de captura", self.backend_label)
        form.addRow("Frecuencia de lectura", self.rate_spin)
        form.addRow("Confirmaciones exigidas", self.confirm_spin)
        form.addRow("Caducidad de un dato", self.ttl_spin)
        form.addRow("Pantalla de referencia", self.screen_label)
        return box

    def _build_regions(self) -> QGroupBox:
        box = QGroupBox("Regiones de interes")
        layout = QVBoxLayout(box)

        info = QLabel(
            "Abre la casa de apuestas en el navegador y deja visible el partido. "
            "Pulsa 'Definir' y arrastra el raton sobre la zona. ESC cancela.\n"
            "Imprescindibles: Reloj, Cuarto, Marcador y Bloque de lineas."
        )
        info.setWordWrap(True)
        info.setObjectName("status")
        layout.addWidget(info)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Region", "Estado", "Coordenadas", "Ultima prueba OCR", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.define_button = QPushButton("Definir region seleccionada")
        self.define_button.clicked.connect(self._define_selected)
        self.clear_button = QPushButton("Borrar region")
        self.clear_button.clicked.connect(self._clear_selected)
        self.test_button = QPushButton("Probar lectura de todas")
        self.test_button.clicked.connect(self._test_all)
        buttons.addWidget(self.define_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.test_button)
        layout.addLayout(buttons)
        return box

    def _build_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        return buttons

    # ---------------------------------------------------------------- datos
    def _load_profile_into_form(self) -> None:
        self.name_edit.setText(self.profile.name)
        self.sportsbook_combo.setCurrentText(self.profile.sportsbook or self.profile.name)
        self.rules_combo.setCurrentText(self.profile.rules_name)
        index = self.engine_combo.findText(self.profile.engine)
        self.engine_combo.setCurrentIndex(index if index >= 0 else 0)
        self.rate_spin.setValue(self.profile.reads_per_second)
        self.confirm_spin.setValue(self.profile.stabilization_required)
        self.ttl_spin.setValue(self.profile.value_ttl_seconds)
        self._update_screen_label()

    def _update_screen_label(self) -> None:
        screen = self.profile.screen
        self.screen_label.setText(
            f"{screen.width}x{screen.height} @ escala {screen.dpi_scale:g}  |  "
            f"marco {self.profile.frame.width}x{self.profile.frame.height}"
        )

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(ROI_ORDER))
        for row, kind in enumerate(ROI_ORDER):
            roi = self.profile.get_roi(kind)
            name = kind.display_name + (" *" if kind.is_required else "")
            self.table.setItem(row, 0, QTableWidgetItem(name))

            if roi is None:
                estado = "sin definir"
                coords = "--"
            else:
                estado = "definida"
                rect = roi.resolve(self.profile.frame)
                coords = f"{rect.x},{rect.y}  {rect.width}x{rect.height}"
            self.table.setItem(row, 1, QTableWidgetItem(estado))
            self.table.setItem(row, 2, QTableWidgetItem(coords))
            self.table.setItem(row, 3, QTableWidgetItem(self._test_results.get(kind, "")))

            item = QTableWidgetItem(kind.value)
            item.setData(Qt.UserRole, kind.value)
            self.table.setItem(row, 4, QTableWidgetItem(""))
            self.table.item(row, 0).setData(Qt.UserRole, kind.value)
        if self.table.rowCount() and not self.table.selectionModel().hasSelection():
            self.table.selectRow(0)

    def _selected_kind(self) -> Optional[RoiKind]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        return RoiKind(item.data(Qt.UserRole))

    # -------------------------------------------------------------- acciones
    def _define_selected(self) -> None:
        kind = self._selected_kind()
        if kind is None:
            return
        try:
            image, monitor = grab_desktop(self.capture)
        except CaptureError as exc:
            QMessageBox.warning(self, "Captura", f"No se pudo capturar la pantalla:\n{exc}")
            return

        # El marco de referencia es el monitor donde se configura.
        self.profile.frame = monitor
        self.profile.screen = ScreenContext(width=monitor.width, height=monitor.height,
                                            dpi_scale=self.profile.screen.dpi_scale)

        overlay = RoiOverlay(image, monitor, title=f"Selecciona: {kind.display_name}")
        overlay.regionSelected.connect(lambda rect, k=kind: self._on_region(k, rect))
        overlay.cancelled.connect(self._on_region_cancelled)
        self._overlay = overlay
        self.hide()
        overlay.showFullScreen()

    def _on_region(self, kind: RoiKind, rect: Rect) -> None:
        self.profile.set_roi(kind, rect)
        self._test_results.pop(kind, None)
        self._overlay = None
        self.show()
        self._update_screen_label()
        self._refresh_table()

    def _on_region_cancelled(self) -> None:
        self._overlay = None
        self.show()

    def _clear_selected(self) -> None:
        kind = self._selected_kind()
        if kind is None:
            return
        self.profile.remove_roi(kind)
        self._test_results.pop(kind, None)
        self._refresh_table()

    def _test_all(self) -> None:
        """Captura cada ROI y muestra lo que ve el OCR (diagnostico previo)."""
        if self.engine is None:
            QMessageBox.information(self, "OCR",
                                    "No hay motor OCR disponible para probar la lectura.")
            return
        for kind, roi in self.profile.rois.items():
            rect = roi.resolve(self.profile.frame)
            try:
                image = self.capture.grab(rect)
            except CaptureError as exc:
                self._test_results[kind] = f"error de captura: {exc}"
                continue
            prepared = preprocessing.prepare(image, roi.hints)
            result = self.engine.recognize(prepared, roi.hints)
            if result.error:
                self._test_results[kind] = f"error OCR: {result.error}"
            else:
                text = result.text.replace("\n", " / ") or "(vacio)"
                self._test_results[kind] = f"{text}   [conf {result.confidence:.2f}]"
        self._refresh_table()

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Perfil", "El perfil necesita un nombre.")
            return
        missing = self.profile.missing_required()
        if missing:
            names = ", ".join(k.display_name for k in missing)
            answer = QMessageBox.question(
                self, "Regiones incompletas",
                f"Faltan regiones imprescindibles:\n{names}\n\n"
                "Puedes guardar igualmente, pero la lectura en vivo no funcionara "
                "hasta definirlas. Guardar de todos modos?",
            )
            if answer != QMessageBox.Yes:
                return

        self.profile.name = name
        self.profile.sportsbook = self.sportsbook_combo.currentText().strip()
        self.profile.rules_name = self.rules_combo.currentText()
        self.profile.engine = self.engine_combo.currentText()
        self.profile.reads_per_second = float(self.rate_spin.value())
        self.profile.stabilization_required = int(self.confirm_spin.value())
        self.profile.value_ttl_seconds = float(self.ttl_spin.value())
        self.accept()
