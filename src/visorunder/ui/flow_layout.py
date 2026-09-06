"""Filas que se parten en varias lineas cuando la ventana se estrecha.

Una `QHBoxLayout` normal impone como ancho MINIMO la SUMA de todo lo que
contiene. En la barra superior eso eran 1222 px: mas de lo que mide de ancho
una pantalla vertical, asi que la ventana no podia encogerse por debajo de esa
cifra y la columna de metricas se quedaba sin sitio aunque el usuario
arrastrase el divisor.

`FlowLayout` coloca los mismos widgets en una sola fila mientras quepan y los
va bajando de linea cuando no. Su ancho minimo es el del elemento MAS ANCHO,
no la suma, de modo que ningun boton se recorta ni desaparece: solo cambia de
sitio. El ancho preferido sigue siendo el de una fila unica, asi que en una
pantalla ancha la barra se ve exactamente igual que antes.

Los espaciadores elasticos (`add_stretch`) se respetan dentro de cada fila: el
sobrante de esa linea se reparte entre ellos, que es lo que mantiene la
casilla "Siempre encima" pegada a la derecha mientras la barra cabe entera.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)


def _es_elastico(item: QLayoutItem) -> bool:
    """Un espaciador que absorbe el ancho sobrante de su fila."""
    return (item.spacerItem() is not None
            and bool(item.expandingDirections() & Qt.Horizontal))


class FlowLayout(QLayout):
    """Disposicion horizontal que salta de linea en vez de exigir el ancho."""

    def __init__(self, parent: Optional[QWidget] = None,
                 spacing: int = 6, vertical_spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: List[QLayoutItem] = []
        self._spacing = spacing
        self._vertical_spacing = vertical_spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ------------------------------------------------------- api de QLayout
    def addItem(self, item: QLayoutItem) -> None:      # noqa: N802 (API de Qt)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:   # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:   # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:        # noqa: N802
        # No pide crecer por su cuenta: se conforma con el ancho que le den.
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:                     # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:             # noqa: N802
        return self._disponer(QRect(0, 0, width, 0), medir=True)

    def setGeometry(self, rect: QRect) -> None:              # noqa: N802
        super().setGeometry(rect)
        self._disponer(rect, medir=False)

    def sizeHint(self) -> QSize:                             # noqa: N802
        """Lo que mide puesto todo en una sola fila: el aspecto de siempre."""
        ancho = 0
        alto = 0
        visibles = 0
        for item in self._items:
            if _es_elastico(item):
                continue
            hint = item.sizeHint()
            ancho += hint.width()
            alto = max(alto, hint.height())
            visibles += 1
        ancho += max(0, visibles - 1) * self._spacing
        return self._con_margenes(QSize(ancho, alto))

    def minimumSize(self) -> QSize:                          # noqa: N802
        """El elemento mas ancho. Es la clave: NO la suma de todos."""
        minimo = QSize(0, 0)
        for item in self._items:
            if _es_elastico(item):
                continue
            minimo = minimo.expandedTo(item.minimumSize())
        return self._con_margenes(minimo)

    # ------------------------------------------------------------- interno
    def _con_margenes(self, size: QSize) -> QSize:
        margenes = self.contentsMargins()
        return QSize(size.width() + margenes.left() + margenes.right(),
                     size.height() + margenes.top() + margenes.bottom())

    def _filas(self, disponible: int) -> List[tuple]:
        """Reparte los elementos en filas segun el ancho que haya.

        Devuelve `(elementos, ancho_ocupado, alto_de_la_fila)` por fila. Los
        espaciadores elasticos viajan con su fila pero no ocupan ancho aqui:
        se les asigna el sobrante al pintar.
        """
        filas: List[tuple] = []
        actual: List[QLayoutItem] = []
        ancho = 0
        alto = 0
        for item in self._items:
            if _es_elastico(item):
                actual.append(item)
                continue
            hint = item.sizeHint()
            separacion = self._spacing if ancho > 0 else 0
            if ancho > 0 and ancho + separacion + hint.width() > disponible:
                filas.append((actual, ancho, alto))
                actual, ancho, alto = [], 0, 0
                separacion = 0
            actual.append(item)
            ancho += separacion + hint.width()
            alto = max(alto, hint.height())
        if actual:
            filas.append((actual, ancho, alto))
        return filas

    def _disponer(self, rect: QRect, medir: bool) -> int:
        margenes = self.contentsMargins()
        util = rect.adjusted(margenes.left(), margenes.top(),
                             -margenes.right(), -margenes.bottom())
        disponible = max(1, util.width())

        y = util.y()
        for indice, (elementos, ancho, alto) in enumerate(self._filas(disponible)):
            if indice:
                y += self._vertical_spacing
            if not medir:
                self._pintar_fila(elementos, util.x(), y, disponible - ancho, alto)
            y += alto
        return y - rect.y() + margenes.bottom()

    def _pintar_fila(self, elementos: List[QLayoutItem], x: int, y: int,
                     sobrante: int, alto: int) -> None:
        elasticos = [i for i in elementos if _es_elastico(i)]
        reparto = max(0, sobrante) // len(elasticos) if elasticos else 0
        primero = True
        for item in elementos:
            if _es_elastico(item):
                x += reparto
                continue
            if not primero:
                x += self._spacing
            primero = False
            hint = item.sizeHint()
            # Centrado vertical: mezclar botones y casillas en la misma fila
            # sin que unos queden colgando de la linea base de los otros.
            desplazamiento = max(0, (alto - hint.height()) // 2)
            item.setGeometry(QRect(QPoint(x, y + desplazamiento), hint))
            x += hint.width()


class FlowRow(QWidget):
    """Contenedor listo para usar: una fila de controles que sabe partirse."""

    def __init__(self, parent: Optional[QWidget] = None,
                 spacing: int = 6, vertical_spacing: int = 4) -> None:
        super().__init__(parent)
        self._flow = FlowLayout(self, spacing=spacing,
                                vertical_spacing=vertical_spacing)
        politica = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        # Sin esto el layout padre reserva el alto de UNA fila y las lineas
        # que se van anadiendo al estrecharse quedarian recortadas.
        politica.setHeightForWidth(True)
        self.setSizePolicy(politica)

    def add(self, widget: QWidget) -> QWidget:
        self._flow.addWidget(widget)
        return widget

    def add_stretch(self) -> None:
        self._flow.addItem(QSpacerItem(0, 0, QSizePolicy.Expanding,
                                       QSizePolicy.Minimum))

    def add_spacing(self, ancho: int) -> None:
        self._flow.addItem(QSpacerItem(ancho, 0, QSizePolicy.Fixed,
                                       QSizePolicy.Minimum))

    def hasHeightForWidth(self) -> bool:                     # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:             # noqa: N802
        return self._flow.heightForWidth(width)

    def sizeHint(self) -> QSize:                             # noqa: N802
        return self._flow.sizeHint()

    def minimumSizeHint(self) -> QSize:                      # noqa: N802
        return self._flow.minimumSize()
