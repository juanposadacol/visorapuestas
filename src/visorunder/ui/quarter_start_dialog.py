"""Dialogo de marcador al comenzar el cuarto (requisito 9, prioridad 3).

Solo aparece cuando la aplicacion NO puede saber los puntos del cuarto:
ni hay desglose en la casa, ni historial propio del inicio del cuarto.
Nunca se rellena solo con el marcador actual.
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class QuarterStartDialog(QDialog):
    """Pide el marcador que habia justo al empezar el cuarto actual."""

    def __init__(self, period_label: str, current_a: Optional[int], current_b: Optional[int],
                 team_a: str = "Equipo A", team_b: str = "Equipo B",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Marcador al comenzar el {period_label}")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        message = QLabel(
            f"Para calcular correctamente los puntos del {period_label} necesito saber "
            f"el marcador al comenzar el cuarto.\n\n"
            f"Marcador actual: {current_a if current_a is not None else '--'} - "
            f"{current_b if current_b is not None else '--'}.\n"
            "Introduce el marcador que habia cuando empezo el cuarto (no el actual)."
        )
        message.setWordWrap(True)
        layout.addWidget(message)

        form = QFormLayout()
        self.spin_a = QSpinBox()
        self.spin_a.setRange(0, 250)
        self.spin_b = QSpinBox()
        self.spin_b.setRange(0, 250)
        if current_a is not None:
            self.spin_a.setMaximum(max(250, current_a))
            self.spin_a.setValue(0)
        if current_b is not None:
            self.spin_b.setMaximum(max(250, current_b))
            self.spin_b.setValue(0)
        form.addRow(f"{team_a} al empezar", self.spin_a)
        form.addRow(f"{team_b} al empezar", self.spin_b)
        layout.addLayout(form)

        self._current = (current_a, current_b)
        self.warning = QLabel("")
        self.warning.setObjectName("danger")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        a, b = self.values()
        cur_a, cur_b = self._current
        if cur_a is not None and a > cur_a:
            self.warning.setText("El marcador inicial no puede ser mayor que el actual.")
            return
        if cur_b is not None and b > cur_b:
            self.warning.setText("El marcador inicial no puede ser mayor que el actual.")
            return
        self.accept()

    def values(self) -> Tuple[int, int]:
        return (int(self.spin_a.value()), int(self.spin_b.value()))
