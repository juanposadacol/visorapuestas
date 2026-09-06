"""Regresiones del panel de apuestas manuales.

El panel dejo de ser un libro contable: lo primero que ensena es el
SEGUIMIENTO deportivo de cada apuesta (puntos del mercado, margen, puntos
para cruzar, proyeccion y diferencia contra la linea). El conteo de dinero
sigue existiendo, pero al final de la fila y en una sola linea de resumen.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.app import AppController  # noqa: E402
from visorunder.calculations.manual_tracking import TrackingStatus  # noqa: E402
from visorunder.domain.game_state import GameState, PeriodPointsTracker  # noqa: E402
from visorunder.domain.manual_bet import ManualBetStatus  # noqa: E402
from visorunder.domain.market import MarketKey, Side  # noqa: E402
from visorunder.domain.rules import FIBA  # noqa: E402
from visorunder.domain.values import Observed  # noqa: E402
from visorunder.ui.manual_bets_panel import (  # noqa: E402
    COLUMNS,
    ManualBetsPanel,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _column(name: str) -> int:
    return [n for n, _ in COLUMNS].index(name)


@pytest.fixture()
def panel(qapp, tmp_path):
    controller = AppController(db_path=str(tmp_path / "manual.db"))
    controller.settings.log_to_file = False
    widget = ManualBetsPanel(controller)
    yield widget, controller
    controller.db.close()


def _add(panel, *, sportsbook="BetPlay", market="Q4", side="UNDER",
         line=40.5, odds=1.80, stake=0.0, event=""):
    panel.sportsbook_combo.setCurrentText(sportsbook)
    panel.event_edit.setText(event)
    panel.market_combo.setCurrentIndex(panel.market_combo.findData(market))
    panel.side_combo.setCurrentIndex(panel.side_combo.findData(side))
    panel.line_spin.setValue(line)
    panel.odds_spin.setValue(odds)
    panel.stake_spin.setValue(stake)
    panel._add_bet()


def _state(period: int, clock: int, score_a: int, score_b: int, baselines=None):
    tracker = PeriodPointsTracker(rules=FIBA)
    for periodo, (a, b) in (baselines or {}).items():
        tracker.set_baseline(periodo, a, b)
    state = GameState(rules=FIBA, tracker=tracker)
    state.period = Observed.confirmed(period)
    state.clock_seconds = Observed.confirmed(clock)
    state.score_a = Observed.confirmed(score_a)
    state.score_b = Observed.confirmed(score_b)
    return state


# ---------------------------------------------------------------------------
# El libro sigue funcionando igual
# ---------------------------------------------------------------------------
def test_panel_agrega_y_liquida_apuesta_manual(panel):
    widget, controller = panel
    _add(widget, sportsbook="Stake", market="Q2", side="UNDER", line=48.5,
         odds=1.85, stake=10_000, event="Equipo A vs Equipo B")

    assert widget.table.rowCount() == 1
    assert widget.table.item(0, _column("CASA")).text() == "Stake"
    assert widget.table.item(0, _column("MERCADO")).text() == "Q2"
    assert widget.table.item(0, _column("APUESTA")).text() == "UNDER 48.5"
    assert widget.table.item(0, _column("CUOTA")).text() == "1.85"
    assert widget.table.item(0, _column("ESTADO")).text() == "SIN DATOS"
    assert controller.manual_bet_summary().pending == 1

    widget.table.selectRow(0)
    widget._settle_selected(ManualBetStatus.WON)

    summary = controller.manual_bet_summary()
    assert summary.total == 1
    assert summary.pending == 0
    assert summary.won == 1
    assert summary.net_profit == pytest.approx(8_500)
    assert summary.roi == pytest.approx(85.0)
    # El resultado que marca el usuario manda sobre el seguimiento en vivo.
    assert widget.table.item(0, _column("ESTADO")).text() == "GANADA"
    assert "ROI +85.0%" in widget.money_label.text()


def test_casa_manual_admite_nombre_no_preconfigurado(panel):
    widget, controller = panel
    _add(widget, sportsbook="Mi Casa Nueva", market="GAME", line=190.5,
         odds=1.91, stake=25_000)

    bets = controller.list_manual_bets()
    assert len(bets) == 1
    assert bets[0].sportsbook == "Mi Casa Nueva"


def test_el_monto_es_opcional(panel):
    """Se puede seguir una apuesta sin decir cuanto se jugo."""
    widget, controller = panel
    _add(widget, sportsbook="Stake", market="Q4", line=40.5, odds=1.80, stake=0.0)

    bets = controller.list_manual_bets()
    assert len(bets) == 1
    assert bets[0].stake == 0.0
    assert bets[0].has_stake is False
    assert bets[0].profit is None
    assert widget.table.item(0, _column("MONTO")).text() == "--"
    assert widget.table.item(0, _column("UTILIDAD")).text() == "--"


# ---------------------------------------------------------------------------
# La tabla prioriza el seguimiento deportivo
# ---------------------------------------------------------------------------
def test_las_columnas_de_seguimiento_van_antes_que_el_dinero():
    nombres = [n for n, _ in COLUMNS]
    for columna in ("ACTUAL", "MARGEN", "P/CRUZAR", "PROYECCION", "DIF. LINEA"):
        assert columna in nombres, f"falta la columna {columna}"
    # El dinero existe, pero detras del seguimiento.
    assert nombres.index("DIF. LINEA") < nombres.index("MONTO")
    assert nombres.index("PROYECCION") < nombres.index("UTILIDAD")
    assert nombres.index("ESTADO") < nombres.index("MONTO")


def test_la_tabla_muestra_el_seguimiento_en_vivo(panel):
    """UNDER 40.5 en el Q4 con 32 puntos: margen 8.5 y 9 para cruzar."""
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5, odds=1.80)

    state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
    widget.update_tracking(controller.manual_bet_tracking_state(state))

    assert widget.table.item(0, _column("ACTUAL")).text() == "32"
    assert widget.table.item(0, _column("MARGEN")).text() == "+8.5"
    assert widget.table.item(0, _column("P/CRUZAR")).text() == "9"
    assert widget.table.item(0, _column("PROYECCION")).text() == "64.0 pts"
    assert widget.table.item(0, _column("DIF. LINEA")).text() == "+23.5"
    assert widget.table.item(0, _column("ESTADO")).text() == "EN RIESGO"


def test_la_tabla_se_actualiza_sola_al_cambiar_el_marcador(panel):
    """32 -> 34 -> 36 -> 39 sin volver a tocar la apuesta."""
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5)

    esperado = {32: ("+8.5", "9"), 34: ("+6.5", "7"),
                36: ("+4.5", "5"), 39: ("+1.5", "2")}
    for puntos, (margen, cruzan) in esperado.items():
        state = _state(4, 300, 72 + puntos, 60, baselines={4: (72, 60)})
        widget.update_tracking(controller.manual_bet_tracking_state(state))
        assert widget.table.item(0, _column("ACTUAL")).text() == str(puntos)
        assert widget.table.item(0, _column("MARGEN")).text() == margen
        assert widget.table.item(0, _column("P/CRUZAR")).text() == cruzan


def test_tres_apuestas_simultaneas_no_se_mezclan(panel):
    """BetPlay Q4 40.5, Stake Q4 42.5 y BetPlay partido 185.5."""
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5)
    _add(widget, sportsbook="Stake", market="Q4", line=42.5)
    _add(widget, sportsbook="BetPlay", market="GAME", line=185.5)

    state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
    widget.update_tracking(controller.manual_bet_tracking_state(state))
    assert widget.table.rowCount() == 3

    filas = {}
    for row in range(3):
        clave = (widget.table.item(row, _column("CASA")).text(),
                 widget.table.item(row, _column("APUESTA")).text())
        filas[clave] = row

    betplay_q4 = filas[("BetPlay", "UNDER 40.5")]
    stake_q4 = filas[("Stake", "UNDER 42.5")]
    partido = filas[("BetPlay", "UNDER 185.5")]

    # Mismo mercado y mismos puntos, pero cada linea con su propio margen.
    assert widget.table.item(betplay_q4, _column("ACTUAL")).text() == "32"
    assert widget.table.item(stake_q4, _column("ACTUAL")).text() == "32"
    assert widget.table.item(betplay_q4, _column("MARGEN")).text() == "+8.5"
    assert widget.table.item(stake_q4, _column("MARGEN")).text() == "+10.5"
    assert widget.table.item(betplay_q4, _column("P/CRUZAR")).text() == "9"
    assert widget.table.item(stake_q4, _column("P/CRUZAR")).text() == "11"

    # Y el mercado de partido mira el total, no el cuarto.
    assert widget.table.item(partido, _column("ACTUAL")).text() == "164"
    assert widget.table.item(partido, _column("MARGEN")).text() == "+21.5"
    assert widget.table.item(partido, _column("MERCADO")).text() == "Partido"


def test_sin_partido_las_metricas_quedan_no_disponibles(panel):
    """Sin datos no se inventa nada: se escribe '--'."""
    widget, controller = panel
    _add(widget, sportsbook="Stake", market="Q4", line=40.5)

    for columna in ("ACTUAL", "MARGEN", "P/CRUZAR", "PROYECCION", "DIF. LINEA"):
        assert widget.table.item(0, _column(columna)).text() == "--"
    assert widget.table.item(0, _column("ESTADO")).text() == "SIN DATOS"
    # Pero la apuesta si se ve entera.
    assert widget.table.item(0, _column("APUESTA")).text() == "UNDER 40.5"
    assert widget.table.item(0, _column("CUOTA")).text() == "1.80"


# ---------------------------------------------------------------------------
# Bloque de detalle "MI APUESTA"
# ---------------------------------------------------------------------------
def test_el_detalle_separa_margen_de_puntos_enteros(panel):
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5, odds=1.80)

    state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
    widget.update_tracking(controller.manual_bet_tracking_state(state))
    widget.table.selectRow(0)

    assert "BetPlay" in widget.detail_title.text()
    assert "UNDER 40.5" in widget.detail_title.text()

    valores = widget.detail_values
    assert valores["line"].text() == "40.5"
    assert valores["current"].text() == "32"
    assert valores["margin"].text() == "+8.5"
    assert valores["tolerable"].text() == "8"      # puntos enteros que caben
    assert valores["cross"].text() == "9"          # puntos que cruzan
    assert valores["projection"].text() == "64.0 pts"
    assert valores["difference"].text() == "+23.5"
    assert valores["pace"].text() == "6.40 pts/min"
    assert valores["required"].text() == "1.80 pts/min"
    assert valores["status"].text() == "EN RIESGO"

    # Y el titular no deja lugar a dudas entre las tres cifras.
    titular = widget.detail_headline.text()
    assert "8.5" in titular and "caben 8" in titular and "con 9" in titular


def test_el_detalle_sigue_a_la_fila_seleccionada(panel):
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5)
    _add(widget, sportsbook="Stake", market="Q4", line=42.5)

    state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
    widget.update_tracking(controller.manual_bet_tracking_state(state))

    vistos = {}
    for row in range(widget.table.rowCount()):
        widget.table.selectRow(row)
        vistos[widget.table.item(row, _column("CASA")).text()] = (
            widget.detail_values["line"].text(),
            widget.detail_values["margin"].text(),
        )

    assert vistos["BetPlay"] == ("40.5", "+8.5")
    assert vistos["Stake"] == ("42.5", "+10.5")


def test_el_detalle_del_over_no_habla_de_puntos_que_caben(panel):
    widget, controller = panel
    _add(widget, sportsbook="Stake", market="Q4", side="OVER", line=40.5)

    state = _state(4, 300, 90, 74, baselines={4: (72, 60)})
    widget.update_tracking(controller.manual_bet_tracking_state(state))
    widget.table.selectRow(0)

    assert widget.detail_values["cross"].text() == "9"
    assert widget.detail_values["tolerable"].text() == "--"
    assert "faltan 9 puntos" in widget.detail_headline.text()


def test_sin_seleccion_el_detalle_no_inventa(panel):
    widget, _controller = panel
    widget.table.clearSelection()
    widget._update_detail()

    assert "Selecciona" in widget.detail_title.text()
    for etiqueta in widget.detail_values.values():
        assert etiqueta.text() == "--"


# ---------------------------------------------------------------------------
# El estado se sugiere, pero no se impone
# ---------------------------------------------------------------------------
def test_no_se_marca_ganada_sola_mientras_el_mercado_sigue_vivo(panel):
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5)

    state = _state(4, 120, 82, 70, baselines={4: (72, 60)})   # 20 puntos, va bien
    widget.update_tracking(controller.manual_bet_tracking_state(state))

    seguimiento = widget._tracking[0]
    assert seguimiento.status is TrackingStatus.FAVORABLE
    # Favorable NO es ganada: en la base sigue pendiente.
    assert controller.list_manual_bets()[0].status is ManualBetStatus.PENDING
    assert controller.manual_bet_summary().pending == 1


def test_el_mercado_cerrado_si_permite_afirmar_el_resultado(panel):
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q3", line=40.5)

    # Q3 cerrado en 32 puntos mientras se juega el Q4.
    state = _state(4, 300, 90, 74, baselines={3: (55, 45), 4: (72, 60)})
    widget.update_tracking(controller.manual_bet_tracking_state(state))

    from visorunder.calculations.manual_tracking import suggested_status

    seguimiento = widget._tracking[0]
    assert seguimiento.settled is True
    assert seguimiento.status is TrackingStatus.WON
    assert suggested_status(seguimiento) is ManualBetStatus.WON
    # Pero seguimos sin tocar la base sin que el usuario lo pida.
    assert controller.list_manual_bets()[0].status is ManualBetStatus.PENDING


def test_borrar_una_apuesta_la_saca_del_seguimiento(panel):
    widget, controller = panel
    _add(widget, sportsbook="BetPlay", market="Q4", line=40.5)
    _add(widget, sportsbook="Stake", market="Q4", line=42.5)
    assert widget.table.rowCount() == 2

    widget.table.selectRow(0)
    bet_id = widget._selected_bet_id()
    controller.delete_manual_bet(bet_id)
    widget.refresh()

    assert widget.table.rowCount() == 1
    assert len(widget._tracking) == 1
