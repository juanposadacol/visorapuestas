"""Punto de entrada: python -m visorunder"""

from __future__ import annotations

import sys


def main(argv: list = None) -> int:
    import argparse

    from PySide6.QtWidgets import QApplication

    from .app import AppController
    from .ui.main_window import MainWindow
    from .ui.styles import STYLESHEET
    from .runtime_adjustments import install_runtime_adjustments

    parser = argparse.ArgumentParser(
        prog="visorunder",
        description="Visor de metricas UNDER: lee la pantalla y calcula. No apuesta.")
    parser.add_argument("--demo", action="store_true",
                        help="arranca con un partido simulado, sin leer la pantalla")
    parser.add_argument("--db", default=None, help="ruta alternativa de la base de datos")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Visor UNDER")
    app.setStyleSheet(STYLESHEET)

    # Ajustes acordados para el uso en vivo: mercados retirados fuera del radar
    # y tiempo jugado del cuarto con mayor jerarquia que el tiempo restante.
    install_runtime_adjustments()

    controller = AppController(db_path=args.db)
    if args.demo:
        controller.enable_demo()
    window = MainWindow(controller)
    if args.demo:
        window.profile_combo.setCurrentText("DEMO (partido simulado)")
        window.toggle_reading()

    geometry = controller.settings.window_geometry
    if geometry and len(geometry) == 4:
        window.setGeometry(*geometry)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
