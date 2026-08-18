"""Preferencias de la aplicacion (no del perfil de casa)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .criteria import EntryCriteria
from .freshness import FreshnessCriteria
from .paths import settings_path


@dataclass
class AppSettings:
    last_profile: str = ""
    always_on_top: bool = True
    capture_backend: str = "auto"
    global_hotkeys: bool = True
    hotkeys: Dict[str, str] = field(default_factory=lambda: {
        "toggle_reading": "F8",
        "lock_bet": "F9",
        "toggle_panel": "F10",
        "finish_game": "F11",
    })
    window_geometry: Optional[list] = None
    log_to_file: bool = True
    #: Criterios de entrada (ritmo de referencia, cuota objetivo, umbrales).
    entry: EntryCriteria = field(default_factory=EntryCriteria)
    #: Umbrales de frescura de los mercados no visibles.
    freshness: FreshnessCriteria = field(default_factory=FreshnessCriteria)

    def save(self, path: Optional[Path] = None) -> None:
        target = Path(path) if path else settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def load(path: Optional[Path] = None) -> "AppSettings":
        target = Path(path) if path else settings_path()
        if not target.exists():
            return AppSettings()
        try:
            data: Dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppSettings()
        settings = AppSettings()
        for key, value in data.items():
            if key == "entry":
                settings.entry = EntryCriteria.from_dict(value)
            elif key == "freshness":
                settings.freshness = FreshnessCriteria.from_dict(value)
            elif hasattr(settings, key):
                setattr(settings, key, value)
        return settings
