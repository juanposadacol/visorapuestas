"""Regresiones del registro manual de apuestas y su panel Qt."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.app import AppController  # noqa: E402
from visorunder.domain.manual_bet import ManualBetStatus  # noqa: E402
from visorunder.ui.manual_bets_panel import ManualBetsPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_panel_agrega_y_liquida_apuesta_manual(qapp, tmp_path):
    controller = AppController(db_path=str(tmp_path / "manual.db"))
    controller.settings.log_to_file = False
    panel = ManualBetsPanel(controller)

    panel.sportsbook_combo.setCurrentText("Stake")
    panel.event_edit.setText("Equipo A vs Equipo B")
    panel.market_combo.setCurrentIndex(panel.market_combo.findData("Q2"))
    panel.side_combo.setCurrentIndex(panel.side_combo.findData("UNDER"))
    panel.line_spin.setValue(48.5)
    panel.odds_spin.setValue(1.85)
    panel.stake_spin.setValue(10_000)

    panel._add_bet()

    assert panel.table.rowCount() == 1
    assert panel.table.item(0, 1).text() == "Stake"
    assert panel.table.item(0, 3).text() == "UNDER 48.5"
    assert panel.table.item(0, 6).text() == "PENDIENTE"
    assert controller.manual_bet_summary().pending == 1

    panel.table.selectRow(0)
    panel._settle_selected(ManualBetStatus.WON)

    summary = controller.manual_bet_summary()
    assert summary.total == 1
    assert summary.pending == 0
    assert summary.won == 1
    assert summary.net_profit == pytest.approx(8_500)
    assert summary.roi == pytest.approx(85.0)
    assert panel.table.item(0, 6).text() == "GANADA"
    assert "ROI +85.0%" in panel.money_label.text()

    controller.db.close()


def test_casa_manual_admite_nombre_no_preconfigurado(qapp, tmp_path):
    controller = AppController(db_path=str(tmp_path / "manual-otra.db"))
    controller.settings.log_to_file = False
    panel = ManualBetsPanel(controller)

    panel.sportsbook_combo.setCurrentText("Mi Casa Nueva")
    panel.line_spin.setValue(190.5)
    panel.odds_spin.setValue(1.91)
    panel.stake_spin.setValue(25_000)
    panel._add_bet()

    bets = controller.list_manual_bets()
    assert len(bets) == 1
    assert bets[0].sportsbook == "Mi Casa Nueva"

    controller.db.close()
