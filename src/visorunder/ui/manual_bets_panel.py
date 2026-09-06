"""Panel compacto para registrar y contabilizar apuestas manuales."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
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
from ..config.profiles import KNOWN_SPORTSBOOKS
from ..domain.manual_bet import ManualBetStatus
from ..domain.market import MarketKey, Side


MARKET_CHOICES = [
    ("GAME", "Partido"),
    ("Q1", "Q1"),
    ("Q2", "Q2"),
    ("Q3", "Q3"),
    ("Q4", "Q4"),
    ("H1", "1.a mitad"),
    ("H2", "2.a mitad"),
]


def _market_key(value: str) -> MarketKey:
    value = (value or "GAME").upper()
    if value == "GAME":
        return MarketKey.game()
    if value.startswith("Q"):
        return MarketKey.quarter(int(value[1:]))
    if value.startswith("H"):
        return MarketKey.half_market(int(value[1:]))
    raise ValueError(f"Mercado manual no soportado: {value}")


def _money(value: float) -> str:
    return f"$ {value:,.0f}".replace(",", ".")


class ManualBetsPanel(QWidget):
    """Formulario + historial + conteo de apuestas introducidas a mano."""

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._default_sportsbook = ""
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        box = QGroupBox("APUESTAS MANUALES - registro y conteo")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(6)

        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)

        self.sportsbook_combo = QComboBox()
        self.sportsbook_combo.setEditable(True)
        self.sportsbook_combo.addItems(KNOWN_SPORTSBOOKS)
        self.sportsbook_combo.setMinimumWidth(110)
        self.sportsbook_combo.setToolTip(
            "Puedes elegir una casa de la lista o escribir cualquier otra, por ejemplo Stake.")

        self.event_edit = QLineEdit()
        self.event_edit.setPlaceholderText("Partido / evento (opcional)")
        self.event_edit.setMinimumWidth(155)

        self.market_combo = QComboBox()
        for value, label in MARKET_CHOICES:
            self.market_combo.addItem(label, value)

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
        self.stake_spin.setRange(1.0, 999_999_999_999.0)
        self.stake_spin.setDecimals(0)
        self.stake_spin.setSingleStep(1000.0)
        self.stake_spin.setValue(10_000.0)
        self.stake_spin.setPrefix("$ ")

        self.add_button = QPushButton("AGREGAR APUESTA")
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
        box_layout.addLayout(form)

        summary = QHBoxLayout()
        summary.setSpacing(14)
        self.count_label = QLabel()
        self.results_label = QLabel()
        self.money_label = QLabel()
        self.count_label.setObjectName("metricValue")
        self.results_label.setObjectName("metricValue")
        self.money_label.setObjectName("metricValue")
        summary.addWidget(self.count_label)
        summary.addWidget(self.results_label)
        summary.addWidget(self.money_label)
        summary.addStretch(1)
        box_layout.addLayout(summary)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["ID", "CASA", "MERCADO", "APUESTA", "CUOTA", "MONTO", "ESTADO", "UTILIDAD"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(110)
        self.table.setMaximumHeight(170)
        self.table.setColumnHidden(0, True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        box_layout.addWidget(self.table)

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
        box_layout.addLayout(actions)

        self.help_label = QLabel(
            "El conteo se guarda en SQLite. GANADA suma monto x (cuota - 1); "
            "PERDIDA resta el monto; NULA deja utilidad 0. Pendientes no entran al ROI.")
        self.help_label.setObjectName("status")
        self.help_label.setWordWrap(True)
        box_layout.addWidget(self.help_label)

        root.addWidget(box)

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
        item = self.table.item(rows[0].row(), 0)
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

    def refresh(self, select_bet_id: Optional[int] = None) -> None:
        bets = self.controller.list_manual_bets(100)
        self.table.setRowCount(len(bets))
        selected_row = None
        for row, bet in enumerate(bets):
            profit = bet.profit
            values = [
                str(bet.bet_id or ""),
                bet.sportsbook,
                bet.key.label.replace(" - Total de puntos", ""),
                f"{bet.side.value} {bet.line:g}",
                f"{bet.odds:.2f}",
                _money(bet.stake),
                bet.status.label,
                "--" if profit is None else _money(profit),
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column in (4, 5, 7):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if bet.event:
                    item.setToolTip(bet.event)
                self.table.setItem(row, column, item)
            if select_bet_id is not None and bet.bet_id == select_bet_id:
                selected_row = row

        if selected_row is not None:
            self.table.selectRow(selected_row)

        summary = self.controller.manual_bet_summary()
        hit_rate = "--" if summary.hit_rate is None else f"{summary.hit_rate:.1f}%"
        roi = "--" if summary.roi is None else f"{summary.roi:+.1f}%"
        self.count_label.setText(
            f"TOTAL {summary.total}   |   PENDIENTES {summary.pending}")
        self.results_label.setText(
            f"GANADAS {summary.won}   |   PERDIDAS {summary.lost}   |   NULAS {summary.void}   |   "
            f"ACIerto {hit_rate}".upper())
        self.money_label.setText(
            f"APOSTADO {_money(summary.total_staked)}   |   UTILIDAD {_money(summary.net_profit)}   |   ROI {roi}")
