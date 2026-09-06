"""Pantalla de CONFIGURAR: perfiles y regiones (requisitos 3, 23 y 24).

Aqui el usuario:
1. crea o elige un perfil de casa (Sportium, BetPlay, Wplay, RushBet, otra);
2. dibuja con el raton cada region sobre una captura real de su pantalla;
3. PRUEBA la lectura de cada region antes de guardar, viendo el texto que
   saca el OCR y el valor que se interpreta.

El paso 3 es el que evita configuraciones que "parecen bien" pero leen mal.

POR QUE "DEFINIR REGION" CERRABA LA APLICACION
----------------------------------------------
Para dibujar la region hay que quitar de en medio este dialogo y la ventana
principal, o saldrian en la captura. Eso provocaba dos danos encadenados:

1. Ocultar un QDialog TERMINA su bucle modal: `QDialog::setVisible(false)`
   hace `eventLoop->exit()`. Asi que `dialog.exec()` devolvia "cancelado" en
   cuanto se pulsaba el boton, y quien lo habia abierto daba el perfil por
   descartado mientras la seleccion seguia viva por su cuenta.
2. Con el editor y la ventana principal ocultos, el overlay quedaba como
   unica ventana visible. Al cerrarlo, Qt emitia `lastWindowClosed` y
   cerraba el proceso entero.

La solucion tiene tres piezas:

* `quit_guard()` desactiva el cierre automatico mientras dura la seleccion.
* El overlay avisa del resultado antes de cerrarse (ver `roi_selector`).
* `exec()` se reengancha aqui: si el bucle modal se rompio por una seleccion
  de region, se espera a que la seleccion termine y se vuelve a entrar, de
  modo que quien abrio el dialogo sigue viendo una llamada modal normal.
"""

from __future__ import annotations

import traceback
from sys import stderr as _stderr
from typing import Dict, Optional
from copy import deepcopy

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QGuiApplication
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
from ..config.profiles import (
    DEFAULT_MARKET_CHOICES,
    KNOWN_SPORTSBOOKS,
    ScreenContext,
    SportsbookProfile,
)
from ..domain.rules import preset_names
from ..ocr import preprocessing
from ..ocr.base import OcrEngine
from ..ocr.engine import available_engines
from .roi_selector import RoiOverlay, grab_desktop, quit_guard

