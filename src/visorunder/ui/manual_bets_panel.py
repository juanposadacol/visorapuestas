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
* la columna SEGUIMIENTO dice como va la apuesta AHORA (FAVORABLE, EN RIESGO,
  SUPERADA, SIN DATOS) mientras sigue pendiente, y solo ensena el resultado
  -GANADA, PERDIDA, NULA- cuando tu la liquidas con los botones;
* debajo hay un bloque de detalle de la apuesta seleccionada, con el mismo
  espiritu que la tarjeta "MI APUESTA" del panel principal;
* el conteo (total, pendientes, ganadas, perdidas, utilidad, ROI) sigue
  existiendo como informacion secundaria, en una sola linea.

Los numeros los calcula `calculations.manual_tracking`, que reutiliza el mismo
motor que el radar. Aqui solo se pintan.

ESTE PANEL ES UNA HERRAMIENTA SECUNDARIA
----------------------------------------
Lo que manda en la pantalla son las metricas del partido y el radar. En el uso
real hay una, dos o tres apuestas abiertas, asi que el panel esta dimensionado
para eso y no para una tabla enorme medio vacia:

* la tabla tiene altura FIJA para `VISIBLE_ROWS` filas; a partir de ahi
  aparece scroll vertical y el panel NO crece;
* el detalle cabe en dos franjas horizontales en vez de una rejilla alta;
* todo el bloque se puede contraer dejando solo su encabezado.

Las alturas se derivan de la metrica de la fuente, no de pixeles fijos, para
que sigan siendo correctas con otra escala de pantalla.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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
    # SEGUIMIENTO, no ESTADO: mientras la apuesta esta pendiente esta columna
    # dice como va en vivo (FAVORABLE, EN RIESGO, SUPERADA, SIN DATOS) y solo
    # ensena el resultado -GANADA, PERDIDA, NULA- cuando ya se ha liquidado.
    ("SEGUIMIENTO", 105),
    ("MONTO", 90),
    ("UTILIDAD", 90),
]
COL_ID = 0
COL_STATUS = 10

#: Filas visibles antes de que aparezca el scroll. En el uso real hay una,
#: dos o tres apuestas abiertas: mas alto que esto seria area vacia robandole
#: sitio a las metricas del partido.
VISIBLE_ROWS = 3

