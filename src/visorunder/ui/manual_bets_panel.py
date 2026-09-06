"""Panel de APUESTAS MANUALES: seguimiento en vivo, no un historial de dinero.

Una apuesta manual se introduce una vez (casa, mercado, lado, linea, cuota) y
a partir de ahi la aplicacion la sigue sola con el marcador real del partido:
cuantos puntos lleva SU mercado, cuanto margen queda, cuantos puntos hacen
cruzar la linea, que proyecta el ritmo y de que lado cae esa proyeccion.

La jerarquia visual sigue esa idea:

* la tabla ensena primero el seguimiento deportivo (ACTUAL, MARGEN, PUNTOS
  P/CRUZAR, PROYECCION, DIF. LINEA) y deja MONTO y UTILIDAD al final, donde no
  desplazan a lo importante; la tabla tiene scroll horizontal para que ninguna
  columna se coma a las demas;
* debajo hay un bloque de detalle de la apuesta seleccionada, con el mismo
  espiritu que la tarjeta "MI APUESTA" del panel principal;
* el conteo (total, pendientes, ganadas, perdidas, utilidad, ROI) sigue
  existiendo como informacion secundaria, en una sola linea.

Los numeros los calcula `calculations.manual_tracking`, que reutiliza el mismo
motor que el radar. Aqui solo se pintan.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app import AppController
from ..calculations.manual_tracking import ManualBetTracking, TrackingStatus
from ..config.profiles import KNOWN_SPORTSBOOKS
from ..domain.manual_bet import ManualBetStatus
from ..domain.market import MarketKey, Side
from . import formatters as fmt
from .styles import COLOR_DANGER, COLOR_MUTED, COLOR_OK, COLOR_TEXT, COLOR_WARN

MARKET_CHOICES = [
    ("GAME", "Partido"),
    ("Q1", "Q1"),
    ("Q2", "Q2"),
    ("Q3", "Q3"),
    ("Q4", "Q4"),
    ("H1", "1.a mitad"),
    ("H2", "2.a mitad"),
]

#: Columnas de la tabla. El seguimiento va primero; el dinero, al final.
COLUMNS = [
    ("ID", 0),
    ("CASA", 90),
    ("MERCADO", 80),
    ("APUESTA", 105),
    ("ACTUAL", 70),
    ("MARGEN", 75),
    ("P/CRUZAR", 85),
    ("PROYECCION", 95),
    ("DIF. LINEA", 90),
    ("CUOTA", 60),
    ("ESTADO", 105),
    ("MONTO", 90),
    ("UTILIDAD", 90),
]
COL_ID = 0
COL_STATUS = 10

#: Color de cada estado de seguimiento.
STATUS_COLORS = {
    TrackingStatus.FAVORABLE: COLOR_OK,
    TrackingStatus.AT_RISK: COLOR_WARN,
    TrackingStatus.EXCEEDED: COLOR_DANGER,
    TrackingStatus.WON: COLOR_OK,
    TrackingStatus.LOST: COLOR_DANGER,
    TrackingStatus.PUSH: COLOR_MUTED,
    TrackingStatus.NOT_STARTED: COLOR_MUTED,
    TrackingStatus.NO_DATA: COLOR_MUTED,
}


def _market_key(value: str) -> MarketKey:
    value = (value or "GAME").upper()
    if value == "GAME":
        return MarketKey.game()
    if value.startswith("Q"):
        return MarketKey.quarter(int(value[1:]))
    if value.startswith("H"):
        return MarketKey.half_market(int(value[1:]))
    raise ValueError(f"Mercado manual no soportado: {value}")


def _money(value: Optional[float]) -> str:
    if value is None:
        return fmt.UNKNOWN
    return f"$ {value:,.0f}".replace(",", ".")


def _signed(value: Optional[float], decimals: int = 1) -> str:
    """Numero con signo explicito. El signo es la lectura rapida."""
    if value is None:
        return fmt.UNKNOWN
    return f"{value:+.{decimals}f}"


class ManualBetsPanel(QWidget):
    """Formulario + seguimiento en vivo + detalle + conteo."""

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._default_sportsbook = ""
        self._tracking: List[ManualBetTracking] = []
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------- construccion
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        box = QGroupBox("APUESTAS MANUALES - seguimiento en vivo")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(6)
        box_layout.addLayout(self._build_form())
        box_layout.addWidget(self._build_table(), 1)
        box_layout.addWidget(self._build_detail())
        box_layout.addLayout(self._build_actions())
        box_layout.addLayout(self._build_summary())
        root.addWidget(box)

    def _build_form(self) -> QGridLayout:
        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)

        self.sportsbook_combo = QComboBox()
        self.sportsbook_combo.setEditable(True)
        self.sportsbook_combo.addItems(KNOWN_SPORTSBOOKS)
        self.sportsbook_combo.setMinimumWidth(110)
        self.sportsbook_combo.setToolTip(
            "Puedes elegir una casa de la lista o escribir cualquier otra, por ejemplo Stake.\n"
            "La casa no cambia el calculo: el marcador es del partido, no de la casa.")

        self.event_edit = QLineEdit()
        self.event_edit.setPlaceholderText("Partido / evento (opcional)")
        self.event_edit.setMinimumWidth(155)

        self.market_combo = QComboBox()
        for value, label in MARKET_CHOICES:
            self.market_combo.addItem(label, value)
        self.market_combo.setToolTip(
            "El mercado decide QUE puntos se miran: Q4 usa los del Q4, "
            "1.a mitad usa Q1+Q2 y Partido usa el total.")

        self.side_combo = QComboBox()
        self.side_combo.addItem("UNDER", Side.UNDER.value)
        self.side_combo.addItem("OVER", Side.OVER.value)

        self.line_spin = QDoubleSpinBox()
        self.line_spin.setRange(0.0, 9999.5)
        self.line_spin.setDecimals(1)
        self.line_spin.setSingleStep(0.5)
        self.line_spin.setValue(40.5)

        self.odds_spin = QDoubleSpinBox()
        self.odds_spin.setRange(1.01, 1000.0)
        self.odds_spin.setDecimals(2)
        self.odds_spin.setSingleStep(0.01)
        self.odds_spin.setValue(1.80)

        self.stake_spin = QDoubleSpinBox()
        self.stake_spin.setRange(0.0, 999_999_999_999.0)
        self.stake_spin.setDecimals(0)
        self.stake_spin.setSingleStep(1000.0)
        self.stake_spin.setValue(0.0)
        self.stake_spin.setPrefix("$ ")
        self.stake_spin.setSpecialValueText("$ (opcional)")
        self.stake_spin.setToolTip(
            "Opcional. Sin monto la apuesta se sigue igual; solo no entra en "
            "el conteo de utilidad y ROI.")

        self.add_button = QPushButton("AGREGAR Y SEGUIR")
        self.add_button.setObjectName("primary")
        self.add_button.clicked.connect(self._add_bet)

        form.addWidget(QLabel("Casa"), 0, 0)
        form.addWidget(self.sportsbook_combo, 1, 0)
        form.addWidget(QLabel("Evento"), 0, 1)
        form.addWidget(self.event_edit, 1, 1)
        form.addWidget(QLabel("Mercado"), 0, 2)
        form.addWidget(self.market_combo, 1, 2)
        form.addWidget(QLabel("Lado"), 0, 3)
        form.addWidget(self.side_combo, 1, 3)
        form.addWidget(QLabel("Linea"), 0, 4)
        form.addWidget(self.line_spin, 1, 4)
        form.addWidget(QLabel("Cuota"), 0, 5)
        form.addWidget(self.odds_spin, 1, 5)
        form.addWidget(QLabel("Monto"), 0, 6)
        form.addWidget(self.stake_spin, 1, 6)
        form.addWidget(self.add_button, 1, 7)
        form.setColumnStretch(1, 1)
        return form

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(120)
        self.table.setColumnHidden(COL_ID, True)
        # Ninguna columna se come a las demas: anchura propia y scroll
        # horizontal cuando no caben todas.
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        for index, (_, width) in enumerate(COLUMNS):
            if width:
                self.table.setColumnWidth(index, width)
        self.table.itemSelectionChanged.connect(self._update_detail)
        return self.table

    def _build_detail(self) -> QFrame:
        """Bloque de detalle, con el mismo espiritu que 'MI APUESTA'."""
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.detail_title = QLabel("Selecciona una apuesta para ver su seguimiento")
        self.detail_title.setObjectName("metricValue")
        layout.addWidget(self.detail_title)

        self.detail_headline = QLabel("")
        self.detail_headline.setObjectName("status")
        self.detail_headline.setWordWrap(True)
        layout.addWidget(self.detail_headline)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(2)
        self.detail_values = {}
        campos = [
            ("line", "Linea apostada"),
            ("current", "Puntos actuales"),
            ("margin", "Margen"),
            ("tolerable", "Puntos que caben"),
            ("cross", "Puntos para superar"),
            ("projection", "Proyeccion"),
            ("difference", "Dif. contra linea"),
            ("pace", "Ritmo actual"),
            ("required", "Ritmo para cruzar"),
            ("status", "Estado"),
        ]
        for index, (clave, etiqueta) in enumerate(campos):
            fila, columna = divmod(index, 5)
            titulo = QLabel(etiqueta)
            titulo.setObjectName("metricLabel")
            valor = QLabel(fmt.UNKNOWN)
            valor.setObjectName("metricValue")
            grid.addWidget(titulo, fila * 2, columna)
            grid.addWidget(valor, fila * 2 + 1, columna)
            self.detail_values[clave] = valor
        layout.addLayout(grid)
        self.detail_card = card
        return card

    def _build_actions(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        self.won_button = QPushButton("GANADA")
        self.lost_button = QPushButton("PERDIDA")
        self.void_button = QPushButton("NULA")
        self.pending_button = QPushButton("PENDIENTE")
        self.delete_button = QPushButton("ELIMINAR")
        self.won_button.clicked.connect(lambda: self._settle_selected(ManualBetStatus.WON))
        self.lost_button.clicked.connect(lambda: self._settle_selected(ManualBetStatus.LOST))
        self.void_button.clicked.connect(lambda: self._settle_selected(ManualBetStatus.VOID))
        self.pending_button.clicked.connect(lambda: self._settle_selected(ManualBetStatus.PENDING))
        self.delete_button.clicked.connect(self._delete_selected)
        actions.addWidget(QLabel("Resultado de la fila seleccionada:"))
        actions.addWidget(self.won_button)
        actions.addWidget(self.lost_button)
        actions.addWidget(self.void_button)
        actions.addWidget(self.pending_button)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        return actions

    def _build_summary(self) -> QHBoxLayout:
        summary = QHBoxLayout()
        summary.setSpacing(14)
        self.count_label = QLabel()
        self.results_label = QLabel()
        self.money_label = QLabel()
        for etiqueta in (self.count_label, self.results_label, self.money_label):
            etiqueta.setObjectName("status")
        summary.addWidget(self.count_label)
        summary.addWidget(self.results_label)
        summary.addWidget(self.money_label)
        summary.addStretch(1)
        return summary

    # ----------------------------------------------------------------- datos
    def set_default_sportsbook(self, sportsbook: str) -> None:
        sportsbook = (sportsbook or "").strip()
        current = self.sportsbook_combo.currentText().strip()
        if sportsbook and (not current or current == self._default_sportsbook or current == "Stake"):
            self.sportsbook_combo.setCurrentText(sportsbook)
        self._default_sportsbook = sportsbook

    def _add_bet(self) -> None:
        sportsbook = self.sportsbook_combo.currentText().strip()
        if not sportsbook:
            QMessageBox.warning(self, "Apuesta manual", "Escribe la casa de apuestas.")
            return
        try:
            bet = self.controller.add_manual_bet(
                sportsbook=sportsbook,
                event=self.event_edit.text().strip(),
                key=_market_key(self.market_combo.currentData()),
                side=Side(self.side_combo.currentData()),
                line=float(self.line_spin.value()),
                odds=float(self.odds_spin.value()),
                # Siempre un numero: `None` esta reservado para el flujo del
                # Browser Bridge, que no se toca.
                stake=float(self.stake_spin.value()),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Apuesta manual", str(exc))
            return

        self.event_edit.clear()
        self.refresh(select_bet_id=bet.bet_id)

    def _selected_bet_id(self) -> Optional[int]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), COL_ID)
        return int(item.text()) if item is not None and item.text() else None

    def _settle_selected(self, status: ManualBetStatus) -> None:
        bet_id = self._selected_bet_id()
        if bet_id is None:
            QMessageBox.information(self, "Apuesta manual", "Selecciona primero una apuesta.")
            return
        self.controller.settle_manual_bet(bet_id, status)
        self.refresh(select_bet_id=bet_id)

    def _delete_selected(self) -> None:
        bet_id = self._selected_bet_id()
        if bet_id is None:
            QMessageBox.information(self, "Apuesta manual", "Selecciona primero una apuesta.")
            return
        answer = QMessageBox.question(
            self,
            "Eliminar apuesta manual",
            f"Se eliminara definitivamente la apuesta #{bet_id}. Continuar?",
        )
        if answer != QMessageBox.Yes:
            return
        self.controller.delete_manual_bet(bet_id)
        self.refresh()

    # ---------------------------------------------------------------- pintar
    def update_tracking(self, tracking: List[ManualBetTracking]) -> None:
        """Refresco en vivo desde el ciclo de la ventana principal.

        Se llama en cada lectura, asi que solo reconstruye la tabla cuando
        cambia el conjunto de apuestas; en el caso normal actualiza las celdas
        de seguimiento y conserva la seleccion del usuario.
        """
        anteriores = [t.bet.bet_id for t in self._tracking]
        actuales = [t.bet.bet_id for t in tracking]
        self._tracking = list(tracking)
        if anteriores != actuales:
            self.refresh()
            return
        for row, seguimiento in enumerate(self._tracking):
            self._fill_row(row, seguimiento)
        self._update_detail()

    def refresh(self, select_bet_id: Optional[int] = None) -> None:
        """Reconstruye la tabla entera desde el libro guardado."""
        self.controller._invalidate_manual_ledger()
        self._tracking = self.controller.manual_bet_tracking()

        self.table.setRowCount(len(self._tracking))
        selected_row = None
        for row, seguimiento in enumerate(self._tracking):
            self._fill_row(row, seguimiento)
            if select_bet_id is not None and seguimiento.bet.bet_id == select_bet_id:
                selected_row = row

        if selected_row is not None:
            self.table.selectRow(selected_row)
        elif self._tracking and not self.table.selectionModel().hasSelection():
            self.table.selectRow(0)

        self._update_summary()
        self._update_detail()

    def _fill_row(self, row: int, seguimiento: ManualBetTracking) -> None:
        bet = seguimiento.bet
        profit = bet.profit
        valores = [
            str(bet.bet_id or ""),
            bet.sportsbook,
            seguimiento.market_label,
            seguimiento.description,
            fmt.integer(seguimiento.scope_points),
            _signed(seguimiento.margin),
            fmt.integer(seguimiento.points_to_cross),
            fmt.projection(seguimiento.projection),
            _signed(seguimiento.projection_vs_line),
            f"{bet.odds:.2f}",
            self._status_text(seguimiento),
            _money(bet.stake) if bet.has_stake else fmt.UNKNOWN,
            _money(profit),
        ]
        for column, texto in enumerate(valores):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, column, item)
            item.setText(texto)
            if column >= 4:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if bet.event:
                item.setToolTip(bet.event)

        color = QColor(self._status_color(seguimiento))
        self.table.item(row, COL_STATUS).setForeground(color)

    def _status_text(self, seguimiento: ManualBetTracking) -> str:
        """El resultado que TU marcaste manda sobre el seguimiento en vivo."""
        if seguimiento.bet.status is not ManualBetStatus.PENDING:
            return seguimiento.bet.status.label
        return seguimiento.status.label

    def _status_color(self, seguimiento: ManualBetTracking) -> str:
        estado = seguimiento.bet.status
        if estado is ManualBetStatus.WON:
            return COLOR_OK
        if estado is ManualBetStatus.LOST:
            return COLOR_DANGER
        if estado is ManualBetStatus.VOID:
            return COLOR_MUTED
        return STATUS_COLORS.get(seguimiento.status, COLOR_TEXT)

    def _selected_tracking(self) -> Optional[ManualBetTracking]:
        bet_id = self._selected_bet_id()
        if bet_id is None:
            return None
        return next((t for t in self._tracking if t.bet.bet_id == bet_id), None)

    def _update_detail(self) -> None:
        seguimiento = self._selected_tracking()
        if seguimiento is None:
            self.detail_title.setText("Selecciona una apuesta para ver su seguimiento")
            self.detail_headline.setText("")
            for etiqueta in self.detail_values.values():
                etiqueta.setText(fmt.UNKNOWN)
            return

        bet = seguimiento.bet
        self.detail_title.setText(
            f"{bet.sportsbook}   |   {seguimiento.market_label}   |   "
            f"{seguimiento.description} @ {bet.odds:.2f}")

        titular = seguimiento.describe_margin()
        if seguimiento.unavailable_reason:
            titular = seguimiento.unavailable_reason
        self.detail_headline.setText(titular)

        self.detail_values["line"].setText(fmt.line(bet.line))
        self.detail_values["current"].setText(fmt.integer(seguimiento.scope_points))
        self.detail_values["margin"].setText(_signed(seguimiento.margin))
        self.detail_values["tolerable"].setText(
            fmt.integer(seguimiento.tolerable_points)
            if bet.side is Side.UNDER else fmt.UNKNOWN)
        self.detail_values["cross"].setText(fmt.integer(seguimiento.points_to_cross))
        self.detail_values["projection"].setText(fmt.projection(seguimiento.projection))
        self.detail_values["difference"].setText(_signed(seguimiento.projection_vs_line))
        self.detail_values["pace"].setText(fmt.pace(seguimiento.current_pace))
        self.detail_values["required"].setText(fmt.pace(seguimiento.required_pace))

        estado = self.detail_values["status"]
        estado.setText(self._status_text(seguimiento))
        estado.setStyleSheet(
            f"color: {self._status_color(seguimiento)}; font-size: 15px; font-weight: 700;")

    def _update_summary(self) -> None:
        summary = self.controller.manual_bet_summary()
        hit_rate = fmt.UNKNOWN if summary.hit_rate is None else f"{summary.hit_rate:.1f}%"
        roi = fmt.UNKNOWN if summary.roi is None else f"{summary.roi:+.1f}%"
        self.count_label.setText(
            f"TOTAL {summary.total}   |   PENDIENTES {summary.pending}")
        self.results_label.setText(
            f"GANADAS {summary.won}   |   PERDIDAS {summary.lost}   |   NULAS {summary.void}   |   "
            f"ACIERTO {hit_rate}")
        self.money_label.setText(
            f"APOSTADO {_money(summary.total_staked)}   |   "
            f"UTILIDAD {_money(summary.net_profit)}   |   ROI {roi}")
