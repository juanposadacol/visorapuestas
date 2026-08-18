"""Dialogo de criterios de entrada, en modo sin pantalla."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.calculations.signals import SignalLevel  # noqa: E402
from visorunder.config.criteria import EntryCriteria  # noqa: E402
from visorunder.ui.criteria_dialog import CriteriaDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_el_dialogo_refleja_los_criterios_actuales(qapp):
    criteria = EntryCriteria(reference_pace=4.25, target_under_odds=1.95)
    dialog = CriteriaDialog(criteria)
    assert dialog.reference_spin.value() == pytest.approx(4.25)
    assert dialog.target_odds_spin.value() == pytest.approx(1.95)


def test_los_cambios_salen_validados(qapp):
    dialog = CriteriaDialog(EntryCriteria())
    dialog.reference_spin.setValue(3.80)
    dialog.target_odds_spin.setValue(1.72)
    # umbrales desordenados a proposito
    dialog.very_spin.setValue(0.20)
    dialog.demanding_spin.setValue(1.40)
    resultado = dialog.result_criteria()

    assert resultado.reference_pace == pytest.approx(3.80)
    assert resultado.target_under_odds == pytest.approx(1.72)
    assert resultado.threshold_very_demanding >= resultado.threshold_demanding


def test_la_paleta_no_se_invierte_dos_veces(qapp):
    """Con la paleta invertida, abrir y guardar no debe alterar los colores."""
    criteria = EntryCriteria()
    criteria.invert_palette = True
    originales = dict(criteria.palette)

    dialog = CriteriaDialog(criteria)
    resultado = dialog.result_criteria()

    assert resultado.palette == originales
    assert resultado.invert_palette is True


def test_restaurar_valores_iniciales(qapp):
    dialog = CriteriaDialog(EntryCriteria(reference_pace=5.0, target_under_odds=1.50))
    dialog._restore_defaults()
    resultado = dialog.result_criteria()
    assert resultado.reference_pace == 4.00
    assert resultado.target_under_odds == 1.80


def test_hay_un_color_por_cada_nivel_de_senal(qapp):
    dialog = CriteriaDialog(EntryCriteria())
    assert set(dialog._color_buttons) == {level.value for level in SignalLevel}


def test_el_tramo_final_es_configurable_desde_el_dialogo(qapp):
    dialog = CriteriaDialog(EntryCriteria())
    dialog.final_stretch_spin.setValue(120)
    dialog.final_stretch_check.setChecked(False)
    resultado = dialog.result_criteria()
    assert resultado.final_stretch_seconds == 120
    assert resultado.show_final_stretch is False
