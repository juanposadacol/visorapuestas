"""La columna izquierda manda: reparto horizontal de la ventana principal.

La zona de lectura -marcador, promedios, jugado/restante, linea enfocada y
seguimiento- es la que se mira de un vistazo mientras corre el partido. Estas
pruebas fijan que se lleve la mayor parte del ancho, que nunca se recorte y
que el que ceda espacio sea el radar, que ademas tiene scroll propio.

Son pruebas de PRESENTACION: no tocan ningun calculo, ninguna senal ni
ninguna persistencia.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QLabel,
    QPushButton,
)

from visorunder.app import AppController  # noqa: E402
from visorunder.capture.screen_capture import NullCapture  # noqa: E402
from visorunder.pipeline.demo import DemoGame  # noqa: E402
from visorunder.ui.flow_layout import FlowRow  # noqa: E402
from visorunder.ui.main_window import (  # noqa: E402
    LEFT_AREA_SHARE,
    RIGHT_AREA_SHARE,
    MainWindow,
)

#: Pantalla vertical tipica: un monitor de 1920x1080 girado.
PANTALLA_VERTICAL = (1080, 1920)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def window(qapp, tmp_path):
    controller = AppController(db_path=str(tmp_path / "layout.db"),
                               capture=NullCapture())
    controller.settings.log_to_file = False
    win = MainWindow(controller)
    win.timer.stop()
    win.show()
    yield win, controller, qapp
    win.hotkeys.stop()
    controller.shutdown()


@pytest.fixture()
def window_en_vivo(qapp, tmp_path):
    """Ventana con un partido simulado: la columna lleva datos de verdad."""
    controller = AppController(db_path=str(tmp_path / "vivo.db"))
    controller.settings.log_to_file = False
    controller.enable_demo(
        DemoGame(period=3, clock_seconds=328, score_a=43, score_b=31, speed=0.0))
    win = MainWindow(controller)
    win.timer.stop()
    win.profile_combo.setCurrentText("DEMO (partido simulado)")
    win.show()
    lector = controller.start_session(controller.profile)
    assert lector is not None
    lector.stop()                      # los ciclos se disparan a mano
    for _ in range(6):
        controller.reader.tick()
    win._refresh()
    qapp.processEvents()
    yield win, controller, qapp
    controller.finish_game()
    win.hotkeys.stop()
    controller.db.close()


def _proporcion_izquierda(win) -> float:
    izquierda, derecha = win.main_splitter.sizes()
    return izquierda / max(1, izquierda + derecha)


def _etiquetas_cortadas(widget):
    """Etiquetas cuyo texto no cabe en el ancho que tienen asignado."""
    cortadas = []
    for label in widget.findChildren(QLabel):
        texto = label.text()
        if not texto.strip() or label.wordWrap():
            continue
        if label.fontMetrics().horizontalAdvance(texto) > label.width() + 1:
            cortadas.append((texto, label.width()))
    return cortadas


# ---------------------------------------------------------------------------
# 1. El reparto inicial favorece la izquierda
# ---------------------------------------------------------------------------
def test_el_reparto_inicial_favorece_la_columna_izquierda(window):
    win, _controller, qapp = window
    win.resize(1200, 900)
    qapp.processEvents()

    proporcion = _proporcion_izquierda(win)
    assert 0.55 <= proporcion <= 0.65, (
        f"la izquierda se queda con el {proporcion:.0%}; se pidio entre 55 % y 65 %")


def test_las_proporciones_declaradas_dan_prioridad_a_la_izquierda():
    """La constante, no solo el resultado: quien lea el codigo lo ve igual."""
    total = LEFT_AREA_SHARE + RIGHT_AREA_SHARE
    assert LEFT_AREA_SHARE > RIGHT_AREA_SHARE
    assert 0.55 <= LEFT_AREA_SHARE / total <= 0.65


def test_la_proporcion_se_mantiene_al_ensanchar_la_ventana(window):
    """No es un tamano fijo en pixeles: es un reparto que escala."""
    win, _controller, qapp = window
    medidas = []
    for ancho in (900, 1200, 1500, 1800):
        win.resize(ancho, 1000)
        qapp.processEvents()
        medidas.append(_proporcion_izquierda(win))

    for ancho, proporcion in zip((900, 1200, 1500, 1800), medidas):
        assert 0.55 <= proporcion <= 0.65, (
            f"a {ancho} px de ancho la izquierda cae al {proporcion:.0%}")


# ---------------------------------------------------------------------------
# 2. La izquierda puede ampliarse a mano
# ---------------------------------------------------------------------------
def test_el_usuario_puede_dar_mas_ancho_a_la_izquierda(window):
    """Arrastrar el divisor tiene que servir de algo.

    Antes no servia: el radar imponia 480 px y el arrastre chocaba con esa
    pared mucho antes de llegar a donde el usuario apuntaba.
    """
    win, _controller, qapp = window
    win.resize(1200, 900)
    qapp.processEvents()
    antes, _ = win.main_splitter.sizes()

    total = sum(win.main_splitter.sizes())
    win.main_splitter.setSizes([int(total * 0.80), int(total * 0.20)])
    qapp.processEvents()

    izquierda, derecha = win.main_splitter.sizes()
    assert izquierda > antes, "arrastrar el divisor no amplio la izquierda"
    assert izquierda / (izquierda + derecha) >= 0.75, (
        "el divisor se quedo atascado antes de llegar al 75 %")


def test_la_izquierda_nunca_se_puede_plegar_del_todo(window):
    win, _controller, _qapp = window
    assert win.main_splitter.isCollapsible(0) is False, (
        "la columna prioritaria no puede quedar oculta")
    assert win.main_splitter.isCollapsible(1) is True, (
        "el radar si debe poder plegarse si el usuario quiere todo el ancho")


# ---------------------------------------------------------------------------
# 3. La derecha se comprime mas que la izquierda
# ---------------------------------------------------------------------------
def test_la_derecha_cede_antes_que_la_izquierda(window):
    win, _controller, _qapp = window
    izquierda = win.main_splitter.widget(0).minimumSizeHint().width()
    derecha = win.main_splitter.widget(1).minimumSizeHint().width()

    assert derecha < izquierda, (
        f"el radar exige {derecha} px y la columna de metricas solo {izquierda}: "
        "con esa relacion Qt estrangula la izquierda primero")


def test_pedir_todo_el_ancho_para_la_derecha_respeta_el_minimo_izquierdo(window):
    """Aun empujando el divisor al extremo, la izquierda conserva su suelo."""
    win, _controller, qapp = window
    win.resize(1200, 900)
    qapp.processEvents()
    total = sum(win.main_splitter.sizes())

    win.main_splitter.setSizes([0, total])
    qapp.processEvents()

    izquierda, _derecha = win.main_splitter.sizes()
    assert izquierda >= win.metrics_scroll.minimumWidth(), (
        "la izquierda bajo de su ancho minimo protegido")


# ---------------------------------------------------------------------------
# 4. El minimo de la izquierda protege su contenido
# ---------------------------------------------------------------------------
def test_el_minimo_de_la_izquierda_cubre_lo_que_ocupa_el_panel(window):
    """`QScrollArea` no propaga el minimo de su contenido; se hace a mano.

    Sin esto el divisor estrechaba la columna por debajo del panel y, como la
    barra horizontal esta desactivada a proposito, los valores alineados a la
    derecha se cortaban sin dejar forma de recuperarlos.
    """
    win, _controller, _qapp = window
    necesario = max(win.metrics_panel.minimumWidth(),
                    win.metrics_panel.minimumSizeHint().width())

    assert win.metrics_scroll.minimumWidth() >= necesario, (
        "el area de scroll no protege el ancho que pide el panel de metricas")


def test_el_panel_de_metricas_nunca_se_sale_de_su_ventanilla(window_en_vivo):
    """Con datos reales y a varios anchos: nada queda fuera de la vista."""
    win, _controller, qapp = window_en_vivo
    for ancho in (1400, 1080, 900, 800):
        win.resize(ancho, 1400)
        win._refresh()
        qapp.processEvents()
        visible = win.metrics_scroll.viewport().width()
        assert win.metrics_panel.width() <= visible, (
            f"a {ancho} px el panel mide {win.metrics_panel.width()} y solo se "
            f"ven {visible}: {win.metrics_panel.width() - visible} px cortados")


def test_ningun_valor_de_la_izquierda_queda_cortado(window_en_vivo):
    win, _controller, qapp = window_en_vivo
    for ancho in (1400, 1080, 900, 800):
        win.resize(ancho, 1400)
        win._refresh()
        qapp.processEvents()
        cortadas = _etiquetas_cortadas(win.metrics_panel)
        assert not cortadas, (
            f"a {ancho} px se recortan estas etiquetas: "
            + ", ".join(f"{t!r} en {w} px" for t, w in cortadas))


# ---------------------------------------------------------------------------
# 5. Pantalla vertical / estrecha
# ---------------------------------------------------------------------------
def test_la_ventana_cabe_en_una_pantalla_vertical(window):
    """El caso real del usuario: un monitor girado, 1080 px de ancho.

    El minimo era de 1238 px -mas ancho que la pantalla-, asi que la ventana
    no cabia y no habia manera de dar mas sitio a la izquierda.
    """
    win, _controller, _qapp = window
    ancho_pantalla = PANTALLA_VERTICAL[0]
    assert win.minimumSizeHint().width() <= ancho_pantalla, (
        f"la ventana exige {win.minimumSizeHint().width()} px y la pantalla "
        f"tiene {ancho_pantalla}")


def test_en_pantalla_vertical_la_izquierda_sigue_siendo_prioritaria(window_en_vivo):
    win, _controller, qapp = window_en_vivo
    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()

    proporcion = _proporcion_izquierda(win)
    assert proporcion >= 0.55, (
        f"en pantalla vertical la izquierda cae al {proporcion:.0%}")
    assert not _etiquetas_cortadas(win.metrics_panel)


def test_en_ventana_estrecha_los_controles_siguen_estando(window):
    """Estrechar reordena la barra, no hace desaparecer botones."""
    win, _controller, qapp = window
    win.resize(700, 900)
    qapp.processEvents()

    for boton in (win.start_button, win.finish_button, win.configure_button,
                  win.criteria_button, win.new_profile_button):
        assert boton.isVisible(), f"{boton.text()} desaparecio al estrechar"
        assert boton.width() >= boton.minimumSizeHint().width(), (
            f"{boton.text()} quedo recortado")


# ---------------------------------------------------------------------------
# 6. Los widgets criticos de la izquierda conservan un ancho util
# ---------------------------------------------------------------------------
def test_los_bloques_criticos_de_la_izquierda_conservan_ancho(window_en_vivo):
    win, _controller, qapp = window_en_vivo
    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()

    panel = win.metrics_panel
    criticos = {
        "resultados actuales": panel.results_table,
        "puntos para superar": panel.points_to_exceed_label,
        "promedio faltante": panel.required_pace_label,
        "linea enfocada": panel.bet_label,
        "limite para perder": panel.threshold_label,
    }
    for nombre, widget in criticos.items():
        assert widget.width() >= 100, (
            f"'{nombre}' se quedo en {widget.width()} px, ilegible")


def test_la_columna_izquierda_mantiene_su_ancho_util_en_vertical(window_en_vivo):
    win, _controller, qapp = window_en_vivo
    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()

    assert win.metrics_panel.width() >= win.metrics_panel.minimumSizeHint().width()
    assert win.metrics_panel.width() >= 400, (
        f"la columna se quedo en {win.metrics_panel.width()} px")


# ---------------------------------------------------------------------------
# 7. La derecha se comprime sin romperse: sigue teniendo scroll
# ---------------------------------------------------------------------------
def test_el_radar_conserva_su_scroll_interno(window_en_vivo):
    """Al estrecharse, el radar desplaza; no aplasta ni pierde columnas."""
    from PySide6.QtCore import Qt

    win, _controller, qapp = window_en_vivo
    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()

    scroll = win.entry_board.scroll
    assert scroll.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOff, (
        "sin barra horizontal las tablas de mercado se recortarian")
    assert scroll.widgetResizable() is True

    bloques = win.entry_board.blocks()
    assert bloques, "el radar se quedo sin mercados"
    for key, bloque in bloques.items():
        assert bloque.table.columnCount() == 10, (
            f"el mercado {key.label} perdio columnas al estrecharse")


def test_las_columnas_del_radar_no_se_aplastan(window_en_vivo):
    """En modo `Stretch` las diez columnas caian a 26 px: ilegibles.

    Con la ventana estrecha la tabla debe DESPLAZARSE en horizontal, que es lo
    que se pidio, en vez de repartir un ancho que no da para nada.
    """
    win, _controller, qapp = window_en_vivo
    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()

    for key, bloque in win.entry_board.blocks().items():
        cabecera = bloque.table.horizontalHeader()
        assert cabecera.minimumSectionSize() >= 50, (
            f"{key.label}: sin suelo por columna la cabecera se vuelve ilegible")
        for columna in range(bloque.table.columnCount()):
            assert bloque.table.columnWidth(columna) >= 50, (
                f"{key.label}: la columna {columna} quedo en "
                f"{bloque.table.columnWidth(columna)} px")


def test_el_bloque_del_radar_reserva_sitio_para_su_barra_horizontal(window_en_vivo):
    """Si la barra aparece y no se le reserva alto, tapa la ultima linea."""
    win, _controller, qapp = window_en_vivo
    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()

    for key, bloque in win.entry_board.blocks().items():
        tabla = bloque.table
        if tabla.horizontalHeader().length() <= tabla.viewport().width():
            continue          # ahi caben: no hay barra que reservar
        filas = sum(tabla.rowHeight(f) for f in range(tabla.rowCount()))
        barra = tabla.horizontalScrollBar().sizeHint().height()
        assert tabla.height() >= tabla.horizontalHeader().height() + filas + barra, (
            f"{key.label}: la barra horizontal tapa la ultima linea del mercado")


def test_el_radar_sigue_operativo_con_la_ventana_muy_estrecha(window_en_vivo):
    win, _controller, qapp = window_en_vivo
    win.resize(760, 1400)
    win._refresh()
    qapp.processEvents()

    assert win.entry_board.isVisible()
    for boton in (win.entry_board.lock_button, win.entry_board.unlock_button,
                  win.entry_board.auto_button):
        assert boton.isVisible(), "un boton del radar desaparecio"
        assert boton.width() >= boton.minimumSizeHint().width()


# ---------------------------------------------------------------------------
# La fila que se parte: es lo que permite encoger la ventana
# ---------------------------------------------------------------------------
def test_una_fila_flexible_pide_como_minimo_su_elemento_mas_ancho(qapp):
    fila = FlowRow()
    botones = [fila.add(QPushButton(t)) for t in
               ("CONFIGURAR", "CRITERIOS", "INICIAR (F8)", "FINALIZAR PARTIDO")]

    minimo = fila.minimumSizeHint().width()
    mas_ancho = max(b.sizeHint().width() for b in botones)
    suma = sum(b.sizeHint().width() for b in botones)

    assert minimo < suma, "sigue exigiendo la suma de sus elementos"
    assert minimo >= mas_ancho, "el elemento mas ancho tiene que caber entero"


def test_una_fila_flexible_baja_de_linea_sin_recortar_nada(qapp):
    fila = FlowRow()
    botones = [fila.add(QPushButton(t)) for t in
               ("CONFIGURAR", "CRITERIOS", "INICIAR (F8)", "FINALIZAR PARTIDO")]
    fila.add_stretch()
    casilla = fila.add(QCheckBox("Siempre encima"))
    fila.show()

    for ancho in (900, 600, 420, 260, 150):
        fila.resize(ancho, fila.heightForWidth(ancho))
        qapp.processEvents()
        for widget in botones + [casilla]:
            assert widget.width() >= widget.sizeHint().width(), (
                f"a {ancho} px '{widget.text()}' quedo recortado")
            assert widget.x() + widget.width() <= ancho + 1, (
                f"a {ancho} px '{widget.text()}' se sale de la fila")


def test_una_fila_flexible_crece_de_alto_al_estrecharse(qapp):
    fila = FlowRow()
    for texto in ("CONFIGURAR", "CRITERIOS", "INICIAR (F8)", "FINALIZAR PARTIDO"):
        fila.add(QPushButton(texto))

    ancha = fila.heightForWidth(fila.sizeHint().width())
    estrecha = fila.heightForWidth(200)
    assert estrecha > ancha, (
        "al estrechar deberia ocupar mas alto: es la senal de que ha saltado "
        "de linea en vez de recortar")


# ---------------------------------------------------------------------------
# Nada de esto toca los numeros
# ---------------------------------------------------------------------------
def test_el_reparto_no_altera_ningun_calculo(window_en_vivo):
    """El mismo ciclo, medido a dos anchos distintos, da lo mismo."""
    win, controller, qapp = window_en_vivo

    def foto():
        vista = controller.build_view_model(controller.reader.last_snapshot)
        return [(e.line_value, e.points_to_exceed, e.current_pace,
                 e.required_pace, e.signal.label) for e in vista.evaluations]

    win.resize(1600, 1000)
    win._refresh()
    qapp.processEvents()
    ancha = foto()

    win.resize(*PANTALLA_VERTICAL)
    win._refresh()
    qapp.processEvents()
    estrecha = foto()

    assert ancha == estrecha, "el ancho de la ventana cambio los numeros"
    assert ancha, "no habia ninguna linea evaluada que comparar"
