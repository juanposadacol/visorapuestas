"""Panel de conexion (requisitos 13 y 25).

Responde de un vistazo a la pregunta "¿esto esta funcionando?", para que no
haya que abrir el popup de Chrome durante el uso normal. Y dice de DONDE sale
cada dato, que es justo lo que permite entender por que algo falta.
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QWidget

from ..bridge.source import LinkState, SourceKind
from .styles import COLOR_DANGER, COLOR_MUTED, COLOR_OK, COLOR_WARN

#: Etiquetas de los datos que puede aportar cada fuente.
CAMPOS = [
    ("market", "Mercado"),
    ("lines", "Lineas y cuotas"),
    ("score_a", "Marcador"),
    ("period", "Cuarto"),
    ("clock_seconds", "Reloj"),
]

COLORES_ENLACE = {
    LinkState.LIVE: COLOR_OK,
    LinkState.STALE: COLOR_WARN,
    LinkState.DISCONNECTED: COLOR_MUTED,
}


def _title(texto: str) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("sectionTitle")
    return etiqueta


class ConnectionPanel(QWidget):
    """Estado del enlace con la extension y procedencia de cada dato."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        tarjeta = QFrame()
        tarjeta.setObjectName("card")

        exterior = QGridLayout(self)
        exterior.setContentsMargins(0, 0, 0, 0)
        exterior.addWidget(tarjeta, 0, 0)

        rejilla = QGridLayout(tarjeta)
        rejilla.setContentsMargins(12, 10, 12, 10)
        rejilla.setSpacing(4)

        self.state_label = QLabel(LinkState.DISCONNECTED.label)
        self.state_label.setObjectName("metricValue")
        self.state_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.age_label = QLabel("--")
        self.age_label.setObjectName("metricValue")
        self.age_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        rejilla.addWidget(_title("EXTENSION"), 0, 0)
        rejilla.addWidget(self.state_label, 0, 1)
        rejilla.addWidget(_title("ULTIMO DATO"), 1, 0)
        rejilla.addWidget(self.age_label, 1, 1)

        self.field_labels: Dict[str, QLabel] = {}
        for fila, (clave, titulo) in enumerate(CAMPOS, start=2):
            valor = QLabel("--")
            valor.setObjectName("metricValue")
            valor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.field_labels[clave] = valor
            rejilla.addWidget(_title(titulo.upper()), fila, 0)
            rejilla.addWidget(valor, fila, 1)

        self.conflict_label = QLabel("")
        self.conflict_label.setObjectName("danger")
        self.conflict_label.setWordWrap(True)
        rejilla.addWidget(self.conflict_label, len(CAMPOS) + 2, 0, 1, 2)

        rejilla.setColumnStretch(0, 1)
        rejilla.setColumnMinimumWidth(1, 130)

    def update_view(self, link_state: LinkState, age_seconds: Optional[float],
                    field_sources: Dict[str, str], latency_ms: Optional[float] = None,
                    conflicts: Optional[list] = None) -> None:
        self.state_label.setText(link_state.label)
        self.state_label.setStyleSheet(
            f"color: {COLORES_ENLACE.get(link_state, COLOR_MUTED)}; font-weight: 700;")

        if age_seconds is None:
            self.age_label.setText("--")
        else:
            texto = f"hace {age_seconds:.1f} s"
            if latency_ms is not None and age_seconds < 5:
                texto += f"  ({latency_ms:.0f} ms)"
            self.age_label.setText(texto)

        for clave, etiqueta in self.field_labels.items():
            # El marcador se cubre con las dos mitades a la vez.
            fuentes = [field_sources.get(clave)]
            if clave == "score_a":
                fuentes.append(field_sources.get("score_b"))
            valor = next((f for f in fuentes if f), None)
            if valor == SourceKind.BROWSER_DOM.value:
                etiqueta.setText("DOM ✓")
                etiqueta.setStyleSheet(f"color: {COLOR_OK};")
            elif valor == SourceKind.OCR.value:
                etiqueta.setText("OCR ✓")
                etiqueta.setStyleSheet(f"color: {COLOR_WARN};")
            elif valor == SourceKind.MANUAL.value:
                etiqueta.setText("manual ✓")
                etiqueta.setStyleSheet(f"color: {COLOR_WARN};")
            else:
                etiqueta.setText("--")
                etiqueta.setStyleSheet(f"color: {COLOR_MUTED};")

        pendientes = conflicts or []
        if pendientes:
            ultimo = pendientes[-1]
            self.conflict_label.setText(
                f"CONFLICTO DE FUENTES en {ultimo['field']}: DOM {ultimo['dom']} "
                f"frente a OCR {ultimo['ocr']}. Se usa el DOM.")
        else:
            self.conflict_label.setText("")
