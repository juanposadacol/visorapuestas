"""Atajos de teclado (requisito 26).

Dos capas:

* ATAJOS GLOBALES con `pynput`: funcionan aunque el foco este en Chrome, que
  es el caso normal mientras se sigue el partido. No requieren permisos de
  administrador.
* ATAJOS LOCALES con QShortcut: siempre disponibles cuando la ventana tiene
  foco, y sirven de respaldo si pynput no esta instalado.

Las combinaciones son configurables desde la propia clase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

DEFAULT_BINDINGS: Dict[str, str] = {
    "toggle_reading": "F8",   # iniciar / pausar lectura
    "lock_bet": "F9",         # fijar la apuesta seleccionada
    "toggle_panel": "F10",    # mostrar / ocultar el panel
    "finish_game": "F11",     # finalizar partido
}


@dataclass
class HotkeyManager:
    """Registra los atajos y avisa por callbacks."""

    widget: QWidget
    bindings: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_BINDINGS))
    callbacks: Dict[str, Callable[[], None]] = field(default_factory=dict)
    global_enabled: bool = True
    _listener: Optional[object] = None
    _shortcuts: list = field(default_factory=list)

    def register(self, action: str, callback: Callable[[], None]) -> None:
        self.callbacks[action] = callback

    def apply(self) -> None:
        """Instala los atajos locales y, si se puede, los globales."""
        self._install_local()
        if self.global_enabled:
            self._install_global()

    def _install_local(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
        self._shortcuts.clear()
        for action, key in self.bindings.items():
            callback = self.callbacks.get(action)
            if callback is None:
                continue
            shortcut = QShortcut(QKeySequence(key), self.widget)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _install_global(self) -> bool:
        """Atajos globales con pynput. Devuelve False si no esta disponible."""
        try:
            from pynput import keyboard
        except Exception:
            return False

        mapping = {}
        for action, key in self.bindings.items():
            callback = self.callbacks.get(action)
            if callback is None:
                continue
            mapping[f"<{key.lower()}>"] = _thread_safe(self.widget, callback)
        if not mapping:
            return False
        try:
            listener = keyboard.GlobalHotKeys(mapping)
            listener.daemon = True
            listener.start()
        except Exception:
            return False
        self._listener = listener
        return True

    def stop(self) -> None:
        listener = self._listener
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
            self._listener = None

    @property
    def global_active(self) -> bool:
        return self._listener is not None

    def describe(self) -> str:
        parts = [f"{key}: {_ACTION_NAMES.get(action, action)}"
                 for action, key in self.bindings.items()]
        return "   |   ".join(parts)


_ACTION_NAMES = {
    "toggle_reading": "iniciar/pausar",
    "lock_bet": "fijar apuesta",
    "toggle_panel": "mostrar/ocultar",
    "finish_game": "finalizar partido",
}


def _thread_safe(widget: QWidget, callback: Callable[[], None]) -> Callable[[], None]:
    """Los atajos globales llegan en otro hilo: se reencaminan al hilo de Qt."""
    from PySide6.QtCore import QTimer

    def wrapper() -> None:
        QTimer.singleShot(0, callback)

    return wrapper
