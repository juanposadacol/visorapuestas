"""Configuracion de los criterios de entrada.

Todo lo que aqui se ajusta son TUS parametros. La aplicacion no los interpreta
como probabilidades ni recomienda nada con ellos: solo cambian con que numeros
se compara el ritmo necesario y como se colorea la escala.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..calculations.signals import SignalLevel
from ..config.criteria import EntryCriteria


class _ColorButton(QPushButton):
    """Boton que abre el selector de color y recuerda el valor elegido."""

    def __init__(self, color: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedWidth(90)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self) -> None:
        self.setText(self._color)
        self.setStyleSheet(f"background-color: {self._color}; color: #06101c; font-weight: 700;")

    def _pick(self) -> None:
        from PySide6.QtGui import QColor

        chosen = QColorDialog.getColor(QColor(self._color), self, "Elige un color")
        if chosen.isValid():
            self._color = chosen.name()
            self._refresh()

    @property
    def color(self) -> str:
        return self._color


class CriteriaDialog(QDialog):
    """Editor de ritmo de referencia, cuota objetivo, umbrales y paleta."""

    def __init__(self, criteria: EntryCriteria, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Criterios de entrada")
        self.setMinimumWidth(560)
        self._criteria = criteria

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_references(criteria))
        layout.addWidget(self._build_thresholds(criteria))
        layout.addWidget(self._build_palette(criteria))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore_defaults)
        layout.addWidget(buttons)

    # ---------------------------------------------------------- construccion
    def _build_references(self, criteria: EntryCriteria) -> QGroupBox:
        box = QGroupBox("Mis referencias")
        form = QFormLayout(box)

        self.reference_spin = QDoubleSpinBox()
        self.reference_spin.setRange(0.10, 30.00)
        self.reference_spin.setSingleStep(0.05)
        self.reference_spin.setDecimals(2)
        self.reference_spin.setSuffix(" pts/min")
        self.reference_spin.setValue(criteria.reference_pace)

        self.target_odds_spin = QDoubleSpinBox()
        self.target_odds_spin.setRange(1.01, 20.00)
        self.target_odds_spin.setSingleStep(0.01)
        self.target_odds_spin.setDecimals(2)
        self.target_odds_spin.setValue(criteria.target_under_odds)

        form.addRow("Ritmo de referencia", self.reference_spin)
        form.addRow("Cuota UNDER objetivo", self.target_odds_spin)
        nota = QLabel(
            "El ritmo de referencia es tu punto de comparacion, no una constante del "
            "baloncesto.\nLa cuota objetivo solo decide que linea se enfoca en la tarjeta "
            "grande cuando no has elegido ninguna a mano: no filtra lineas ni recomienda apostar."
        )
        nota.setObjectName("status")
        nota.setWordWrap(True)
        form.addRow(nota)
        return box

    def _build_thresholds(self, criteria: EntryCriteria) -> QGroupBox:
        box = QGroupBox("Umbrales de senal   (margen = ritmo necesario - referencia)")
        form = QFormLayout(box)

        def spin(value: float) -> QDoubleSpinBox:
            widget = QDoubleSpinBox()
            widget.setRange(-30.0, 30.0)
            widget.setSingleStep(0.05)
            widget.setDecimals(2)
            widget.setSuffix(" pts/min")
            widget.setValue(value)
            return widget

        self.very_spin = spin(criteria.threshold_very_demanding)
        self.demanding_spin = spin(criteria.threshold_demanding)
        self.neutral_spin = spin(criteria.threshold_neutral)

        form.addRow("MUY EXIGENTE a partir de", self.very_spin)
        form.addRow("EXIGENTE a partir de", self.demanding_spin)
        form.addRow("NEUTRO a partir de", self.neutral_spin)
        form.addRow(QLabel("Por debajo del ultimo umbral: PELIGROSO"))

        self.final_stretch_spin = QSpinBox()
        self.final_stretch_spin.setRange(0, 600)
        self.final_stretch_spin.setSuffix(" s")
        self.final_stretch_spin.setValue(criteria.final_stretch_seconds)
        self.final_stretch_check = QCheckBox("Avisar del tramo final")
        self.final_stretch_check.setChecked(criteria.show_final_stretch)

        form.addRow(self.final_stretch_check, self.final_stretch_spin)
        aviso = QLabel(
            "TRAMO FINAL es solo un aviso: no modifica el ritmo necesario, ni el margen, "
            "ni la clasificacion. La senal siempre sale de la matematica, sin correcciones."
        )
        aviso.setObjectName("status")
        aviso.setWordWrap(True)
        form.addRow(aviso)
        return box

    def _build_palette(self, criteria: EntryCriteria) -> QGroupBox:
        box = QGroupBox("Colores")
        layout = QVBoxLayout(box)
        self._color_buttons = {}
        for level in SignalLevel:
            row = QHBoxLayout()
            etiqueta = QLabel(level.label)
            etiqueta.setMinimumWidth(140)
            # Se lee la paleta EN BRUTO, no `color_for`, que ya aplica la
            # inversion: si no, al guardar se invertiria dos veces.
            boton = _ColorButton(criteria.palette.get(level.value, "#8b97a8"))
            self._color_buttons[level.value] = boton
            row.addWidget(etiqueta)
            row.addWidget(boton)
            row.addWidget(QLabel(level.explanation), 1)
            layout.addLayout(row)

        self.invert_check = QCheckBox(
            "Invertir la paleta (si prefieres la lectura cromatica opuesta)")
        self.invert_check.setChecked(criteria.invert_palette)
        layout.addWidget(self.invert_check)
        nota = QLabel("La etiqueta de texto se muestra siempre, ademas del color.")
        nota.setObjectName("status")
        layout.addWidget(nota)
        return box

    # -------------------------------------------------------------- acciones
    def _restore_defaults(self) -> None:
        base = EntryCriteria()
        self.reference_spin.setValue(base.reference_pace)
        self.target_odds_spin.setValue(base.target_under_odds)
        self.very_spin.setValue(base.threshold_very_demanding)
        self.demanding_spin.setValue(base.threshold_demanding)
        self.neutral_spin.setValue(base.threshold_neutral)
        self.final_stretch_spin.setValue(base.final_stretch_seconds)
        self.final_stretch_check.setChecked(base.show_final_stretch)
        self.invert_check.setChecked(base.invert_palette)

    def result_criteria(self) -> EntryCriteria:
        """Criterios resultantes, ya validados."""
        criteria = EntryCriteria(
            reference_pace=float(self.reference_spin.value()),
            target_under_odds=float(self.target_odds_spin.value()),
            threshold_very_demanding=float(self.very_spin.value()),
            threshold_demanding=float(self.demanding_spin.value()),
            threshold_neutral=float(self.neutral_spin.value()),
            final_stretch_seconds=int(self.final_stretch_spin.value()),
            show_final_stretch=bool(self.final_stretch_check.isChecked()),
            invert_palette=bool(self.invert_check.isChecked()),
        )
        # `_ColorButton` ya devuelve el color tal cual lo eligio el usuario; la
        # inversion se aplica al pintar, no al guardar.
        for level_value, boton in self._color_buttons.items():
            criteria.palette[level_value] = boton.color
        return criteria.validate()