#: El detalle en DOS franjas horizontales en vez de una rejilla alta. Se
#: conservan los diez campos; solo cambia como se reparten.
DETAIL_ROWS = [
    [("line", "LINEA"), ("current", "ACTUAL"), ("margin", "MARGEN"),
     ("tolerable", "CABEN"), ("cross", "P/CRUZAR")],
    [("projection", "PROY."), ("difference", "DIF. LINEA"), ("pace", "RITMO"),
     ("required", "RITMO CRUZAR"), ("status", "SEGUIMIENTO")],
]

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

    #: Se emite al contraer o desplegar. La ventana lo usa para devolverle al
    #: panel principal el alto que deja libre, y para restaurarlo despues.
    expandedChanged = Signal(bool)

    def __init__(self, controller: AppController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._default_sportsbook = ""
        self._tracking: List[ManualBetTracking] = []
        #: Alto de un control compacto, derivado de la fuente para que siga
        #: siendo correcto con otra escala de pantalla.
        self._field_height = self.fontMetrics().height() + 10
        self._build_ui()
        self.refresh()

    # ---------------------------------------------------------- construccion
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        box = QGroupBox("APUESTAS MANUALES - seguimiento en vivo")
        box.setObjectName("manualPanel")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(8, 2, 8, 6)
        box_layout.setSpacing(4)
        box_layout.addLayout(self._build_header())

        # Todo lo que se oculta al contraer vive dentro de este cuerpo.
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        body.addLayout(self._build_form())
        # Sin factor de estiramiento: la tabla tiene alto fijo y el panel no
        # crece por tener mas apuestas.
        body.addWidget(self._build_table())
        body.addWidget(self._build_detail())
        body.addLayout(self._build_actions())
        body.addLayout(self._build_summary())
        box_layout.addWidget(self.body)
        self._box = box

        # El contenido va dentro de un area con scroll para que el panel se
        # pueda ESTRECHAR cuando la ventana es baja. Sin esto su altura minima
        # seria la de todo su contenido y el divisor no podria darle al panel
        # principal la altura que le corresponde.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(box)
        self._scroll = scroll
        root.addWidget(scroll)

        # Puede encogerse hasta dejar ver poco mas que el encabezado; lo que
        # no quepa se alcanza con el scroll interno.
        self.setMinimumHeight(self._field_height * 2)
        # Y no pide mas alto del que ocupa su contenido: lo que sobra es para
        # las metricas del partido.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def sizeHint(self) -> QSize:
        """Alto natural = el de su contenido.

        El area con scroll, por si sola, sugiere un alto arbitrario. Aqui se
        devuelve el del contenido real para que el divisor reparta bien y para
        que al contraer el panel encoja de verdad.
        """
        base = super().sizeHint()
        return QSize(base.width(), self._box.sizeHint().height())

    def _build_header(self) -> QHBoxLayout:
        """Franja del titulo con el boton de contraer/desplegar."""
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addStretch(1)

        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("panelToggle")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(True)
        self.toggle_button.setArrowType(Qt.UpArrow)
        self.toggle_button.setToolTip("Contraer las apuestas manuales")
        self.toggle_button.setAutoRaise(True)
        self.toggle_button.toggled.connect(self.set_expanded)
        header.addWidget(self.toggle_button)
        return header

    # ------------------------------------------------------ contraer/desplegar
    @property
    def is_expanded(self) -> bool:
        return self.body.isVisible()

    def set_expanded(self, expanded: bool) -> None:
        """Muestra u oculta el cuerpo; contraido solo queda el encabezado."""
        expanded = bool(expanded)
        if self.toggle_button.isChecked() != expanded:
            # Llega de codigo, no del boton: se sincroniza sin reentrar.
            self.toggle_button.blockSignals(True)
            self.toggle_button.setChecked(expanded)
            self.toggle_button.blockSignals(False)
        if self.body.isVisible() == expanded:
            return
        self.body.setVisible(expanded)
        self.toggle_button.setArrowType(Qt.UpArrow if expanded else Qt.DownArrow)
        self.toggle_button.setToolTip(
            "Contraer las apuestas manuales" if expanded
            else "Desplegar las apuestas manuales")
        self.expandedChanged.emit(expanded)

    def toggle_expanded(self) -> None:
        self.set_expanded(not self.is_expanded)

    def _build_form(self) -> QGridLayout:
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(1)

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

        campos = [
            ("Casa", self.sportsbook_combo),
            ("Evento", self.event_edit),
            ("Mercado", self.market_combo),
            ("Lado", self.side_combo),
            ("Linea", self.line_spin),
            ("Cuota", self.odds_spin),
            ("Monto", self.stake_spin),
        ]
        for columna, (texto, control) in enumerate(campos):
            titulo = QLabel(texto)
            titulo.setObjectName("metricLabel")
            form.addWidget(titulo, 0, columna)
            control.setFixedHeight(self._field_height)
            form.addWidget(control, 1, columna)

        self.add_button.setFixedHeight(self._field_height)
        form.addWidget(self.add_button, 1, len(campos))
        form.setColumnStretch(1, 1)
        return form

    def _build_table(self) -> QTableWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("manualTable")
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setColumnHidden(COL_ID, True)

        # Filas compactas: lo justo para leerlas sin desperdiciar alto.
        filas = self.table.verticalHeader()
        filas.setVisible(False)
        filas.setDefaultSectionSize(self._field_height)
        filas.setMinimumSectionSize(self._field_height)

        # Ninguna columna se come a las demas: anchura propia y scroll
        # horizontal cuando no caben todas.
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        for index, (_, width) in enumerate(COLUMNS):
            if width:
                self.table.setColumnWidth(index, width)

        self._apply_table_height()
        self.table.itemSelectionChanged.connect(self._update_detail)
        return self.table

    def _apply_table_height(self) -> None:
        """Fija la altura de la tabla a exactamente `VISIBLE_ROWS` filas.

        Con mas apuestas aparece scroll vertical y el panel NO crece: es lo
        que impide que una tabla medio vacia le robe media pantalla a las
        metricas del partido.

        Se reserva ademas el alto de la barra horizontal, que siempre puede
        aparecer porque la tabla tiene mas columnas de las que suelen caber;
        sin reservarlo taparia la tercera fila.
        """
        fila = self.table.verticalHeader().defaultSectionSize()
        cabecera = self.table.horizontalHeader().sizeHint().height()
        marco = 2 * self.table.frameWidth()
        barra = self.table.horizontalScrollBar().sizeHint().height()
        self.table.setFixedHeight(cabecera + VISIBLE_ROWS * fila + marco + barra)

    @property
    def visible_rows(self) -> int:
        """Cuantas filas caben sin hacer scroll."""
        fila = self.table.verticalHeader().defaultSectionSize()
        if fila <= 0:
            return 0
        alto = (self.table.height()
                - self.table.horizontalHeader().sizeHint().height()
                - 2 * self.table.frameWidth()
                - self.table.horizontalScrollBar().sizeHint().height())
        return max(0, alto // fila)

    def _build_detail(self) -> QFrame:
        """Detalle de la apuesta seleccionada, en franjas horizontales.

        Estan los mismos diez campos que antes; lo que cambia es el reparto.
        La rejilla anterior ponia el rotulo encima del valor, asi que diez
        campos ocupaban cuatro filas de widgets mas el titular. Aqui cada
        campo es "ROTULO valor" en linea, de modo que caben en dos franjas.
        """
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # Titulo y titular comparten franja para no gastar dos.
        encabezado = QHBoxLayout()
        encabezado.setSpacing(10)
        self.detail_title = QLabel("Selecciona una apuesta para ver su seguimiento")
        self.detail_title.setObjectName("metricValue")
        self.detail_headline = QLabel("")
        self.detail_headline.setObjectName("status")
        self.detail_headline.setWordWrap(False)
        encabezado.addWidget(self.detail_title)
        encabezado.addWidget(self.detail_headline, 1)
        layout.addLayout(encabezado)

        self.detail_values = {}
        for campos in DETAIL_ROWS:
            franja = QHBoxLayout()
            franja.setSpacing(14)
            for clave, etiqueta in campos:
                celda = QHBoxLayout()
                celda.setSpacing(4)
                titulo = QLabel(etiqueta)
                titulo.setObjectName("metricLabel")
                valor = QLabel(fmt.UNKNOWN)
                valor.setObjectName("metricValue")
                celda.addWidget(titulo)
                celda.addWidget(valor)
                franja.addLayout(celda)
                self.detail_values[clave] = valor
            franja.addStretch(1)
            layout.addLayout(franja)

        self.detail_card = card
        return card

    def _build_actions(self) -> QHBoxLayout:
        """Una sola franja de botones, sin crear otro bloque vertical."""
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)

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

        rotulo = QLabel("Resultado:")
        rotulo.setObjectName("metricLabel")
        rotulo.setToolTip("Se aplica a la apuesta seleccionada en la tabla.")
        actions.addWidget(rotulo)
        for boton in (self.won_button, self.lost_button, self.void_button,
                      self.pending_button, self.delete_button):
            boton.setFixedHeight(self._field_height)
        actions.addWidget(self.won_button)
        actions.addWidget(self.lost_button)
        actions.addWidget(self.void_button)
        actions.addWidget(self.pending_button)
        actions.addStretch(1)
        actions.addWidget(self.delete_button)
        return actions

    def _build_summary(self) -> QHBoxLayout:
        """Conteo en una sola linea al pie: informacion secundaria."""
        summary = QHBoxLayout()
        summary.setContentsMargins(0, 0, 0, 0)
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
        """Que se escribe en la columna SEGUIMIENTO.

        Mientras la apuesta sigue PENDIENTE lo util no es leer "PENDIENTE",
        que ya se sabe: es ver como va en vivo (FAVORABLE, EN RIESGO,
        SUPERADA, SIN DATOS). En cuanto tu la liquidas, ese resultado manda y
        la columna pasa a decir GANADA, PERDIDA o NULA.

        Por eso la columna se llama SEGUIMIENTO y no ESTADO: los botones de
        abajo son los que fijan el RESULTADO.
        """
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