#: Orden en que se ofrecen las regiones: primero las imprescindibles.
ROI_ORDER = [
    # El tablero completo va primero: en las casas cuyo marcador cambia de
    # columnas durante el partido (Stake) es la forma recomendada, porque
    # cubre reloj, cuarto y marcador con una sola region que no caduca.
    RoiKind.SCOREBOARD,
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
        self.profile = deepcopy(profile)
        self.capture = capture
        self.engine = engine
        self._overlay: Optional[RoiOverlay] = None
        self._test_results: Dict[RoiKind, str] = {}
        self._hidden_windows = []
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._capture_selection)
        self._selection_kind = None
        #: True mientras se esta eligiendo una region. Ocultar el dialogo rompe
        #: su bucle modal, asi que `exec()` usa esta marca para volver a entrar
        #: en vez de darle a quien lo abrio un "cancelado" que nadie pidio.
        self._selecting_roi = False
        self._selection_loop: Optional[QEventLoop] = None
        #: Estado de `quitOnLastWindowClosed` antes de ocultar las ventanas.
        self._quit_guard = None
        #: Ultimo error real de captura, para poder verlo en las pruebas.
        self.last_capture_error: str = ""

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

        # Si no se configura el ROI del titulo del mercado, hay que decir
        # EXPLICITAMENTE a que mercado pertenecen las lineas leidas.
        self.default_market_combo = QComboBox()
        for value, label in DEFAULT_MARKET_CHOICES:
            self.default_market_combo.addItem(label, value)

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
        self.monitor_combo = QComboBox()
        monitors = self.capture.monitors()
        self._desktop = monitors[0] if monitors else self.profile.frame
        for index, monitor in enumerate(monitors[1:] or monitors, start=1):
            self.monitor_combo.addItem(
                f"Pantalla {index}: {monitor.width} × {monitor.height} "
                f"({monitor.x}, {monitor.y})", monitor)

        form.addRow("Nombre del perfil", self.name_edit)
        form.addRow("Casa de apuestas", self.sportsbook_combo)
        form.addRow("Reglas del partido", self.rules_combo)
        form.addRow("Mercado si no se lee el titulo", self.default_market_combo)
        form.addRow("Motor OCR", self.engine_combo)
        form.addRow("Backends de captura", self.backend_label)
        form.addRow("Frecuencia de lectura", self.rate_spin)
        form.addRow("Confirmaciones exigidas", self.confirm_spin)
        form.addRow("Caducidad de un dato", self.ttl_spin)
        form.addRow("Pantalla de referencia", self.screen_label)
        form.addRow("Pantalla para seleccionar", self.monitor_combo)
        return box

    def _build_regions(self) -> QGroupBox:
        box = QGroupBox("Regiones de interes")
        layout = QVBoxLayout(box)

        info = QLabel(
            "Abre la casa de apuestas en el navegador y deja visible el partido. "
            "Pulsa 'Definir' y arrastra el raton sobre la zona. ESC cancela.\n"
            "Imprescindibles: Reloj, Cuarto, Marcador y Bloque de lineas.\n"
            "Si la casa cambia las columnas del marcador durante el partido "
            "(por ejemplo Stake, que anade una columna cada cuarto), define en "
            "su lugar el 'Tablero completo': cubre reloj, cuarto y marcador de "
            "una vez y no hay que redibujarlo al cambiar de cuarto."
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
        market_index = self.default_market_combo.findData(self.profile.default_market)
        self.default_market_combo.setCurrentIndex(max(0, market_index))
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

    # ---------------------------------------------------- modal + seleccion
    def exec(self) -> int:  # noqa: A003 - la firma la impone QDialog
        """Igual que `QDialog.exec()`, pero inmune a la seleccion de regiones.

        Ocultar un QDialog termina su bucle modal. Como definir una region
        exige ocultar este dialogo, `exec()` devolvia "cancelado" nada mas
        pulsar el boton y la ventana que lo abrio descartaba el perfil.

        Aqui se distingue una cosa de la otra: si el bucle se rompio porque hay
        una seleccion en curso, se espera a que termine y se vuelve a entrar.
        Quien llama sigue viendo una unica llamada modal que solo devuelve
        cuando el usuario guarda o cancela de verdad.
        """
        while True:
            result = super().exec()
            if not self._selecting_roi:
                return result
            self._wait_for_selection()

    def _wait_for_selection(self) -> None:
        """Bucle propio mientras el overlay esta en pantalla."""
        if not self._selecting_roi:
            return
        # Red de seguridad: si no hay overlay ni captura pendiente, la
        # seleccion murio sin avisar. Se restaura el editor en vez de esperar
        # a un aviso que ya no va a llegar nunca.
        if self._overlay is None and not self._capture_timer.isActive():
            self._restore_editor()
            return
        loop = QEventLoop()
        self._selection_loop = loop
        try:
            loop.exec()
        finally:
            self._selection_loop = None

    def done(self, result: int) -> None:
        """Cerrar el dialogo cancela cualquier seleccion en curso.

        Asi no puede quedar un overlay huerfano ocupando la pantalla ni el
        guardia de cierre puesto despues de que el dialogo haya terminado.
        """
        if self._selecting_roi:
            overlay = self._overlay
            if overlay is not None:
                overlay.finish(None)
            else:
                self._restore_editor()
        super().done(result)

    @property
    def is_selecting_roi(self) -> bool:
        """True mientras el overlay de seleccion sigue abierto."""
        return self._selecting_roi

    # -------------------------------------------------------------- acciones
    def _define_selected(self) -> None:
        kind = self._selected_kind()
        if kind is None:
            QMessageBox.information(self, "Region", "Selecciona una fila de la lista.")
            return
        if self._selecting_roi or self._capture_timer.isActive() or self._overlay is not None:
            return

        self._selection_kind = kind
        self._selecting_roi = True
        self.last_capture_error = ""

        # A partir de aqui no queda ninguna ventana visible de la aplicacion.
        # Sin este guardia, cerrar el overlay al terminar cerraria el proceso.
        self._quit_guard = quit_guard()
        self._quit_guard.__enter__()

        self._hidden_windows = []
        parent = self.parentWidget()
        if parent is not None and parent.window().isVisible():
            self._hidden_windows.append(parent.window())
        self.hide()
        for window in self._hidden_windows:
            window.hide()
        # Dejar que Windows repinte el navegador antes de tomar la imagen.
        self._capture_timer.start(300)

    def _capture_selection(self) -> None:
        kind = self._selection_kind
        try:
            monitor = self.monitor_combo.currentData()
            if monitor is None:
                raise CaptureError("No hay una pantalla disponible para capturar.")
            image, monitor = grab_desktop(self.capture, monitor)
            target = next((s for s in QGuiApplication.screens()
                           if (s.geometry().x(), s.geometry().y()) == (monitor.x, monitor.y)),
                          self.screen())
            titulo = kind.display_name if kind is not None else "la region"
            overlay = RoiOverlay(image, monitor, title=f"Selecciona: {titulo}",
                                 screen=target)
            overlay.regionSelected.connect(lambda rect, k=kind: self._on_region(k, rect))
            overlay.cancelled.connect(self._on_region_cancelled)
            self._overlay = overlay
            overlay.showFullScreen()
            overlay.raise_()
            overlay.activateWindow()
            overlay.setFocus()
        except Exception as exc:
            # El error se REGISTRA entero y se explica; no se traga. Lo unico
            # que se evita es que una excepcion aqui deje la aplicacion sin
            # ninguna ventana visible, que es lo que la mataba.
            self.last_capture_error = traceback.format_exc()
            print(self.last_capture_error, file=_stderr)
            self._restore_editor()
            QMessageBox.warning(
                self, "Captura",
                f"No se pudo capturar la pantalla:\n{exc}\n\n"
                "La aplicacion sigue abierta. Revisa el backend de captura en "
                "el panel de diagnostico.")

    def _restore_editor(self) -> None:
        """Devuelve la aplicacion al estado anterior a la seleccion.

        El orden importa: primero vuelven las ventanas que se ocultaron y solo
        despues se suelta el guardia de cierre, de modo que nunca hay un
        instante sin ventanas visibles con el cierre automatico activo.
        """
        self._capture_timer.stop()
        overlay, self._overlay = self._overlay, None
        if overlay is not None:
            overlay.deleteLater()

        for window in self._hidden_windows:
            window.show()
        self._hidden_windows = []
        self.show()
        self.raise_()
        self.activateWindow()

        self._selecting_roi = False
        self._selection_kind = None

        guard, self._quit_guard = self._quit_guard, None
        if guard is not None:
            guard.__exit__(None, None, None)

        # Si `exec()` estaba esperando a que terminara la seleccion, ya puede
        # volver a entrar en su bucle modal.
        loop, self._selection_loop = self._selection_loop, None
        if loop is not None and loop.isRunning():
            loop.quit()

    def _on_region(self, kind: RoiKind, rect: Rect) -> None:
        if kind is None or rect is None:
            self._restore_editor()
            return
        # Un marco comun conserva regiones de diferentes monitores sin moverlas.
        from ..capture.roi import NormalizedRect
        for roi in self.profile.rois.values():
            absolute = roi.resolve(self.profile.frame)
            roi.rect = NormalizedRect.from_rect(absolute, self._desktop)
        self.profile.frame = self._desktop
        self.profile.screen = ScreenContext(width=self._desktop.width, height=self._desktop.height,
                                            dpi_scale=self.profile.screen.dpi_scale)
        self.profile.set_roi(kind, rect)
        self._test_results.pop(kind, None)
        self._restore_editor()
        self._update_screen_label()
        self._refresh_table()

    def _on_region_cancelled(self) -> None:
        self._restore_editor()

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
        self.profile.default_market = self.default_market_combo.currentData() or "GAME"
        self.profile.engine = self.engine_combo.currentText()
        self.profile.reads_per_second = float(self.rate_spin.value())
        self.profile.stabilization_required = int(self.confirm_spin.value())
        self.profile.value_ttl_seconds = float(self.ttl_spin.value())
        self.accept()
