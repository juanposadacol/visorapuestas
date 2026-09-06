"""El panel de apuestas manuales es una herramienta SECUNDARIA.

En el uso real hay una, dos o tres apuestas abiertas. El panel esta
dimensionado para eso: una tabla alta y medio vacia le robaria media pantalla
a las metricas del partido, que son lo que de verdad manda.

Estas pruebas fijan el reparto de espacio. Son de presentacion: ningun calculo
ni ninguna persistencia cambia, y eso tambien se comprueba aqui.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.app import AppController  # noqa: E402
from visorunder.capture.screen_capture import NullCapture  # noqa: E402
from visorunder.domain.manual_bet import ManualBetStatus  # noqa: E402
from visorunder.domain.market import MarketKey, Side  # noqa: E402
from visorunder.ui.manual_bets_panel import (  # noqa: E402
    COLUMNS,
    DETAIL_ROWS,
    VISIBLE_ROWS,
    ManualBetsPanel,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def panel(qapp, tmp_path):
    controller = AppController(db_path=str(tmp_path / "layout.db"), capture=NullCapture())
    controller.settings.log_to_file = False
    widget = ManualBetsPanel(controller)
    widget.resize(1100, 400)
    widget.show()
    qapp.processEvents()
    yield widget, controller, qapp
    controller.db.close()


def _column(name: str) -> int:
    return [n for n, _ in COLUMNS].index(name)


def _add(controller, n: int) -> None:
    for index in range(n):
        controller.add_manual_bet(
            sportsbook=f"Casa {index + 1}", event="", key=MarketKey.quarter(4),
            side=Side.UNDER, line=40.5 + index, odds=1.80, stake=0.0)


# ---------------------------------------------------------------------------
# 1. La tabla ensena como mucho tres filas y luego hace scroll
# ---------------------------------------------------------------------------
def test_la_tabla_muestra_tres_filas_antes_de_hacer_scroll(panel):
    widget, controller, qapp = panel
    _add(controller, 3)
    widget.refresh()
    qapp.processEvents()

    assert VISIBLE_ROWS == 3
    assert widget.visible_rows == 3, "no caben exactamente tres filas"
    assert widget.table.verticalScrollBar().maximum() == 0, (
        "con tres apuestas no deberia hacer falta scroll")


def test_a_partir_de_la_cuarta_aparece_scroll_vertical(panel):
    widget, controller, qapp = panel
    _add(controller, 6)
    widget.refresh()
    qapp.processEvents()

    assert widget.table.rowCount() == 6
    assert widget.visible_rows == 3, "la tabla crecio para caber seis filas"
    assert widget.table.verticalScrollBar().maximum() > 0, (
        "con seis apuestas tiene que poder hacerse scroll")


def test_la_altura_de_la_tabla_es_fija(panel):
    """Ni crece con mas apuestas ni encoge con menos."""
    widget, controller, qapp = panel
    alto_vacia = widget.table.height()

    alturas = set()
    for _ in range(6):
        _add(controller, 1)
        widget.refresh()
        qapp.processEvents()
        alturas.add(widget.table.height())

    assert alturas == {alto_vacia}, f"la tabla cambio de alto: {alturas}"
    assert widget.table.minimumHeight() == widget.table.maximumHeight(), (
        "la tabla no tiene la altura fijada")


def test_la_altura_se_deriva_de_la_fuente_y_no_de_pixeles_fijos(panel):
    """Con otra escala de pantalla las alturas siguen siendo correctas."""
    widget, _controller, _qapp = panel

    fila = widget.table.verticalHeader().defaultSectionSize()
    assert fila == widget._field_height
    assert fila >= widget.fontMetrics().height(), "las filas no caben en su fuente"

    esperado = (widget.table.horizontalHeader().sizeHint().height()
                + VISIBLE_ROWS * fila
                + 2 * widget.table.frameWidth()
                + widget.table.horizontalScrollBar().sizeHint().height())
    assert widget.table.height() == esperado


# ---------------------------------------------------------------------------
# 2. El panel entero no se expande indefinidamente
# ---------------------------------------------------------------------------
def test_el_panel_no_crece_al_anadir_apuestas(panel):
    widget, controller, qapp = panel
    alturas = []
    for _ in range(6):
        _add(controller, 1)
        widget.refresh()
        qapp.processEvents()
        alturas.append(widget.sizeHint().height())

    assert len(set(alturas)) == 1, f"el panel crecio con las apuestas: {alturas}"


def test_el_panel_pide_su_alto_natural_y_no_mas(panel):
    """Politica Maximum: lo que sobra es para las metricas del partido."""
    from PySide6.QtWidgets import QSizePolicy

    widget, _controller, _qapp = panel
    assert widget.sizePolicy().verticalPolicy() == QSizePolicy.Maximum


def test_el_panel_cabe_en_una_franja_razonable(panel):
    """Sirve para 1-3 apuestas sin ocupar media pantalla."""
    widget, controller, qapp = panel
    _add(controller, 3)
    widget.refresh()
    qapp.processEvents()

    alto = widget.sizeHint().height()
    assert alto < 400, f"el panel sigue siendo demasiado alto: {alto}px"


# ---------------------------------------------------------------------------
# 3. El detalle sigue completo, solo mejor repartido
# ---------------------------------------------------------------------------
def test_el_detalle_conserva_los_diez_campos(panel):
    widget, _controller, _qapp = panel

    esperados = {"line", "current", "margin", "tolerable", "cross",
                 "projection", "difference", "pace", "required", "status"}
    assert set(widget.detail_values) == esperados
    assert len(widget.detail_values) == 10, "se perdio informacion del detalle"


def test_el_detalle_ocupa_dos_franjas(panel):
    widget, _controller, _qapp = panel

    assert len(DETAIL_ROWS) == 2, "el detalle deberia caber en dos franjas"
    assert all(len(fila) == 5 for fila in DETAIL_ROWS)
    repartidos = [clave for fila in DETAIL_ROWS for clave, _ in fila]
    assert sorted(repartidos) == sorted(widget.detail_values)


def test_el_detalle_sigue_mostrando_los_valores(panel):
    """Compactar no puede dejar de pintar los numeros."""
    from visorunder.domain.game_state import GameState, PeriodPointsTracker
    from visorunder.domain.rules import FIBA
    from visorunder.domain.values import Observed

    widget, controller, qapp = panel
    controller.add_manual_bet(sportsbook="BetPlay", event="", key=MarketKey.quarter(4),
                              side=Side.UNDER, line=40.5, odds=1.80, stake=0.0)
    widget.refresh()

    tracker = PeriodPointsTracker(rules=FIBA)
    tracker.set_baseline(4, 72, 60)
    state = GameState(rules=FIBA, tracker=tracker)
    state.period = Observed.confirmed(4)
    state.clock_seconds = Observed.confirmed(300)
    state.score_a = Observed.confirmed(90)
    state.score_b = Observed.confirmed(74)

    widget.update_tracking(controller.manual_bet_tracking_state(state))
    widget.table.selectRow(0)
    qapp.processEvents()

    assert widget.detail_values["line"].text() == "40.5"
    assert widget.detail_values["current"].text() == "32"
    assert widget.detail_values["margin"].text() == "+8.5"
    assert widget.detail_values["tolerable"].text() == "8"
    assert widget.detail_values["cross"].text() == "9"
    assert widget.detail_values["projection"].text() == "64.0 pts"
    assert widget.detail_values["difference"].text() == "+23.5"
    assert widget.detail_values["status"].text() == "EN RIESGO"
    assert "BetPlay" in widget.detail_title.text()


# ---------------------------------------------------------------------------
# 4 y 5. Contraer y desplegar
# ---------------------------------------------------------------------------
def test_arranca_desplegado(panel):
    widget, _controller, _qapp = panel
    assert widget.is_expanded is True
    assert widget.body.isVisible() is True


def test_contraer_oculta_el_contenido(panel):
    widget, _controller, qapp = panel
    alto_desplegado = widget.sizeHint().height()

    widget.set_expanded(False)
    qapp.processEvents()

    assert widget.is_expanded is False
    assert widget.body.isVisible() is False
    assert widget.table.isVisible() is False
    assert widget.detail_card.isVisible() is False
    assert widget.sizeHint().height() < alto_desplegado / 2, (
        "contraido deberia quedar solo el encabezado")


def test_desplegar_lo_restaura_todo(panel):
    widget, controller, qapp = panel
    _add(controller, 2)
    widget.refresh()
    qapp.processEvents()
    alto_desplegado = widget.sizeHint().height()

    widget.set_expanded(False)
    qapp.processEvents()
    widget.set_expanded(True)
    qapp.processEvents()

    assert widget.is_expanded is True
    assert widget.body.isVisible() is True
    assert widget.table.isVisible() is True
    assert widget.sizeHint().height() == alto_desplegado
    assert widget.table.rowCount() == 2, "se perdieron las apuestas al desplegar"


def test_el_boton_alterna_el_estado(panel):
    widget, _controller, qapp = panel

    widget.toggle_button.click()
    qapp.processEvents()
    assert widget.is_expanded is False
    assert widget.toggle_button.isChecked() is False

    widget.toggle_button.click()
    qapp.processEvents()
    assert widget.is_expanded is True
    assert widget.toggle_button.isChecked() is True


def test_contraer_avisa_una_sola_vez(panel):
    widget, _controller, _qapp = panel
    avisos = []
    widget.expandedChanged.connect(avisos.append)

    widget.set_expanded(False)
    widget.set_expanded(False)      # ya estaba contraido: no vuelve a avisar
    widget.set_expanded(True)

    assert avisos == [False, True]


def test_contraer_no_pierde_los_datos(panel):
    """Es un cambio de presentacion: la base no se toca."""
    widget, controller, qapp = panel
    _add(controller, 2)
    widget.refresh()

    widget.set_expanded(False)
    qapp.processEvents()

    assert len(controller.list_manual_bets()) == 2
    assert widget.table.rowCount() == 2, "las filas siguen ahi, solo no se ven"
    assert len(widget._tracking) == 2


# ---------------------------------------------------------------------------
# 7-9. Nada funcional se rompe
# ---------------------------------------------------------------------------
def test_agregar_una_apuesta_sigue_funcionando(panel):
    widget, controller, qapp = panel

    widget.sportsbook_combo.setCurrentText("Stake")
    widget.market_combo.setCurrentIndex(widget.market_combo.findData("Q3"))
    widget.side_combo.setCurrentIndex(widget.side_combo.findData("OVER"))
    widget.line_spin.setValue(48.5)
    widget.odds_spin.setValue(1.95)
    widget.stake_spin.setValue(5_000)
    widget._add_bet()
    qapp.processEvents()

    apuestas = controller.list_manual_bets()
    assert len(apuestas) == 1
    assert apuestas[0].sportsbook == "Stake"
    assert apuestas[0].side is Side.OVER
    assert apuestas[0].line == 48.5
    assert apuestas[0].stake == 5_000
    assert widget.table.rowCount() == 1
    assert widget.table.item(0, _column("APUESTA")).text() == "OVER 48.5"


def test_seleccionar_una_apuesta_sigue_funcionando(panel):
    widget, controller, qapp = panel
    _add(controller, 3)
    widget.refresh()
    qapp.processEvents()

    for fila in range(3):
        widget.table.selectRow(fila)
        qapp.processEvents()
        esperado = widget.table.item(fila, _column("CASA")).text()
        assert esperado in widget.detail_title.text()
        assert widget._selected_bet_id() is not None


@pytest.mark.parametrize("estado, etiqueta", [
    (ManualBetStatus.WON, "GANADA"),
    (ManualBetStatus.LOST, "PERDIDA"),
    (ManualBetStatus.VOID, "NULA"),
    # PENDIENTE devuelve el mando al seguimiento en vivo, que sin partido en
    # curso dice SIN DATOS. Es el comportamiento que el panel ya tenia.
    (ManualBetStatus.PENDING, "SIN DATOS"),
])
def test_liquidar_sigue_funcionando(panel, estado, etiqueta):
    widget, controller, qapp = panel
    controller.add_manual_bet(sportsbook="BetPlay", event="", key=MarketKey.game(),
                              side=Side.UNDER, line=185.5, odds=1.90, stake=10_000)
    widget.refresh()
    widget.table.selectRow(0)

    widget._settle_selected(estado)
    qapp.processEvents()

    assert controller.list_manual_bets()[0].status is estado
    assert widget.table.item(0, _column("ESTADO")).text() == etiqueta


def test_los_botones_caben_en_una_sola_franja(panel):
    widget, _controller, _qapp = panel
    botones = (widget.won_button, widget.lost_button, widget.void_button,
               widget.pending_button, widget.delete_button)

    for boton in botones:
        assert boton.height() == widget._field_height, (
            f"{boton.text()} no tiene alto compacto")
    # Todos a la misma altura: una sola franja, no un bloque vertical.
    assert len({boton.y() for boton in botones}) == 1


def test_el_formulario_no_crece_verticalmente(panel):
    widget, _controller, _qapp = panel
    controles = (widget.sportsbook_combo, widget.event_edit, widget.market_combo,
                 widget.side_combo, widget.line_spin, widget.odds_spin,
                 widget.stake_spin, widget.add_button)

    for control in controles:
        assert control.height() == widget._field_height
    assert widget.add_button.height() == widget.sportsbook_combo.height(), (
        "el boton no puede ser mas alto que los campos")


# ---------------------------------------------------------------------------
# 6. La ventana principal conserva la prioridad de altura
# ---------------------------------------------------------------------------
def test_la_ventana_da_la_mayor_parte_del_alto_al_panel_principal(qapp, tmp_path):
    from visorunder.ui.main_window import (
        MAIN_AREA_SHARE, MANUAL_AREA_SHARE, MainWindow,
    )

    controller = AppController(db_path=str(tmp_path / "win.db"), capture=NullCapture())
    controller.settings.log_to_file = False
    window = MainWindow(controller)
    window.timer.stop()
    try:
        window.resize(1200, 1000)
        qapp.processEvents()

        principal, manuales = window.panel_splitter.sizes()
        total = principal + manuales
        assert total > 0
        proporcion = principal / total
        assert 0.72 <= proporcion <= 0.85, (
            f"el panel principal se queda con el {proporcion:.0%} del alto")

        # Y la proporcion declarada es la que se pretende.
        assert MAIN_AREA_SHARE / (MAIN_AREA_SHARE + MANUAL_AREA_SHARE) == 0.8
        assert window.panel_splitter.isCollapsible(0) is False, (
            "el panel principal nunca puede quedar oculto")
    finally:
        window.hotkeys.stop()
        controller.shutdown()


def test_contraer_devuelve_el_alto_al_panel_principal(qapp, tmp_path):
    from visorunder.ui.main_window import MainWindow

    controller = AppController(db_path=str(tmp_path / "win2.db"), capture=NullCapture())
    controller.settings.log_to_file = False
    window = MainWindow(controller)
    window.timer.stop()
    try:
        window.resize(1200, 1000)
        qapp.processEvents()
        antes = window.panel_splitter.sizes()

        window.manual_bets_panel.set_expanded(False)
        qapp.processEvents()
        contraido = window.panel_splitter.sizes()
        assert contraido[0] > antes[0], (
            "al contraer, el alto liberado debe ir al panel principal")

        window.manual_bets_panel.set_expanded(True)
        qapp.processEvents()
        assert window.panel_splitter.sizes() == antes, (
            "al desplegar deberia recuperarse el reparto anterior")
    finally:
        window.hotkeys.stop()
        controller.shutdown()


def test_la_ventana_pequena_no_expulsa_los_controles(qapp, tmp_path):
    """Con poca altura mandan las metricas; el panel manual usa su scroll."""
    from visorunder.ui.main_window import MainWindow

    controller = AppController(db_path=str(tmp_path / "win3.db"), capture=NullCapture())
    controller.settings.log_to_file = False
    window = MainWindow(controller)
    window.timer.stop()
    try:
        window.resize(1000, 520)
        qapp.processEvents()

        principal, _manuales = window.panel_splitter.sizes()
        assert principal > 0, "el panel principal no puede quedarse sin alto"
        assert window.start_button.isVisible()
        assert window.profile_combo.isVisible()
        assert window.entry_board.isVisible(), "el panel de mercado desaparecio"
    finally:
        window.hotkeys.stop()
        controller.shutdown()
