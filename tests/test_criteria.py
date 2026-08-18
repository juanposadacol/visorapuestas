"""Criterios de entrada configurables: nada esta escrito a fuego."""

import json

import pytest

from visorunder.config.criteria import EntryCriteria
from visorunder.config.settings import AppSettings


def test_valores_iniciales_son_los_acordados():
    c = EntryCriteria()
    assert c.reference_pace == 4.00
    assert c.target_under_odds == 1.80


def test_la_referencia_es_configurable():
    for value in (3.8, 4.0, 4.2, 4.5):
        c = EntryCriteria(reference_pace=value).validate()
        assert c.reference_pace == value


def test_umbrales_se_ordenan_solos():
    c = EntryCriteria(threshold_very_demanding=0.2, threshold_demanding=1.5,
                      threshold_neutral=0.0).validate()
    assert c.threshold_very_demanding >= c.threshold_demanding >= c.threshold_neutral


def test_valores_absurdos_se_acotan():
    c = EntryCriteria(reference_pace=0.0, target_under_odds=0.5,
                      final_stretch_seconds=-10).validate()
    assert c.reference_pace > 0
    assert c.target_under_odds >= 1.01
    assert c.final_stretch_seconds == 0


def test_paleta_configurable_e_invertible():
    c = EntryCriteria()
    verde = c.color_for("MUY_EXIGENTE")
    rojo = c.color_for("PELIGROSO")
    assert verde != rojo
    c.invert_palette = True
    assert c.color_for("MUY_EXIGENTE") == rojo
    assert c.color_for("PELIGROSO") == verde


def test_paleta_personalizada():
    c = EntryCriteria()
    c.palette["MUY_EXIGENTE"] = "#123456"
    assert c.color_for("MUY_EXIGENTE") == "#123456"


def test_se_guardan_y_recargan_con_las_preferencias(tmp_path):
    path = tmp_path / "settings.json"
    settings = AppSettings()
    settings.entry.reference_pace = 4.25
    settings.entry.target_under_odds = 1.95
    settings.entry.threshold_very_demanding = 1.4
    settings.save(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["entry"]["reference_pace"] == 4.25

    recargado = AppSettings.load(path)
    assert isinstance(recargado.entry, EntryCriteria)
    assert recargado.entry.reference_pace == 4.25
    assert recargado.entry.target_under_odds == 1.95
    assert recargado.entry.threshold_very_demanding == 1.4


def test_preferencias_antiguas_sin_criterios_siguen_cargando(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"always_on_top": False}), encoding="utf-8")
    recargado = AppSettings.load(path)
    assert recargado.always_on_top is False
    assert recargado.entry.reference_pace == 4.00
