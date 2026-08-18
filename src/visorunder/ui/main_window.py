"""Ventana principal (requisitos 17, 23, 26 y 34).

Modos de funcionamiento accesibles desde la barra superior:
CONFIGURAR, INICIAR, PAUSAR/REANUDAR, FIJAR APUESTA y FINALIZAR PARTIDO.

La ventana solo PINTA: toda la logica vive en `AppController` y en el lector.
Se refresca por temporizador leyendo la ultima fotografia del lector, lo que
evita cualquier problema de hilos con Qt.
"""

from __future__ import annotations

from typing import Optional, Set

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..app import AppController
from ..capture.screen_capture import CaptureError
from ..domain.market import Side
from .diagnostics_panel import DiagnosticsPanel
from .hotkeys import HotkeyManager
from .entry_board import EntryBoard
from .metrics_panel import MetricsPanel
from .criteria_dialog import CriteriaDialog
from .profile_dialog import ProfileDialog
from .quarter_start_dialog import QuarterStartDialog
from .styles import STYLESHEET


class MainWindow(QMainWindow):
    def __init__(self, controller: AppController) -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Visor UNDER - lectura y calculo en vivo")
        self.setStyleSheet(STYLESHEET)
        self.resize(1040, 780)
        self._asked_baselines: Set[int] = set()
        self._panel_visible = True

        self._build_ui()
        self._build_hotkeys()
        self._refresh_profiles()
        self._apply_always_on_top(self.controller.settings.always_on_top)

        self.timer = QTimer(self)
        self.timer.setInterval(250)  # 4 refrescos por segundo
        self.timer.timeout.connect(self._refresh)
        self.timer.start()

    # ---------------------------------------------------------- construccion
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Horizontal)
        self.metrics_panel = MetricsPanel()
        self.metrics_panel.baselineRequested.connect(lambda: self._ask_baseline(force=True))
        self.entry_board = EntryBoard()
        self.entry_board.lineSelected.connect(self._on_line_selected)
        self.entry_board.lockRequested.connect(self.lock_bet)
        self.entry_board.unlockRequested.connect(self.unlock_bet)
        self.entry_board.autoFocusRequested.connect(self._on_auto_focus)
        self.entry_board.visibleMarketChanged.connect(self.controller.set_visible_market)
        splitter.addWidget(self.metrics_panel)
        splitter.addWidget(self.entry_board)
        # El tablero de lineas es el elemento dominante: es donde se detecta
        # el momento de entrada, que es la funcion principal del programa.
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([460, 700])

        self.tabs = QTabWidget()
        self.tabs.addTab(splitter, "Panel")
        self.diagnostics = DiagnosticsPanel(self.controller.log)
        self.tabs.addTab(self.diagnostics, "Diagnostico")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Listo")
        self.status.addWidget(self.status_label, 1)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)

        self.configure_button = QPushButton("CONFIGURAR")
        self.configure_button.clicked.connect(self.configure_profile)
        self.new_profile_button = QPushButton("Nuevo perfil")
        self.new_profile_button.clicked.connect(self.new_profile)

        self.start_button = QPushButton("INICIAR (F8)")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self.toggle_reading)

        self.finish_button = QPushButton("FINALIZAR PARTIDO")
        self.finish_button.setObjectName("danger")
        self.finish_button.clicked.connect(self.finish_game)
        self.finish_button.setEnabled(False)

        self.criteria_button = QPushButton("CRITERIOS")
        self.criteria_button.setToolTip(
            "Ritmo de referencia, cuota UNDER objetivo, umbrales de senal y colores")
        self.criteria_button.clicked.connect(self.configure_criteria)

        self.baseline_button = QPushButton("Marcador inicial del cuarto")
        self.baseline_button.clicked.connect(lambda: self._ask_baseline(force=True))

        self.on_top_check = QCheckBox("Siempre encima")
        self.on_top_check.setChecked(self.controller.settings.always_on_top)
        self.on_top_check.toggled.connect(self._apply_always_on_top)

        bar.addWidget(QLabel("Perfil:"))
        bar.addWidget(self.profile_combo)
        bar.addWidget(self.new_profile_button)
        bar.addWidget(self.configure_button)
        bar.addWidget(self.criteria_button)
        bar.addSpacing(12)
        bar.addWidget(self.start_button)
        bar.addWidget(self.finish_button)
        bar.addWidget(self.baseline_button)
        bar.addStretch(1)
        bar.addWidget(self.on_top_check)
        return bar

    def _build_hotkeys(self) -> None:
        self.hotkeys = HotkeyManager(
            widget=self,
            bindings=dict(self.controller.settings.hotkeys),
            global_enabled=self.controller.settings.global_hotkeys,
        )
        self.hotkeys.register("toggle_reading", self.toggle_reading)
        self.hotkeys.register("lock_bet", self.lock_bet)
        self.hotkeys.register("toggle_panel", self.toggle_panel)
        self.hotkeys.register("finish_game", self.finish_game)
        self.hotkeys.apply()

    # -------------------------------------------------------------- perfiles
    def _refresh_profiles(self) -> None:
        names = self.controller.profile_names()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        last = self.controller.settings.last_profile
        if last in names:
            self.profile_combo.setCurrentText(last)
        self.profile_combo.blockSignals(False)
        if names:
            self._on_profile_changed(self.profile_combo.currentText())
        else:
            self.status_label.setText(
                "No hay perfiles. Pulsa 'Nuevo perfil' y define las regiones de tu casa.")

    def _on_profile_changed(self, name: str) -> None:
        if not name:
            return
        profile = self.controller.load_profile(name)
        if profile is None:
            return
        missing = profile.missing_required()
        if missing:
            faltan = ", ".join(k.display_name for k in missing)
            self.status_label.setText(f"Perfil '{name}': faltan regiones -> {faltan}")
        else:
            self.status_label.setText(f"Perfil '{name}' listo. Pulsa INICIAR.")

    def new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo perfil", "Nombre del perfil:")
        if not ok or not name.strip():
            return
        profile = self.controller.new_profile(name.strip())
        self._edit_profile(profile)

    def configure_profile(self) -> None:
        profile = self.controller.profile
        if profile is None:
            self.new_profile()
            return
        self._edit_profile(profile)

    def _edit_profile(self, profile) -> None:
        was_running = self.controller.reader is not None
        if was_running:
            self.controller.pause()
        try:
            capture = self.controller.capture
        except CaptureError as exc:
            QMessageBox.critical(self, "Captura", str(exc))
            return
        engine = self.controller.ensure_engine(profile.engine)
        dialog = ProfileDialog(profile, capture, engine, self)
        if dialog.exec():
            self.controller.save_profile(profile)
            self._refresh_profiles()
            self.profile_combo.setCurrentText(profile.name)
        if was_running:
            self.controller.resume()

    # ---------------------------------------------------------------- modos
    def configure_criteria(self) -> None:
        """Edita tus criterios de entrada. Se aplican de inmediato."""
        dialog = CriteriaDialog(self.controller.criteria, self)
        if not dialog.exec():
            return
        self.controller.update_criteria(dialog.result_criteria())
        self.status_label.setText(
            f"Criterios actualizados: {self.controller.criteria.describe()}")

    def toggle_reading(self) -> None:
        controller = self.controller
        if controller.reader is None:
            reader = controller.start_session()
            if reader is None:
                QMessageBox.warning(
                    self, "No se puede iniciar",
                    "Revisa el panel de diagnostico: falta el perfil, alguna region "
                    "imprescindible o el motor OCR.")
                return
            self.start_button.setText("PAUSAR (F8)")
            self.finish_button.setEnabled(True)
            self._asked_baselines.clear()
            return
        paused = controller.toggle_reading()
        self.start_button.setText("REANUDAR (F8)" if paused else "PAUSAR (F8)")

    def finish_game(self) -> None:
        if self.controller.reader is None and self.controller.session_id is None:
            return
        answer = QMessageBox.question(
            self, "Finalizar partido",
            "Se detendra la lectura y se cerrara la sesion.\n"
            "El historial queda guardado en la base de datos. Continuar?")
        if answer != QMessageBox.Yes:
            return
        self.controller.finish_game()
        self.start_button.setText("INICIAR (F8)")
        self.finish_button.setEnabled(False)
        self.entry_board.set_locked(False)
        self.status_label.setText("Partido finalizado. Historial guardado.")

    def toggle_panel(self) -> None:
        self._panel_visible = not self._panel_visible
        if self._panel_visible:
            self.showNormal()
            self.raise_()
            self.activateWindow()
        else:
            self.showMinimized()

    def _apply_always_on_top(self, enabled: bool) -> None:
        self.controller.settings.always_on_top = bool(enabled)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(enabled))
        self.show()

    # -------------------------------------------------------------- apuesta
    def _on_auto_focus(self) -> None:
        self.controller.clear_manual_selection()

    def _on_line_selected(self, evaluation) -> None:
        """Tu clic manda sobre el enfoque automatico por cuota objetivo."""
        if evaluation is not None:
            self.controller.select_line(evaluation.line, Side.UNDER, manual=True)

    def lock_bet(self) -> None:
        if self.controller.locked_bet is not None:
            return
        selected = self.entry_board.selected_evaluation
        line = selected.line if selected is not None else self.controller.selected_line
        if line is None:
            QMessageBox.information(self, "Fijar apuesta",
                                    "Selecciona antes una linea en el panel de mercado.")
            return
        self.controller.select_line(line, Side.UNDER)
        bet = self.controller.lock_bet()
        if bet is not None:
            self.entry_board.set_locked(True)
            self.status_label.setText(f"APUESTA FIJADA: {bet.describe_full()}")

    def unlock_bet(self) -> None:
        self.controller.unlock_bet()
        self.entry_board.set_locked(False)

    # ------------------------------------------------------------- refresco
    def _refresh(self) -> None:
        reader = self.controller.reader
        snapshot = reader.last_snapshot if reader else None
        view = self.controller.build_view_model(snapshot)
        if view.snapshot is None or view.general is None:
            return

        self.metrics_panel.update_view(
            state=view.snapshot.state, general=view.general, bet=view.bet,
            evaluation=view.bet_tracking or view.focus,
            current_market_line=view.current_market_line,
            criteria=view.criteria,
            needs_baseline=view.snapshot.needs_period_baseline,
            focus_freshness=view.focus_freshness,
            focus_age_text=view.focus_age_text,
        )
        self.entry_board.update_board(
            blocks=view.blocks, criteria=view.criteria, focus=view.focus,
            in_transition=view.snapshot.market_in_transition,
            now=view.snapshot.ts,
        )
        self._update_status(view)

    def _update_status(self, view) -> None:
        snapshot = view.snapshot
        parts = [view.mode.label]
        if self.controller.reader is not None:
            estado = "PAUSADO" if self.controller.reader.is_paused else "LEYENDO"
            parts.append(estado)
        parts.append(f"ciclo {snapshot.cycle_ms:.0f} ms")
        parts.append(f"OCR {snapshot.ocr_ms:.0f} ms")
        if self.controller.engine is not None:
            parts.append(self.controller.engine.describe())
        if snapshot.errors:
            parts.append("ERRORES: " + "; ".join(snapshot.errors[:2]))
        parts.append(self.hotkeys.describe())
        self.status_label.setText("   |   ".join(parts))

    def _ask_baseline(self, force: bool = False) -> None:
        """Requisito 9: preguntar el marcador al empezar el cuarto, una sola vez."""
        reader = self.controller.reader
        if reader is None:
            return
        state = reader.state
        period = state.period_value
        if period is None:
            if force:
                QMessageBox.information(self, "Marcador inicial",
                                        "Todavia no se ha confirmado el cuarto en juego.")
            return
        if state.tracker.has_baseline(period) and not force:
            return
        dialog = QuarterStartDialog(
            period_label=state.label(),
            current_a=state.score_a_value, current_b=state.score_b_value,
            team_a=state.team_a.usable_value() or "Equipo A",
            team_b=state.team_b.usable_value() or "Equipo B",
            parent=self,
        )
        if dialog.exec():
            score_a, score_b = dialog.values()
            self.controller.set_period_baseline(period, score_a, score_b)

    # ---------------------------------------------------------------- cierre
    def closeEvent(self, event) -> None:
        self.hotkeys.stop()
        geometry = self.geometry()
        self.controller.settings.window_geometry = [
            geometry.x(), geometry.y(), geometry.width(), geometry.height()]
        self.controller.shutdown()
        super().closeEvent(event)
