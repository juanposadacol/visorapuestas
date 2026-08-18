"""Rutas locales de la aplicacion.

Todo se guarda en el equipo del usuario. No hay servidor ni nube (requisito 2).
En Windows: %APPDATA%\\VisorUnder
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "VisorUnder"


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return app_data_dir() / "visorunder.db"


def log_path() -> Path:
    logs = app_data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "visorunder.log"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def profiles_export_dir() -> Path:
    path = app_data_dir() / "perfiles"
    path.mkdir(parents=True, exist_ok=True)
    return path
