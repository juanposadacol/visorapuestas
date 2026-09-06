"""Tablero de entrada: la pantalla principal mientras buscas el momento.

Muestra TODAS las lineas que la casa ofrece ahora mismo, cada una con sus
numeros y su senal, para poder leer la situacion de un vistazo de uno o dos
segundos.

Columnas acordadas:
    LINEA | CUOTA U | VS REFERENCIA | VS CUARTO | VS MITAD | VS PARTIDO |
    PROMEDIO ACTUAL | PUNTOS FALTANTES | PROMEDIO FALTANTE | SENAL

Las comparaciones van juntas y delante porque son la lectura rapida; los
promedios y los puntos quedan detras como respaldo. La senal cierra siempre.

La senal se transmite SIEMPRE con etiqueta de texto ademas del color, para no
depender de la vista cromatica ni de la iluminacion de la pantalla.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calculations.entry import LineEvaluation, MarketEvaluation
from ..config.criteria import EntryCriteria
from ..domain.event_markets import FreshnessState
from ..domain.market import MarketKey, MarketSnapshot, Side
from . import formatters as fmt
from .flow_layout import FlowRow

COLUMNS = ["LINEA", "CUOTA U", "VS REF.", "VS Q", "VS MITAD", "VS PARTIDO",
           "PROM. ACTUAL", "PUNTOS FALT.", "PROM. FALT.", "SENAL"]
#: Los indices se desempaquetan EN EL MISMO ORDEN que `COLUMNS`, y la lista de
#: valores de cada fila se construye tambien en ese orden. Cambiar el orden
#: obliga a mover los tres sitios a la vez o los datos quedarian bajo otro
#: encabezado.
(COL_LINE, COL_ODDS, COL_REF, COL_QUARTER, COL_HALF, COL_GAME,
 COL_CURRENT_PACE, COL_POINTS, COL_MISSING_PACE, COL_SIGNAL) = range(10)
# Alias historico: RITMO NEC. y PROMEDIO FALTANTE son la misma metrica.
COL_PACE = COL_MISSING_PACE

#: Color de la cabecera segun la frescura del mercado.
FRESHNESS_COLORS = {
    FreshnessState.LIVE: "#3ddc84",
    FreshnessState.RECENT: "#ffbf3f",
    FreshnessState.STALE: "#ff5c5c",
    FreshnessState.REVIEWING: "#3fa7ff",
    FreshnessState.UNAVAILABLE: "#8b97a8",
}


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


class MarketBlock(QWidget):
    """Un mercado del evento: cabecera con su frescura y su tabla de lineas."""

    lineSelected = Signal(object)      # LineEvaluation
    lineActivated = Signal(object)     # doble clic

    def __init__(self, key: MarketKey, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self._evaluations: List[LineEvaluation] = []
        self._signature: tuple = ()
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QHBoxLayout()
        self.title_label = QLabel(key.label)
        self.title_label.setObjectName("sectionTitle")
        self.state_label = QLabel("")
        self.state_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # La frescura no puede recortarse: es lo que impide leer un dato viejo
        # como si fuera actual.
        self.state_label.setMinimumWidth(240)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.state_label)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_SIGNAL,
                                                           QHeaderView.ResizeToContents)
        # `Stretch` reparte el ancho SIN suelo: en un panel estrecho las diez
        # columnas caian a 26 px y la cabecera se leia "INE OTA ; RE /S C".
        # Con un minimo por columna la tabla prefiere DESPLAZARSE en
        # horizontal antes que aplastar los numeros hasta hacerlos ilegibles.
        # Se mide con la fuente real, asi que acompana a la fuente y al DPI.
        self.table.horizontalHeader().setMinimumSectionSize(
            self.table.horizontalHeader().fontMetrics().horizontalAdvance("VS MITAD") + 8)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.cellDoubleClicked.connect(
            lambda *_: self.lineActivated.emit(self.selected_evaluation))
        layout.addWidget(self.table)

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

    def clear_selection(self) -> None:
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.blockSignals(False)

    def select_line_value(self, value: float) -> bool:
        for row, evaluation in enumerate(self._evaluations):
            if abs(evaluation.line_value - value) < 1e-6:
                self.table.blockSignals(True)
                self.table.selectRow(row)
                self.table.blockSignals(False)
                return True
        return False

    def _on_selection_changed(self) -> None:
        evaluation = self.selected_evaluation
        if evaluation is not None:
            self.lineSelected.emit(evaluation)

    # -------------------------------------------------------------- refresco
    def update_block(self, block: MarketEvaluation, criteria: EntryCriteria,
                     now: Optional[float] = None) -> None:
        """Repinta el bloque. La cabecera nunca oculta la antiguedad del dato."""
        self._evaluations = block.evaluations
        estado = block.freshness or FreshnessState.UNAVAILABLE
        edad = block.age_text(now)

        self.title_label.setText(block.label)
        # Regla critica: una linea vieja jamas se presenta como actual.
        texto = estado.label if estado.is_trustworthy_now else f"{estado.label}   ·   {edad}"
        self.state_label.setText(texto)
        self.state_label.setStyleSheet(
            f"color: {FRESHNESS_COLORS.get(estado, '#8b97a8')}; font-weight: 700;")

        signature = tuple(e.line_value for e in block.evaluations)
        rebuild = signature != self._signature
        if rebuild:
            self.table.blockSignals(True)
            self.table.setRowCount(len(block.evaluations))
            self._signature = signature

        for row, e in enumerate(block.evaluations):
            values = [
                fmt.line(e.line_value),                         # LINEA
                fmt.odds(e.under_odds),                         # CUOTA U
                _margin_text(e.margin_vs_reference),            # VS REF.
                _margin_text(e.margin_vs_period_pace),          # VS Q
                _margin_text(e.margin_vs_half_pace),            # VS MITAD
                _margin_text(e.margin_vs_game_pace),            # VS PARTIDO
                _pace_text(e.current_pace),                     # PROM. ACTUAL
                fmt.integer(e.points_to_exceed),                # PUNTOS FALT.
                _pace_text(e.required_pace),                    # PROM. FALT.
                # SENAL
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
                self.table.item(row, COL_SIGNAL).setText(f"{e.signal.label} · TRAMO FINAL")

        # Altura justa para sus filas: los bloques se apilan sin huecos.
        alto = self.table.horizontalHeader().height() + 4
        for row in range(self.table.rowCount()):
            alto += self.table.rowHeight(row)
        # Si las columnas no caben, la barra horizontal ocupa alto real: sin
        # reservarlo tapaba la ultima linea del mercado.
        cabecera = self.table.horizontalHeader()
        if cabecera.length() > self.table.viewport().width():
            alto += self.table.horizontalScrollBar().sizeHint().height()
        alto = max(60, alto)
        self.table.setFixedHeight(alto)
        self.setFixedHeight(alto + self.title_label.sizeHint().height() + 8)

        if rebuild:
            self.table.blockSignals(False)


class EntryBoard(QWidget):
    """Radar multi-mercado: un bloque por mercado, todos a la vez.

    Reune en una sola pantalla lo que la casa reparte en pestanas, y cada
    bloque dice sin rodeos cuando se leyo por ultima vez.
    """

    lineSelected = Signal(object)          # LineEvaluation elegida a mano
    lockRequested = Signal()
    unlockRequested = Signal()
    autoFocusRequested = Signal()          # volver al enfoque por cuota objetivo
    visibleMarketChanged = Signal(object)  # MarketKey forzada a mano, o None

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._blocks: Dict[MarketKey, MarketBlock] = {}
        self._order: List[MarketKey] = []
        self._criteria = EntryCriteria()
        self._locked = False
        self._selected: Optional[LineEvaluation] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = FlowRow(spacing=6, vertical_spacing=4)
        header.add(QLabel("Mercado visible:"))
        self.market_combo = QComboBox()
        # Un minimo de 210 px obligaba a la fila entera a medir 457 px y era
        # parte del suelo que impedia estrechar este panel. El desplegable
        # sigue siendo legible con menos y ademas ahora la fila se parte.
        self.market_combo.setMinimumWidth(140)
        self.market_combo.setToolTip(
            "Automatico usa el titulo leido en pantalla. Elige uno a mano si tu casa "
            "no muestra un titulo legible.")
        self.market_combo.addItem("Automatico (por el titulo)", None)
        for key in _selectable_markets():
            self.market_combo.addItem(key.label, key)
        self.market_combo.currentIndexChanged.connect(
            lambda _: self.visibleMarketChanged.emit(self.market_combo.currentData()))
        self.mode_label = QLabel("BUSCANDO ENTRADA")
        self.mode_label.setObjectName("sectionTitle")
        self.mode_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.add(self.market_combo)
        header.add_stretch()
        header.add(self.mode_label)
        layout.addWidget(header)

        self.review_label = QLabel("")
        self.review_label.setObjectName("danger")
        self.review_label.setWordWrap(True)
        self.review_label.setVisible(False)
        layout.addWidget(self.review_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(10)
        self._container_layout.addStretch(1)
        self.scroll.setWidget(self._container)
        layout.addWidget(self.scroll, 1)

        self.status_label = QLabel("Sin lineas leidas todavia")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(34)
        layout.addWidget(self.status_label)

        buttons = FlowRow(spacing=6, vertical_spacing=4)
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
        buttons.add(self.lock_button)
        buttons.add(self.unlock_button)
        buttons.add(self.auto_button)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- seleccion
    @property
    def selected_evaluation(self) -> Optional[LineEvaluation]:
        return self._selected

    def market_index(self, key: Optional[MarketKey]) -> int:
        """Indice del selector para esa clave.

        No se usa `findData`: Qt compara los datos como variantes y no
        reconoce la igualdad de dos MarketKey equivalentes.
        """
        for index in range(self.market_combo.count()):
            if self.market_combo.itemData(index) == key:
                return index
        return -1

    def select_visible_market(self, key: Optional[MarketKey]) -> None:
        index = self.market_index(key)
        if index >= 0:
            self.market_combo.setCurrentIndex(index)

    def blocks(self) -> Dict[MarketKey, MarketBlock]:
        return dict(self._blocks)

    def block_for(self, key: MarketKey) -> Optional[MarketBlock]:
        return self._blocks.get(key)

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.unlock_button.setEnabled(locked)
        self.lock_button.setEnabled(not locked and bool(self._blocks))
        self.lock_button.setText("APUESTA FIJADA" if locked else "FIJAR APUESTA (F9)")
        self.mode_label.setText("APUESTA FIJADA" if locked else "BUSCANDO ENTRADA")

    def _on_line_selected(self, evaluation: LineEvaluation) -> None:
        """Una seleccion en un bloque limpia la de los demas: solo hay un foco."""
        self._selected = evaluation
        for key, block in self._blocks.items():
            if evaluation is None or key != evaluation.key:
                block.clear_selection()
        self.lineSelected.emit(evaluation)

    # ---------------------------------------------------------- construccion
    def _ensure_block(self, key: MarketKey) -> MarketBlock:
        block = self._blocks.get(key)
        if block is None:
            block = MarketBlock(key)
            block.lineSelected.connect(self._on_line_selected)
            block.lineActivated.connect(lambda _: self.lockRequested.emit())
            self._blocks[key] = block
        return block

    def _rebuild_layout(self, order: List[MarketKey]) -> None:
        """Reordena los bloques manteniendo los widgets ya creados."""
        if order == self._order:
            return
        for i in reversed(range(self._container_layout.count())):
            item = self._container_layout.itemAt(i)
            if item.widget() is not None:
                self._container_layout.takeAt(i)
                item.widget().setParent(None)
            elif item.spacerItem() is not None:
                self._container_layout.takeAt(i)
        for key in order:
            block = self._blocks[key]
            self._container_layout.addWidget(block)
            # Un widget creado sin padre y anadido despues a un layout ya
            # visible no siempre se muestra solo: hay que pedirselo.
            block.setVisible(True)
        self._container_layout.addStretch(1)
        self._container_layout.activate()
        self._order = list(order)

    # -------------------------------------------------------------- refresco
    def update_board(self, blocks: List[MarketEvaluation], criteria: EntryCriteria,
                     focus: Optional[LineEvaluation] = None,
                     in_transition: bool = False,
                     now: Optional[float] = None) -> None:
        """Repinta el radar completo."""
        self._criteria = criteria

        vivos = [b for b in blocks if b.evaluations]
        orden = [b.key for b in vivos]
        for block_data in vivos:
            self._ensure_block(block_data.key)
        # Los mercados que dejaron de existir se retiran de la vista.
        for key in list(self._blocks):
            if key not in orden:
                widget = self._blocks.pop(key)
                widget.setParent(None)
                self._order = []
        self._rebuild_layout(orden)

        for block_data in vivos:
            self._blocks[block_data.key].update_block(block_data, criteria, now)

        if focus is not None:
            self._selected = focus
            block = self._blocks.get(focus.key)
            if block is not None:
                block.select_line_value(focus.line_value)
            for key, other in self._blocks.items():
                if key != focus.key:
                    other.clear_selection()

        revisando = [b for b in vivos if b.freshness is FreshnessState.REVIEWING]
        if in_transition:
            self.review_label.setText(
                "CAMBIO DE PESTANA EN CURSO: no se atribuye ninguna linea hasta confirmar "
                "que mercado se esta viendo.")
            self.review_label.setVisible(True)
        elif revisando:
            nombres = ", ".join(b.label for b in revisando)
            self.review_label.setText(
                f"LINEA EN REVISION en {nombres}: la casa ofrece algo distinto y se esta "
                "confirmando. Se sigue mostrando la ultima lectura confirmada.")
            self.review_label.setVisible(True)
        else:
            self.review_label.setVisible(False)

        if not vivos:
            self.status_label.setText(
                "Sin lineas confirmadas. Revisa el ROI del bloque de mercado.")
            self.lock_button.setEnabled(False)
            return

        total = sum(len(b.evaluations) for b in vivos)
        en_vivo = sum(1 for b in vivos if b.is_live)
        self.status_label.setText(
            f"{len(vivos)} mercado(s) y {total} linea(s) | {en_vivo} en vivo | "
            f"referencia {criteria.reference_pace:.2f} pts/min | "
            f"cuota objetivo {criteria.target_under_odds:.2f}. "
            "Navega tu por las pestanas de la casa: cada mercado conserva su ultima lectura.")
        self.lock_button.setEnabled(not self._locked)


def _selectable_markets() -> List[MarketKey]:
    """Mercados que el usuario puede forzar a mano."""
    return [MarketKey.game(), MarketKey.half_market(1), MarketKey.half_market(2)] + \
        [MarketKey.quarter(p) for p in (1, 2, 3, 4)]
