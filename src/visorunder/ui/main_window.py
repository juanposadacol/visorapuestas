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
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..app import AppController, SessionState
from ..bridge.source import ExtensionState, LinkState
from ..capture.screen_capture import CaptureError
from ..domain.market import Side
from .diagnostics_panel import DiagnosticsPanel
from .hotkeys import HotkeyManager
from .entry_board import EntryBoard
from .metrics_panel import MetricsPanel
from .manual_bets_panel import ManualBetsPanel
from .connection_panel import ConnectionPanel
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
        self.resize(1120, 860)
        self._asked_baselines: Set[int] = set()
        self._panel_visible = True
        self._autostart_blocked = False

        self._build_ui()
        self._build_hotkeys()
        self._refresh_profiles()
        self._apply_always_on_top(self.controller.settings.always_on_top)

        self.controller.start_bridge()

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
        self.connection_panel = ConnectionPanel()
        self.entry_board = EntryBoard()
        self.entry_board.lineSelected.connect(self._on_line_selected)
        self.entry_board.lockRequested.connect(self.lock_bet)
        self.entry_board.unlockRequested.connect(self.unlock_bet)
        self.entry_board.autoFocusRequested.connect(self._on_auto_focus)
        self.entry_board.visibleMarketChanged.connect(self.controller.set_visible_market)
        izquierda = QWidget()
        columna = QVBoxLayout(izquierda)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(8)
        self.metrics_scroll = QScrollArea()
        self.metrics_scroll.setWidgetResizable(True)
        self.metrics_scroll.setFrameShape(QFrame.NoFrame)
        self.metrics_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.metrics_scroll.setWidget(self.metrics_panel)
        columna.addWidget(self.metrics_scroll, 1)
        splitter.addWidget(izquierda)
        splitter.addWidget(self.entry_board)
        # El tablero de lineas es el elemento dominante: es donde se detecta
        # el momento de entrada, que es la funcion principal del programa.
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([460, 700])

        # El registro manual se mantiene debajo del radar principal.
        # El splitter vertical permite reducirlo si se quiere dedicar mas
        # espacio al seguimiento en vivo.
        panel_splitter = QSplitter(Qt.Vertical)
        panel_splitter.addWidget(splitter)
        self.manual_bets_panel = ManualBetsPanel(self.controller)
        panel_splitter.addWidget(self.manual_bets_panel)
        panel_splitter.setStretchFactor(0, 5)
        panel_splitter.setStretchFactor(1, 2)
        panel_splitter.setCollapsible(0, False)
        panel_splitter.setCollapsible(1, True)
        panel_splitter.setSizes([570, 250])

        self.tabs = QTabWidget()
        self.tabs.addTab(panel_splitter, "Panel")
        self.diagnostics = DiagnosticsPanel(self.controller.log)
        diagnostics_tab = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics_tab)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        diagnostics_layout.setSpacing(8)
        diagnostics_layout.addWidget(self.connection_panel)
        diagnostics_layout.addWidget(self.diagnostics, 1)
        self.tabs.addTab(diagnostics_tab, "Diagnostico")
        layout.addWidget(self.tabs, 1)

        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel("Listo")
        self.status.addWidget(self.status_label, 1)
        self.betplay_status_label = QLabel("BETPLAY DESCONECTADO")
        self.betplay_status_label.setObjectName("status")
        self.status.addPermanentWidget(self.betplay_status_label)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.setToolTip(
            "Cada casa puede tener su propio perfil. Por ejemplo: "
            "'Stake principal' y 'BetPlay principal'."
        )
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)

        self.configure_button = QPushButton("CONFIGURAR")
        self.configure_button.clicked.connect(self.configure_profile)
        self.new_profile_button = QPushButton("NUEVO PERFIL")
        self.new_profile_button.setToolTip(
            "Crea un perfil independiente para otra casa de apuestas, como Stake.")
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
        self.baseline_button.setVisible(False)

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
    def _set_profile_controls_enabled(self, enabled: bool) -> None:
        # CONFIGURAR sigue disponible porque su flujo pausa y reanuda el
        # lector. En cambio, cambiar o crear otra casa durante una sesion
        # mezclaria perfil, regiones e historial.
        self.profile_combo.setEnabled(enabled)
        self.new_profile_button.setEnabled(enabled)

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
                "No hay perfiles. Pulsa 'NUEVO PERFIL' y crea uno para tu casa "
                "(por ejemplo, Stake).")

    def _on_profile_changed(self, name: str) -> None:
        if not name:
            return

        # El Reader ya queda ligado a un perfil y a sus fuentes. No se cambia
        # de casa a mitad de una sesion activa.
        active = self.controller.reader is not None
        current = self.controller.profile
        if active and current is not None and current.name != name:
            self.profile_combo.blockSignals(True)
            self.profile_combo.setCurrentText(current.name)
            self.profile_combo.blockSignals(False)
            QMessageBox.information(
                self,
                "Cambiar de perfil",
                "Finaliza el partido actual antes de cambiar a otra casa de apuestas.",
            )
            return

        profile = self.controller.load_profile(name)
        if profile is None:
            return

        sportsbook = profile.sportsbook or profile.name
        self.manual_bets_panel.set_default_sportsbook(sportsbook)

        missing = profile.missing_required()
        if missing:
            faltan = ", ".join(k.display_name for k in missing)
            self.status_label.setText(
                f"Perfil '{name}' ({sportsbook}): faltan regiones -> {faltan}"
            )
        else:
            self.status_label.setText(
                f"Perfil '{name}' ({sportsbook}) listo. Pulsa INICIAR."
            )

    def new_profile(self) -> None:
        if self.controller.reader is not None:
            QMessageBox.information(
                self,
                "Nuevo perfil",
                "Finaliza el partido actual antes de crear o cambiar a otra casa.",
            )
            return

        name, ok = QInputDialog.getText(
            self,
            "Nuevo perfil",
            "Nombre unico del perfil (ej.: Stake principal):",
        )
        name = name.strip() if ok else ""
        if not name:
            return

        if self.controller.profile_exists(name):
            QMessageBox.warning(
                self,
                "Nuevo perfil",
                f"Ya existe un perfil llamado '{name}'. Usa un nombre distinto.",
            )
            return

        profile = self.controller.new_profile(name)
        self._edit_profile(profile)

    def configure_profile(self) -> None:
        profile = self.controller.profile
        if profile is None:
            self.new_profile()
            return
        self._edit_profile(profile)

    def _edit_profile(self, profile) -> None:
        reader = self.controller.reader

        # Solo debemos reanudar si realmente estaba leyendo.
        resume_reader = (
            reader is not None
            and not reader.is_paused
        )

        original_name = profile.name
        original_profile_id = profile.profile_id

        # Mientras se abre el selector de ROI no dejamos que el timer de la
        # ventana siga refrescando los mismos objetos.
        self.timer.stop()

        if resume_reader:
            reader.pause()

        try:
            capture = self.controller.capture
            engine = self.controller.ensure_engine(profile.engine)

            dialog = ProfileDialog(
                profile,
                capture,
                engine,
                self,
            )

            if not dialog.exec():
                return

            edited = dialog.profile

            try:
                self.controller.save_profile(edited)

            except ValueError as exc:
                QMessageBox.warning(
                    self,
                    "Perfil",
                    str(exc),
                )
                return

            self._refresh_profiles()
            self.profile_combo.setCurrentText(edited.name)

            self.manual_bets_panel.set_default_sportsbook(
                edited.sportsbook or edited.name
            )

            # Si el lector vivo utiliza este mismo perfil, actualizamos sus
            # regiones y layout sin destruir la sesion actual.
            if reader is not None:
                manager = getattr(
                    reader,
                    "roi_manager",
                    None,
                )

                if manager is not None:
                    reader_profile = manager.profile

                    if (
                        original_profile_id is not None
                        and reader_profile.profile_id is not None
                    ):
                        same_profile = (
                            reader_profile.profile_id
                            == original_profile_id
                        )
                    else:
                        same_profile = (
                            reader_profile.name
                            == original_name
                        )

                    if same_profile:
                        manager.profile = edited
                        manager.refresh_layout()

        except CaptureError as exc:
            QMessageBox.critical(
                self,
                "Captura",
                str(exc),
            )

        finally:
            if resume_reader and reader is not None:
                reader.resume()

            self.timer.start()

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
            self._set_profile_controls_enabled(False)
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
        self._set_profile_controls_enabled(True)
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
    def _maybe_autostart(self) -> None:
        """Arranca sola la sesion en cuanto la extension trae lo necesario.

        Es lo que convierte el uso diario en 'abrir las dos cosas y ya': no hay
        que pulsar INICIAR ni definir regiones si el DOM cubre los datos.
        """
        if self.controller.reader is not None or self._autostart_blocked:
            return
        if not self.controller.browser.is_live:
            return
        if self.controller.missing_requirements(self.controller.profile):
            return
        reader = self.controller.start_session(self.controller.profile)
        if reader is None:
            # No se reintenta en bucle: si fallo, hara falta accion del usuario.
            self._autostart_blocked = True
            return
        self.start_button.setText("PAUSAR (F8)")
        self.finish_button.setEnabled(True)
        self._set_profile_controls_enabled(False)
        self.status_label.setText(
            "BETPLAY CONECTADO. Radar activo sin regiones manuales.")

    def _refresh(self) -> None:
        self._maybe_autostart()
        reader = self.controller.reader
        snapshot = reader.last_snapshot if reader else None
        view = self.controller.build_view_model(snapshot)
        self._update_betplay_status(view.link_state)
        if view.snapshot is None or view.general is None:
            self.baseline_button.setVisible(False)
            # Todavia sin sesion: el panel de conexion es justo lo que hay que
            # poder mirar ahora, para saber que falta.
            self.connection_panel.update_view(
                link_state=view.link_state, age_seconds=view.link_age_seconds,
                field_sources=view.field_sources, latency_ms=view.link_latency_ms,
                conflicts=view.source_conflicts,
                extension_state=view.extension_state, waiting_for=view.waiting_for,
            )
            self._update_waiting_status(view)
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
        self.baseline_button.setVisible(bool(view.snapshot.needs_period_baseline))
        self.connection_panel.update_view(
            link_state=view.link_state, age_seconds=view.link_age_seconds,
            field_sources=view.field_sources, latency_ms=view.link_latency_ms,
            conflicts=view.source_conflicts,
            extension_state=view.extension_state, waiting_for=view.waiting_for,
        )
        self.entry_board.update_board(
            blocks=view.blocks, criteria=view.criteria, focus=view.focus,
            in_transition=view.snapshot.market_in_transition,
            now=view.snapshot.ts,
        )
        self._update_status(view)
        self._check_event_change()

    def _update_betplay_status(self, link_state: LinkState) -> None:
        """Indicador operativo minimo; el detalle permanece en Diagnostico."""
        if link_state is LinkState.LIVE:
            text, color = "BETPLAY ✓", "#3ddc84"
        elif link_state is LinkState.STALE:
            text, color = "BETPLAY DESACTUALIZADO", "#ffbf3f"
        else:
            text, color = "BETPLAY DESCONECTADO", "#8b97a8"
        self.betplay_status_label.setText(text)
        self.betplay_status_label.setStyleSheet(
            f"color: {color}; font-weight: 700; padding: 0 8px;")

    def _update_waiting_status(self, view) -> None:
        """Que se ve mientras no hay sesion. Nunca un error como primera opcion."""
        if view.session_state is SessionState.RUNNING:
            # La sesion acaba de arrancar y todavia no ha completado un ciclo:
            # el mensaje del arranque sigue siendo el bueno.
            return
        if view.session_state is SessionState.READY:
            self.status_label.setText("LISTO PARA EMPEZAR")
            return
        if view.extension_state is ExtensionState.DISCONNECTED:
            self.status_label.setText(
                "Esperando a la extension. Abre BetPlay en un partido en vivo, "
                "o define las regiones como ultimo recurso.")
            return
        faltan = ", ".join(view.waiting_for) or "datos"
        self.status_label.setText(f"EXTENSION CONECTADA. Esperando {faltan}.")

    def _check_event_change(self) -> None:
        """La extension cambio de partido: no se mezclan eventos."""
        cambio = self.controller.browser.clear_event_change()
        if cambio is None:
            return
        if self.controller.locked_bet is not None:
            respuesta = QMessageBox.question(
                self, "Cambio de partido",
                f"La extension esta viendo otro partido ({cambio['name'] or cambio['to']}).\n\n"
                "Tienes una apuesta fijada. ¿Cerrar la sesion actual y empezar una nueva?")
            if respuesta != QMessageBox.Yes:
                return
        self.controller.finish_game()
        self._autostart_blocked = False
        self.start_button.setText("INICIAR (F8)")
        self.finish_button.setEnabled(False)
        self.status_label.setText(
            f"Nuevo partido detectado: {cambio['name'] or cambio['to']}")

    def _update_status(self, view) -> None:
        snapshot = view.snapshot
        parts = [view.mode.label]
        # Esperar datos NO es un error: se dice lo que falta, no "no se puede
        # iniciar, faltan regiones". El ROI es el ultimo recurso.
        if view.session_state is SessionState.WAITING_FOR_DATA and view.waiting_for:
            parts.append(f"ESPERANDO: {', '.join(view.waiting_for)}")
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
