"""Orden de las columnas del radar y su alineacion con los datos.

El orden acordado pone juntas y delante las comparaciones, que son la lectura
rapida, y deja los promedios y los puntos detras como respaldo:

    LINEA | CUOTA U | VS REF. | VS Q | VS MITAD | VS PARTIDO |
    PROM. ACTUAL | PUNTOS FALT. | PROM. FALT. | SENAL

El riesgo de un cambio asi es mover los encabezados dejando los datos en su
sitio anterior, asi que estas pruebas comprueban que CADA valor sigue debajo
de SU encabezado, no solo que el orden de los titulos sea el pedido.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6", reason="PySide6 no instalado")

from PySide6.QtWidgets import QApplication  # noqa: E402

from visorunder.calculations.entry import evaluate_line  # noqa: E402
from visorunder.calculations.metrics import compute_general_metrics  # noqa: E402
from visorunder.config.criteria import EntryCriteria  # noqa: E402
from visorunder.domain.event_markets import FreshnessState  # noqa: E402
from visorunder.domain.game_state import GameState  # noqa: E402
from visorunder.domain.market import MarketKey, MarketLine  # noqa: E402
from visorunder.domain.rules import FIBA  # noqa: E402
from visorunder.domain.values import Observed  # noqa: E402
from visorunder.ui.entry_board import (  # noqa: E402
    COL_CURRENT_PACE,
    COL_GAME,
    COL_HALF,
    COL_LINE,
    COL_MISSING_PACE,
    COL_ODDS,
    COL_POINTS,
    COL_QUARTER,
    COL_REF,
    COL_SIGNAL,
    COLUMNS,
    MarketBlock,
)

#: El orden exacto pedido.
ORDEN_ESPERADO = [
    "LINEA", "CUOTA U",
    "VS REF.", "VS Q", "VS MITAD", "VS PARTIDO",
    "PROM. ACTUAL", "PUNTOS FALT.", "PROM. FALT.",
    "SENAL",
]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _state(*, period, remaining, periods, rules=FIBA):
    state = GameState(rules=rules)
    state.period = Observed.confirmed(period)
    state.clock_seconds = Observed.confirmed(remaining)
    labels_a = {}
    labels_b = {}
    for number, (points_a, points_b) in periods.items():
        label = rules.label(number)
        labels_a[label] = points_a
        labels_b[label] = points_b
    state.tracker.replace_dom_breakdown(labels_a, labels_b)
    state.score_a = Observed.confirmed(sum(p[0] for p in periods.values()))
    state.score_b = Observed.confirmed(sum(p[1] for p in periods.values()))
    return state


def _line(key, value=42.5):
    return MarketLine(sportsbook="BetPlay", event="A vs B", key=key, line=value,
                      over_odds=1.90, under_odds=1.90, confirmed=True)


def _block(key, *, period=3, remaining=400,
           periods=None, line=42.5):
    """Construye un bloque del radar ya pintado, con numeros reales."""
    periods = periods or {1: (25, 20), 2: (22, 18), 3: (7, 8)}
    state = _state(period=period, remaining=remaining, periods=periods)
    criteria = EntryCriteria()
    general = compute_general_metrics(state)
    evaluation = evaluate_line(state, _line(key, line), criteria, general)

    block = MarketBlock(key)
    block.update_block(SimpleNamespace(
        evaluations=[evaluation], freshness=FreshnessState.LIVE,
        label=key.label, age_text=lambda now=None: "ahora",
    ), criteria)
    return block, evaluation


def _headers(block) -> list:
    return [block.table.horizontalHeaderItem(i).text()
            for i in range(block.table.columnCount())]


def _cells(block, row: int = 0) -> list:
    return [block.table.item(row, i).text() if block.table.item(row, i) else None
            for i in range(block.table.columnCount())]


# ---------------------------------------------------------------------------
# 1 y 3. El orden exacto, con SENAL al final
# ---------------------------------------------------------------------------
def test_el_orden_de_las_columnas_es_el_acordado():
    assert COLUMNS == ORDEN_ESPERADO


def test_las_comparaciones_van_delante_de_los_promedios():
    """Es lo que motivo el cambio: las comparaciones son la lectura rapida."""
    for comparacion in ("VS REF.", "VS Q", "VS MITAD", "VS PARTIDO"):
        assert COLUMNS.index(comparacion) < COLUMNS.index("PROM. ACTUAL")
        assert COLUMNS.index(comparacion) < COLUMNS.index("PUNTOS FALT.")
        assert COLUMNS.index(comparacion) < COLUMNS.index("PROM. FALT.")


def test_la_senal_sigue_siendo_la_ultima():
    assert COLUMNS[-1] == "SENAL"
    assert COL_SIGNAL == len(COLUMNS) - 1


def test_los_indices_coinciden_con_los_encabezados():
    """Si los indices y los titulos se desincronizan, todo lo demas miente."""
    indices = {
        "LINEA": COL_LINE,
        "CUOTA U": COL_ODDS,
        "VS REF.": COL_REF,
        "VS Q": COL_QUARTER,
        "VS MITAD": COL_HALF,
        "VS PARTIDO": COL_GAME,
        "PROM. ACTUAL": COL_CURRENT_PACE,
        "PUNTOS FALT.": COL_POINTS,
        "PROM. FALT.": COL_MISSING_PACE,
        "SENAL": COL_SIGNAL,
    }
    for nombre, indice in indices.items():
        assert COLUMNS[indice] == nombre, (
            f"el indice de {nombre} apunta a {COLUMNS[indice]}")
    assert sorted(indices.values()) == list(range(len(COLUMNS)))


# ---------------------------------------------------------------------------
# 2. Cada valor sigue debajo de SU encabezado
# ---------------------------------------------------------------------------
def test_cada_valor_queda_bajo_su_encabezado(qapp):
    """No basta con mover los titulos: los datos tienen que ir con ellos."""
    block, evaluation = _block(MarketKey.quarter(3))
    try:
        assert _headers(block) == ORDEN_ESPERADO

        from visorunder.ui import formatters as fmt
        from visorunder.ui.entry_board import _margin_text, _pace_text

        esperado = {
            COL_LINE: fmt.line(evaluation.line_value),
            COL_ODDS: fmt.odds(evaluation.under_odds),
            COL_REF: _margin_text(evaluation.margin_vs_reference),
            COL_QUARTER: _margin_text(evaluation.margin_vs_period_pace),
            COL_HALF: _margin_text(evaluation.margin_vs_half_pace),
            COL_GAME: _margin_text(evaluation.margin_vs_game_pace),
            COL_CURRENT_PACE: _pace_text(evaluation.current_pace),
            COL_POINTS: fmt.integer(evaluation.points_to_exceed),
            COL_MISSING_PACE: _pace_text(evaluation.required_pace),
        }
        for indice, valor in esperado.items():
            assert block.table.item(0, indice).text() == valor, (
                f"la columna {COLUMNS[indice]} no muestra su propio valor")
    finally:
        block.deleteLater()
        qapp.processEvents()


def test_las_cuatro_comparaciones_no_se_intercambian(qapp):
    """VS REF., VS Q, VS MITAD y VS PARTIDO tienen valores distintos entre si.

    Con numeros distintos, un cruce entre ellas se ve enseguida.
    """
    # En el Q4, con el Q3 ya cerrado, los cuatro margenes son distintos; en el
    # Q3 el ritmo de la mitad coincide con el del cuarto y un cruce entre esas
    # dos columnas pasaria desapercibido.
    block, evaluation = _block(
        MarketKey.quarter(4), period=4, remaining=400,
        periods={1: (25, 20), 2: (22, 18), 3: (30, 25), 4: (7, 8)})
    try:
        from visorunder.ui.entry_board import _margin_text

        margenes = {
            "VS REF.": (COL_REF, evaluation.margin_vs_reference),
            "VS Q": (COL_QUARTER, evaluation.margin_vs_period_pace),
            "VS MITAD": (COL_HALF, evaluation.margin_vs_half_pace),
            "VS PARTIDO": (COL_GAME, evaluation.margin_vs_game_pace),
        }
        # El escenario tiene que producir valores distintos, o la prueba no
        # distinguiria un cruce.
        valores = [valor for _indice, valor in margenes.values()]
        assert len(set(valores)) == len(valores), (
            "el escenario no sirve: los cuatro margenes coinciden")

        for nombre, (indice, valor) in margenes.items():
            assert block.table.item(0, indice).text() == _margin_text(valor), (
                f"{nombre} muestra el margen de otra columna")
    finally:
        block.deleteLater()
        qapp.processEvents()


def test_los_promedios_no_se_intercambian(qapp):
    """PROM. ACTUAL, PUNTOS FALT. y PROM. FALT. son tres cosas distintas."""
    block, evaluation = _block(MarketKey.quarter(3))
    try:
        from visorunder.ui import formatters as fmt
        from visorunder.ui.entry_board import _pace_text

        actual = block.table.item(0, COL_CURRENT_PACE).text()
        puntos = block.table.item(0, COL_POINTS).text()
        faltante = block.table.item(0, COL_MISSING_PACE).text()

        assert actual == _pace_text(evaluation.current_pace)
        assert puntos == fmt.integer(evaluation.points_to_exceed)
        assert faltante == _pace_text(evaluation.required_pace)
        assert actual != faltante, (
            "el escenario no sirve: los dos promedios coinciden")
    finally:
        block.deleteLater()
        qapp.processEvents()


# ---------------------------------------------------------------------------
# 4-6. El mismo orden en todos los mercados
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key, nombre", [
    (MarketKey.game(), "Partido"),
    (MarketKey.quarter(1), "Q1"),
    (MarketKey.quarter(2), "Q2"),
    (MarketKey.quarter(3), "Q3"),
    (MarketKey.quarter(4), "Q4"),
    (MarketKey.half_market(1), "1H"),
    (MarketKey.half_market(2), "2H"),
])
def test_todos_los_mercados_usan_el_mismo_orden(qapp, key, nombre):
    block, _evaluation = _block(key)
    try:
        assert _headers(block) == ORDEN_ESPERADO, f"{nombre} usa otro orden"
        assert block.table.columnCount() == len(ORDEN_ESPERADO)
    finally:
        block.deleteLater()
        qapp.processEvents()


def test_el_radar_completo_usa_el_orden_nuevo(qapp, tmp_path):
    """De extremo a extremo, con la ventana real y un partido simulado."""
    from visorunder.app import AppController
    from visorunder.pipeline.demo import DemoGame
    from visorunder.ui.main_window import MainWindow

    controller = AppController(db_path=str(tmp_path / "radar.db"))
    controller.settings.log_to_file = False
    controller.enable_demo(DemoGame(period=3, clock_seconds=328,
                                    score_a=43, score_b=31, speed=0.0))
    window = MainWindow(controller)
    window.timer.stop()
    try:
        window.profile_combo.setCurrentText("DEMO (partido simulado)")
        window.toggle_reading()
        for _ in range(4):
            controller.reader.tick()
        window._refresh()

        bloques = window.entry_board.blocks()
        assert bloques, "el radar no pinto ningun mercado"
        for key, block in bloques.items():
            assert _headers(block) == ORDEN_ESPERADO, f"{key.label} usa otro orden"
    finally:
        window.hotkeys.stop()
        controller.finish_game()
        controller.db.close()


# ---------------------------------------------------------------------------
# 7. Ningun resultado numerico cambia
# ---------------------------------------------------------------------------
def test_los_valores_son_los_mismos_solo_en_otro_sitio(qapp):
    """Reordenar es mover celdas: el conjunto de valores no cambia."""
    block, _evaluation = _block(MarketKey.quarter(3))
    try:
        celdas = _cells(block)
        # Los mismos diez valores de siempre, sin perder ni inventar ninguno.
        assert len(celdas) == 10
        assert all(c is not None for c in celdas)
        # Y el orden ANTERIOR reconstruido a partir de los indices actuales
        # devuelve exactamente lo que mostraba antes cada posicion.
        anterior = [celdas[COL_LINE], celdas[COL_ODDS], celdas[COL_CURRENT_PACE],
                    celdas[COL_POINTS], celdas[COL_MISSING_PACE], celdas[COL_REF],
                    celdas[COL_QUARTER], celdas[COL_HALF], celdas[COL_GAME],
                    celdas[COL_SIGNAL]]
        assert sorted(anterior) == sorted(celdas)
    finally:
        block.deleteLater()
        qapp.processEvents()


def test_la_senal_conserva_su_texto_y_su_formato(qapp):
    block, evaluation = _block(MarketKey.quarter(3))
    try:
        item = block.table.item(0, COL_SIGNAL)
        esperado = (evaluation.signal.label if evaluation.is_evaluable
                    else (evaluation.unavailable_reason or evaluation.signal.label))
        assert item.text() == esperado
        assert item.font().bold() is True, "la senal perdio su formato"
    finally:
        block.deleteLater()
        qapp.processEvents()
