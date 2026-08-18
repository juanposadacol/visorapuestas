"""Arranque directo sin instalar el paquete:  python run.py"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from visorunder.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
