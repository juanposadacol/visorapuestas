"""Regresion del cierre de la aplicacion al pulsar "Definir region".

Estas pruebas fijan el comportamiento correcto descrito por el usuario:

1. Pulsar "Definir region seleccionada" NO cierra la aplicacion.
2. ESC cancela la seleccion sin cerrar la aplicacion.
3. Al guardar una region se vuelve al ProfileDialog con la region puesta.
4. Un error real de captura se explica en pantalla, pero no mata el proceso.

La causa original tenia dos partes encadenadas, y cada una tiene aqui su
prueba:

* ocultar un QDialog termina su bucle modal, asi que `exec()` devolvia
  "cancelado" nada mas pulsar el boton;
* con el editor y la ventana principal ocultos, el overlay quedaba como
  unica ventana visible y al cerrarlo Qt emitia `lastWindowClosed` y
  terminaba el proceso.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 no instalado")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QRect, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox  # noqa: E402

from visorunder.capture.roi import Rect, RoiKind  # noqa: E402
from visorunder.capture.screen_capture import CaptureError  # noqa: E402
from visorunder.config.profiles import SportsbookProfile  # noqa: E402
from visorunder.ui.profile_dialog import ProfileDialog  # noqa: E402
from visorunder.ui.roi_selector import RoiOverlay, quit_guard  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeCapture:
    """Captura simulada: no toca la pantalla real."""

    def __init__(self, monitors=None, error: str = "") -> None:
        if monitors is None:
            monitors = [Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1080)]
        self._monitors = list(monitors)   # [] es un caso valido: sin pantallas
        self._error = error

    def monitors(self):
        return list(self._monitors)

    def grab(self, rect: Rect):
        if self._error:
            raise CaptureError(self._error)
        return np.zeros((rect.height, rect.width, 3), dtype=np.uint8)


@pytest.fixture()
def editor(qapp):
    """ProfileDialog de un perfil NUEVO de Stake, con su ventana principal."""
    main = QMainWindow()
    main.show()
    profile = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    dialog = ProfileDialog(profile, FakeCapture(), None, main)
    dialog.show()
    yield dialog, main
    dialog._restore_editor()
    dialog.close()
    main.close()


def _select_row(dialog: ProfileDialog, kind: RoiKind) -> None:
    from visorunder.ui.profile_dialog import ROI_ORDER

    dialog.table.selectRow(ROI_ORDER.index(kind))


def _drag(overlay: RoiOverlay, start: QPoint, end: QPoint) -> None:
    """Simula el arrastre completo del raton sobre el overlay."""
    overlay._origin = start
    overlay._current = end
    overlay.finish(overlay._to_physical(QRect(start, end).normalized()))


# ---------------------------------------------------------------------------
# 1. Pulsar "Definir region" no cierra la QApplication
# ---------------------------------------------------------------------------
def test_definir_region_no_cierra_la_aplicacion(qapp, editor):
    dialog, main = editor
    cerrada = []
    qapp.lastWindowClosed.connect(lambda: cerrada.append("lastWindowClosed"))

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()

    overlay = dialog._overlay
    assert overlay is not None, "no se abrio el overlay de seleccion"
    assert overlay.isVisible()

    # El momento critico: terminar la seleccion siendo la unica ventana visible.
    _drag(overlay, QPoint(100, 120), QPoint(400, 260))
    qapp.processEvents()

    assert cerrada == [], "cerrar el overlay emitio lastWindowClosed"
    assert QApplication.instance() is not None
    assert dialog.isVisible(), "el editor de perfil no volvio"
    assert main.isVisible(), "la ventana principal no volvio"


def test_el_guardia_de_cierre_se_restaura(qapp, editor):
    """El guardia es temporal: no puede dejar la aplicacion sin cerrar nunca."""
    dialog, _main = editor
    previo = qapp.quitOnLastWindowClosed()

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()
    assert qapp.quitOnLastWindowClosed() is False, "el guardia no se activo"

    _drag(dialog._overlay, QPoint(10, 10), QPoint(120, 90))
    assert qapp.quitOnLastWindowClosed() == previo, "el guardia no se restauro"


def test_quit_guard_restaura_incluso_con_excepcion(qapp):
    previo = qapp.quitOnLastWindowClosed()
    with pytest.raises(RuntimeError):
        with quit_guard():
            assert qapp.quitOnLastWindowClosed() is False
            raise RuntimeError("fallo dentro de la seleccion")
    assert qapp.quitOnLastWindowClosed() == previo


# ---------------------------------------------------------------------------
# 2. ESC cancela sin cerrar la aplicacion
# ---------------------------------------------------------------------------
def test_escape_cancela_sin_cerrar_la_aplicacion(qapp, editor):
    dialog, main = editor
    cerrada = []
    qapp.lastWindowClosed.connect(lambda: cerrada.append("lastWindowClosed"))

    _select_row(dialog, RoiKind.PERIOD)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()

    overlay = dialog._overlay
    assert overlay is not None
    overlay.keyPressEvent(_escape_event())
    qapp.processEvents()

    assert cerrada == []
    assert dialog.isVisible()
    assert main.isVisible()
    assert dialog.profile.get_roi(RoiKind.PERIOD) is None, "ESC no debe guardar nada"
    assert dialog._overlay is None


def _escape_event():
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)


# ---------------------------------------------------------------------------
# 3. Guardar una region y volver al ProfileDialog
# ---------------------------------------------------------------------------
def test_guardar_region_vuelve_al_dialogo_con_la_region(qapp, editor):
    dialog, _main = editor

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()
    _drag(dialog._overlay, QPoint(200, 100), QPoint(500, 220))

    roi = dialog.profile.get_roi(RoiKind.CLOCK)
    assert roi is not None, "la region no quedo guardada en el perfil"

    rect = roi.resolve(dialog.profile.frame)
    assert rect.width > 0 and rect.height > 0

    # Y la tabla del editor lo refleja.
    from visorunder.ui.profile_dialog import ROI_ORDER

    fila = ROI_ORDER.index(RoiKind.CLOCK)
    assert dialog.table.item(fila, 1).text() == "definida"
    assert dialog.table.item(fila, 2).text() != "--"
    assert dialog.isVisible()
    assert dialog._overlay is None


def test_varias_regiones_seguidas(qapp, editor):
    """Definir una region no debe impedir definir la siguiente."""
    dialog, _main = editor
    for kind in (RoiKind.CLOCK, RoiKind.PERIOD, RoiKind.MARKET_BLOCK):
        _select_row(dialog, kind)
        dialog.define_button.click()
        dialog._capture_timer.stop()
        dialog._capture_selection()
        assert dialog._overlay is not None, f"no se abrio el overlay para {kind}"
        _drag(dialog._overlay, QPoint(50, 50), QPoint(300, 200))
        assert dialog.profile.get_roi(kind) is not None

    assert len(dialog.profile.rois) == 3


# ---------------------------------------------------------------------------
# 4. El bucle modal sobrevive a la seleccion
# ---------------------------------------------------------------------------
def test_exec_no_devuelve_cancelado_al_definir_una_region(qapp, monkeypatch):
    """`exec()` solo debe volver cuando el usuario guarda o cancela de verdad.

    Ocultar el dialogo para dibujar la region rompe el bucle modal de Qt. Si
    `exec()` devolviera ahi, la ventana que lo abrio daria el perfil por
    descartado -- que es justo lo que ocurria.
    """
    # Al guardar con regiones incompletas el editor pregunta si continuar.
    # Se responde que si para no bloquear la prueba en un dialogo modal.
    monkeypatch.setattr(
        "visorunder.ui.profile_dialog.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )

    main = QMainWindow()
    main.show()
    profile = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    dialog = ProfileDialog(profile, FakeCapture(), None, main)
    pasos = []

    def definir():
        _select_row(dialog, RoiKind.CLOCK)
        dialog.define_button.click()
        dialog._capture_timer.stop()
        dialog._capture_selection()
        pasos.append(("overlay abierto", dialog._overlay is not None))
        QTimer.singleShot(0, terminar_arrastre)

    def terminar_arrastre():
        _drag(dialog._overlay, QPoint(120, 140), QPoint(420, 300))
        pasos.append(("region guardada", dialog.profile.get_roi(RoiKind.CLOCK) is not None))
        pasos.append(("exec seguia vivo", True))
        QTimer.singleShot(0, guardar)

    def guardar():
        dialog.name_edit.setText("Stake principal")
        dialog._on_save()

    QTimer.singleShot(0, definir)
    resultado = dialog.exec()

    assert pasos == [
        ("overlay abierto", True),
        ("region guardada", True),
        ("exec seguia vivo", True),
    ]
    assert resultado == ProfileDialog.Accepted, (
        "exec() devolvio cancelado: el bucle modal murio al ocultar el dialogo")
    assert dialog.profile.get_roi(RoiKind.CLOCK) is not None
    main.close()


# ---------------------------------------------------------------------------
# 5. Errores reales: se explican, no matan
# ---------------------------------------------------------------------------
def test_error_de_captura_no_mata_la_aplicacion(qapp, monkeypatch):
    main = QMainWindow()
    main.show()
    profile = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    dialog = ProfileDialog(profile, FakeCapture(error="backend no disponible"), None, main)
    dialog.show()

    avisos = []
    monkeypatch.setattr(
        "visorunder.ui.profile_dialog.QMessageBox.warning",
        lambda *args, **kwargs: avisos.append(args[2]) or 0,
    )

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()

    assert avisos, "un error real de captura debe avisarse"
    assert "backend no disponible" in avisos[0]
    # Traceback completo registrado: el fallo no se esconde.
    assert "CaptureError" in dialog.last_capture_error
    assert dialog.isVisible() and main.isVisible()
    assert qapp.quitOnLastWindowClosed() is True, "el guardia quedo colgado"
    assert QApplication.instance() is not None
    dialog.close()
    main.close()


def test_sin_pantalla_seleccionada_no_revienta(qapp, monkeypatch):
    main = QMainWindow()
    main.show()
    profile = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    dialog = ProfileDialog(profile, FakeCapture(monitors=[]), None, main)
    dialog.show()

    avisos = []
    monkeypatch.setattr(
        "visorunder.ui.profile_dialog.QMessageBox.warning",
        lambda *args, **kwargs: avisos.append(args[2]) or 0,
    )

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()

    assert avisos and "pantalla" in avisos[0].lower()
    assert dialog.isVisible() and main.isVisible()
    dialog.close()
    main.close()


# ---------------------------------------------------------------------------
# 6. El overlay avisa antes de cerrarse
# ---------------------------------------------------------------------------
def test_el_overlay_avisa_antes_de_cerrarse(qapp):
    """Orden obligatorio: ocultar -> avisar -> cerrar.

    Si el overlay se cerrara antes de avisar, quien escucha no habria podido
    volver a mostrar sus ventanas y Qt cerraria la aplicacion.
    """
    imagen = np.zeros((100, 200, 3), dtype=np.uint8)
    overlay = RoiOverlay(imagen, Rect(0, 0, 200, 100), title="prueba")
    overlay.show()
    orden = []
    overlay.regionSelected.connect(
        lambda rect: orden.append(("aviso", overlay.isVisible())))
    overlay.destroyed.connect(lambda *_: orden.append(("destruido", False)))

    overlay.finish(Rect(1, 2, 30, 40))

    assert orden and orden[0][0] == "aviso"
    assert overlay.selected_rect == Rect(1, 2, 30, 40)
    assert not overlay.isVisible()


def test_el_overlay_cancela_una_sola_vez(qapp):
    imagen = np.zeros((100, 200, 3), dtype=np.uint8)
    overlay = RoiOverlay(imagen, Rect(0, 0, 200, 100))
    overlay.show()
    avisos = []
    overlay.cancelled.connect(lambda: avisos.append("cancelado"))

    overlay.finish(None)
    overlay.close()          # cerrar de nuevo no debe volver a avisar

    assert avisos == ["cancelado"]
    assert overlay.selected_rect is None


def test_cierre_externo_del_overlay_se_trata_como_cancelacion(qapp):
    imagen = np.zeros((100, 200, 3), dtype=np.uint8)
    overlay = RoiOverlay(imagen, Rect(0, 0, 200, 100))
    overlay.show()
    avisos = []
    overlay.cancelled.connect(lambda: avisos.append("cancelado"))

    overlay.close()          # como si se cerrara desde el gestor de ventanas

    assert avisos == ["cancelado"]


# ---------------------------------------------------------------------------
# 7. Redes de seguridad: nunca colgarse ni dejar el guardia puesto
# ---------------------------------------------------------------------------
def test_una_seleccion_que_muere_sin_avisar_no_cuelga_exec(qapp, editor):
    """Si el overlay desaparece sin avisar, `exec()` no puede quedarse esperando."""
    dialog, _main = editor

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()          # la captura nunca llega a ocurrir
    assert dialog.is_selecting_roi is True
    assert dialog._overlay is None

    # exec() detecta que no hay nada a lo que esperar y restaura el editor.
    dialog._wait_for_selection()

    assert dialog.is_selecting_roi is False
    assert dialog.isVisible()
    assert qapp.quitOnLastWindowClosed() is True, "el guardia quedo colgado"


def test_cerrar_el_dialogo_durante_la_seleccion_lo_deja_todo_limpio(qapp):
    main = QMainWindow()
    main.show()
    profile = SportsbookProfile(name="Stake principal", sportsbook="Stake")
    dialog = ProfileDialog(profile, FakeCapture(), None, main)
    dialog.show()

    _select_row(dialog, RoiKind.CLOCK)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()
    assert dialog._overlay is not None

    dialog.reject()          # el usuario cierra el editor con la seleccion abierta

    assert dialog.is_selecting_roi is False
    assert dialog._overlay is None, "quedo un overlay huerfano en pantalla"
    assert qapp.quitOnLastWindowClosed() is True, "el guardia quedo colgado"
    assert profile.get_roi(RoiKind.CLOCK) is None
    assert main.isVisible(), "la ventana principal no volvio"
    main.close()


# ---------------------------------------------------------------------------
# 8. La region del tablero completo se configura como cualquier otra
# ---------------------------------------------------------------------------
def test_el_tablero_completo_aparece_en_el_editor(qapp, editor):
    """Debe poder elegirse en CONFIGURAR PERFIL, con nombre reconocible."""
    from visorunder.ui.profile_dialog import ROI_ORDER

    dialog, _main = editor
    assert RoiKind.SCOREBOARD in ROI_ORDER, "el tablero no se puede configurar"

    fila = ROI_ORDER.index(RoiKind.SCOREBOARD)
    nombre = dialog.table.item(fila, 0).text()
    assert "Tablero" in nombre
    assert "*" not in nombre, "el tablero no puede ser obligatorio para todos"


def test_definir_el_tablero_no_cierra_la_aplicacion(qapp, editor):
    """El mismo requisito que las demas regiones, tambien para esta."""
    dialog, main = editor
    cerrada = []
    qapp.lastWindowClosed.connect(lambda: cerrada.append("lastWindowClosed"))

    _select_row(dialog, RoiKind.SCOREBOARD)
    dialog.define_button.click()
    dialog._capture_timer.stop()
    dialog._capture_selection()

    overlay = dialog._overlay
    assert overlay is not None
    _drag(overlay, QPoint(300, 80), QPoint(1200, 260))
    qapp.processEvents()

    assert cerrada == []
    assert QApplication.instance() is not None
    assert dialog.isVisible() and main.isVisible()
    assert dialog.profile.get_roi(RoiKind.SCOREBOARD) is not None


def test_con_el_tablero_definido_no_hacen_falta_las_otras_regiones(qapp, editor):
    """Un perfil de Stake se completa con el tablero y el bloque de lineas."""
    dialog, _main = editor

    for kind, inicio, fin in ((RoiKind.SCOREBOARD, QPoint(300, 80), QPoint(1200, 260)),
                              (RoiKind.MARKET_BLOCK, QPoint(1300, 350), QPoint(1700, 650))):
        _select_row(dialog, kind)
        dialog.define_button.click()
        dialog._capture_timer.stop()
        dialog._capture_selection()
        _drag(dialog._overlay, inicio, fin)

    assert dialog.profile.missing_required() == [], (
        "el tablero debe cubrir reloj, cuarto y marcador")
