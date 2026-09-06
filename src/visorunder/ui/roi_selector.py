"""Seleccion visual de regiones (requisitos 3, 23 y 25).

El usuario dibuja con el raton los rectangulos sobre una captura real de su
pantalla. Detalles importantes:

* La captura se hace con el MISMO backend que usara el lector, asi que las
  coordenadas coinciden exactamente con lo que se leera despues.
* El dibujo se hace sobre la imagen ESCALADA a la ventana; el rectangulo se
  convierte a pixeles fisicos con el factor de escala real, de modo que el
  escalado de Windows (125 %, 150 %) no descoloca nada.
* ESC cancela la seleccion, como pide el requisito 26.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

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
        physical = self._to_physical(rect)
        self._completed = True
        self.close()
        self.regionSelected.emit(physical)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if not self._completed:
            self._completed = True
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
