"""Seleccion visual de regiones (requisitos 3, 23 y 25).

El usuario dibuja con el raton los rectangulos sobre una captura real de su
pantalla. Detalles importantes:

* La captura se hace con el MISMO backend que usara el lector, asi que las
  coordenadas coinciden exactamente con lo que se leera despues.
* El dibujo se hace sobre la imagen ESCALADA a la ventana; el rectangulo se
  convierte a pixeles fisicos con el factor de escala real, de modo que el
  escalado de Windows (125 %, 150 %) no descoloca nada.
* ESC cancela la seleccion, como pide el requisito 26.

CICLO DE VIDA (por que importa tanto el orden)
----------------------------------------------
Mientras se elige la region, el overlay es la UNICA ventana visible: el
editor de perfil y la ventana principal estan ocultos para que no salgan en
la captura. En ese estado, cerrar el overlay deja la aplicacion sin ninguna
ventana visible y Qt, con `quitOnLastWindowClosed` activo (el valor por
defecto), emite `lastWindowClosed` y TERMINA EL PROCESO.

Por eso aqui se hacen dos cosas:

1. `quit_guard()` desactiva temporalmente ese cierre automatico mientras dura
   la seleccion, y lo restaura exactamente como estaba al terminar.
2. El overlay avisa del resultado ANTES de cerrarse (`hide` -> emitir ->
   `close`), de modo que quien escucha ya ha vuelto a mostrar sus ventanas
   cuando el overlay desaparece de verdad.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..capture.roi import Rect
from ..capture.screen_capture import ScreenCapture


def numpy_to_qimage(array: Any) -> QImage:
    """Convierte una imagen BGR de OpenCV/numpy en QImage RGB."""
    if array is None:
        return QImage()
    height, width = array.shape[:2]
    if array.ndim == 2:
        return QImage(array.data, width, height, width, QImage.Format_Grayscale8).copy()
    bytes_per_line = 3 * width
    rgb = array[:, :, ::-1].copy()  # BGR -> RGB
    return QImage(rgb.data, width, height, bytes_per_line, QImage.Format_RGB888).copy()


def grab_desktop(capture: ScreenCapture, monitor: Optional[Rect] = None) -> Tuple[Any, Rect]:
    """Captura el monitor completo para poder dibujar encima."""
    if monitor is None:
        monitors = capture.monitors()
        monitor = monitors[0] if monitors else Rect(0, 0, 1920, 1080)
    return capture.grab(monitor), monitor


@contextmanager
def quit_guard() -> Iterator[None]:
    """Evita que quedarse sin ventanas visibles termine la aplicacion.

    Qt cierra el proceso cuando se cierra la ultima ventana visible. Durante
    la seleccion de una region eso es justo lo que pasa: el editor y la
    ventana principal estan ocultos y el overlay es la unica ventana viva,
    asi que al cerrarlo Qt daba por terminada la aplicacion entera.

    El guardia desactiva ese comportamiento mientras dura la seleccion y
    restaura SIEMPRE el valor anterior, incluso si algo falla por el camino.
    No se deja desactivado: cerrar la ventana principal debe seguir cerrando
    la aplicacion como siempre.
    """
    app = QGuiApplication.instance()
    if app is None:
        yield
        return
    previous = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    try:
        yield
    finally:
        app.setQuitOnLastWindowClosed(previous)


class RoiOverlay(QWidget):
    """Ventana a pantalla completa para dibujar UN rectangulo."""

    regionSelected = Signal(object)  # Rect en pixeles fisicos
    cancelled = Signal()

    def __init__(self, image: Any, monitor: Rect, title: str = "",
                 parent: Optional[QWidget] = None, screen=None) -> None:
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(title or "Selecciona la region")
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        self._monitor = monitor
        self._qimage = numpy_to_qimage(image)
        self._pixmap = QPixmap.fromImage(self._qimage)
        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._title = title
        self._completed = False
        #: Region elegida, o None si se cancelo. Permite leer el resultado sin
        #: depender de las senales cuando la llamada es sincrona.
        self.selected_rect: Optional[Rect] = None

        screen = screen or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())

    # ------------------------------------------------------------- geometria
    def _scale(self) -> Tuple[float, float]:
        """Factor imagen-fisica / ventana-logica."""
        if self.width() <= 0 or self.height() <= 0 or self._pixmap.isNull():
            return (1.0, 1.0)
        return (self._pixmap.width() / self.width(), self._pixmap.height() / self.height())

    def _to_physical(self, rect: QRect) -> Rect:
        sx, sy = self._scale()
        return Rect(
            x=int(round(self._monitor.x + rect.x() * sx)),
            y=int(round(self._monitor.y + rect.y() * sy)),
            width=max(1, int(round(rect.width() * sx))),
            height=max(1, int(round(rect.height() * sy))),
        )

    def _selection_rect(self) -> Optional[QRect]:
        if self._origin is None or self._current is None:
            return None
        return QRect(self._origin, self._current).normalized()

    # -------------------------------------------------------------- eventos
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._origin is None:
            return
        self._current = event.position().toPoint()
        rect = self._selection_rect()
        self._origin = None
        if rect is None or rect.width() < 4 or rect.height() < 4:
            self.update()
            return
        self.finish(self._to_physical(rect))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.finish(None)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ resultado
    def finish(self, rect: Optional[Rect]) -> None:
        """Termina la seleccion en el UNICO orden que no mata la aplicacion.

        1. `hide()` saca el overlay de la pantalla. Ocultar no dispara el
           cierre automatico de Qt; cerrar si.
        2. Se avisa del resultado, de modo que quien escucha vuelva a mostrar
           el editor de perfil y la ventana principal.
        3. Solo entonces se cierra el overlay: para ese momento ya hay otra
           ventana visible, asi que no queda ninguna 'ultima ventana' que
           cerrar y la aplicacion sigue viva.

        Antes se cerraba primero y se avisaba despues, y ese orden dejaba a la
        aplicacion sin ninguna ventana visible durante el cierre.
        """
        if self._completed:
            return
        self._completed = True
        self.selected_rect = rect

        self.hide()
        if rect is None:
            self.cancelled.emit()
        else:
            self.regionSelected.emit(rect)
        self.close()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        # Cierre por otra via (boton del gestor de ventanas, cierre forzado):
        # se trata como cancelacion para que el editor vuelva igualmente.
        if not self._completed:
            self._completed = True
            self.selected_rect = None
            self.cancelled.emit()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if not self._pixmap.isNull():
            painter.drawPixmap(self.rect(), self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        selection = self._selection_rect()
        if selection is not None and not self._pixmap.isNull():
            source = QRect(
                int(selection.x() * self._scale()[0]), int(selection.y() * self._scale()[1]),
                max(1, int(selection.width() * self._scale()[0])),
                max(1, int(selection.height() * self._scale()[1])),
            )
            painter.drawPixmap(selection, self._pixmap, source)
            pen = QPen(QColor("#3fa7ff"), 2)
            painter.setPen(pen)
            painter.drawRect(selection)

        painter.setPen(QPen(QColor("#e6ebf2")))
        font = painter.font()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        message = self._title or "Arrastra para seleccionar la region"
        painter.drawText(QRect(0, 24, self.width(), 40), Qt.AlignHCenter,
                         message)
        font.setPointSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(QRect(0, 64, self.width(), 30), Qt.AlignHCenter,
                         "Arrastra con el boton izquierdo   |   ESC para cancelar")
        painter.end()
