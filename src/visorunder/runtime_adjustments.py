"""Ajustes de comportamiento acordados para el visor en vivo.

Este modulo concentra dos cambios de interfaz/adquisicion sin alterar el motor
matematico:

* un mercado que deja de existir en el DOM de BetPlay desaparece del radar;
* el bloque de reloj muestra primero el tiempo JUGADO del cuarto y debajo el
  tiempo RESTANTE, dando mayor jerarquia visual al tiempo jugado.

Se instala una sola vez al arrancar la aplicacion. Las clases conservan sus
atributos publicos para no romper la interfaz ni las pruebas existentes.
"""

from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel

from .domain.event_markets import EventMarkets
from .domain.market import MarketKey
from .ui import formatters as fmt
from .ui.metrics_panel import MetricsPanel, _card, _title

_INSTALLED = False
_ORIGINAL_UPDATE_VIEW = MetricsPanel.update_view
_ORIGINAL_SET_VISIBLE_MANY = EventMarkets.set_visible_many


def _build_clock_played_first(self: MetricsPanel):
    """Construye el bloque temporal con JUGADO arriba y RESTANTE debajo."""
    card = _card()
    grid = QGridLayout(card)
    grid.setContentsMargins(12, 10, 12, 10)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(6)

    # Se conserva period_label porque otros consumidores y pruebas lo usan,
    # aunque el periodo ahora se integra en el titulo de la primera fila.
    self.period_label = QLabel(fmt.UNKNOWN, card)
    self.period_label.setVisible(False)

    self.played_title = _title("JUGADO DEL CUARTO")
    self.played_title.setStyleSheet(
        "font-size: 17px; font-weight: 700; letter-spacing: 1px;"
    )
    self.played_label = QLabel(fmt.UNKNOWN)
    self.played_label.setObjectName("bigValue")
    self.played_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    self.played_label.setStyleSheet("font-size: 42px; font-weight: 800;")

    self.remaining_title = _title("RESTANTE")
    self.remaining_title.setStyleSheet(
        "font-size: 13px; font-weight: 700; letter-spacing: 1px;"
    )
    self.clock_label = QLabel(fmt.UNKNOWN)
    self.clock_label.setObjectName("bigValue")
    self.clock_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    self.clock_label.setStyleSheet("font-size: 31px; font-weight: 800;")

    self.phase_label = QLabel("")
    self.phase_label.setObjectName("status")

    grid.addWidget(self.played_title, 0, 0)
    grid.addWidget(self.played_label, 0, 1)
    grid.addWidget(self.remaining_title, 1, 0)
    grid.addWidget(self.clock_label, 1, 1)
    grid.addWidget(self.phase_label, 2, 0, 1, 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnMinimumWidth(1, 150)
    grid.setRowMinimumHeight(0, 54)
    return card


def _update_view_played_first(self: MetricsPanel, state, general, *args, **kwargs) -> None:
    """Mantiene el refresco original y actualiza el titulo con el cuarto."""
    _ORIGINAL_UPDATE_VIEW(self, state, general, *args, **kwargs)
    period = state.label()
    if period and period != fmt.UNKNOWN:
        self.played_title.setText(f"{period} - JUGADO DEL CUARTO")
    else:
        self.played_title.setText("JUGADO DEL CUARTO")
    self.remaining_title.setText("RESTANTE")


def _set_visible_many_pruning(self: EventMarkets, keys: Iterable[MarketKey],
                              primary: Optional[MarketKey] = None) -> None:
    """Quita del radar mercados que BetPlay ya retiro del DOM.

    `set_visible_many` solo se usa con la foto multi-mercado que entrega la
    extension. La lista recibida representa los mercados que EXISTEN en el DOM
    actual, no solo el que esta dentro del viewport.

    Se exigen dos ciclos consecutivos de ausencia antes de retirar un bloque.
    Si por una transicion el DOM llega completamente vacio, no se borra nada:
    se espera a la siguiente foto para evitar parpadeos o borrados masivos.
    """
    visibles = set(keys)
    missing_counts = dict(getattr(self, "_dom_missing_counts", {}))

    if visibles:
        for key in visibles:
            missing_counts.pop(key, None)

        for key in tuple(self.markets):
            if key in visibles:
                continue
            count = missing_counts.get(key, 0) + 1
            missing_counts[key] = count
            if count >= 2:
                self.markets.pop(key, None)
                missing_counts.pop(key, None)
    else:
        # Un escaneo vacio puede ocurrir durante una reconstruccion del DOM.
        # No se interpreta como retirada simultanea de todos los mercados.
        missing_counts.clear()

    self._dom_missing_counts = missing_counts
    _ORIGINAL_SET_VISIBLE_MANY(self, visibles, primary)


def install_runtime_adjustments() -> None:
    """Instala los dos ajustes una sola vez durante el arranque."""
    global _INSTALLED
    if _INSTALLED:
        return
    MetricsPanel._build_clock = _build_clock_played_first
    MetricsPanel.update_view = _update_view_played_first
    EventMarkets.set_visible_many = _set_visible_many_pruning
    _INSTALLED = True
