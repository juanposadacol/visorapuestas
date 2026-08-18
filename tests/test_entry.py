"""Motor de deteccion de entrada: los ejemplos numericos acordados.

Se comprueban tal cual los tres escenarios que definiste (4.20, 5.75 y 2.75)
mas la tabla de cuatro lineas simultaneas.
"""

import math

import pytest

from visorunder.calculations.entry import (
    LineEvaluation,
    choose_focus,
    evaluate_line,
    evaluate_market,
)
from visorunder.calculations.metrics import compute_general_metrics
from visorunder.calculations.signals import SignalLevel, classify, is_final_stretch
from visorunder.config.criteria import EntryCriteria
from visorunder.domain.game_state import GameState, PointsSource
from visorunder.domain.market import MarketKey, MarketLine, MarketSnapshot
from visorunder.domain.rules import FIBA
from visorunder.domain.values import Observed


def _state(*, period=3, clock=300, score_a=43, score_b=31, baseline=None):
    s = GameState(rules=FIBA)
    s.period = Observed.confirmed(period)
    s.clock_seconds = Observed.confirmed(clock)
    s.score_a = Observed.confirmed(score_a)
    s.score_b = Observed.confirmed(score_b)
    if baseline is not None:
        s.tracker.set_manual_baseline(period, *baseline)
    return s


def _line(value, under=1.87, over=1.85, period=3):
    return MarketLine(sportsbook="Sportium", event="A vs B",
                      key=MarketKey.quarter(period), line=value,
                      over_odds=over, under_odds=under)


def _quarter_state(points_in_quarter: int, clock_seconds: int):
    """Estado con exactamente `points_in_quarter` puntos anotados en el Q3."""
    base_a, base_b = 30, 25
    extra_a = points_in_quarter // 2
    extra_b = points_in_quarter - extra_a
    return _state(period=3, clock=clock_seconds,
                  score_a=base_a + extra_a, score_b=base_b + extra_b,
                  baseline=(base_a, base_b))


# --------------------------------------------------- ejemplos del enunciado
def test_ejemplo_1_ritmo_necesario_4_20():
    """Q3, 20 puntos, quedan 05:00, UNDER 40.5 -> faltan 21, ritmo 4.20."""
    state = _quarter_state(20, 300)
    criteria = EntryCriteria(reference_pace=4.00)
    e = evaluate_line(state, _line(40.5), criteria)

    assert e.scope_points == 20
    assert e.exceed_threshold == 41
    assert e.points_to_exceed == 21
    assert e.required_pace == pytest.approx(4.20, abs=0.001)
    assert e.margin_vs_reference == pytest.approx(0.20, abs=0.001)


def test_ejemplo_2_ritmo_necesario_5_75():
    """Q3, 18 puntos, quedan 04:00, UNDER 40.5 -> faltan 23, ritmo 5.75."""
    state = _quarter_state(18, 240)
    criteria = EntryCriteria(reference_pace=4.00)
    e = evaluate_line(state, _line(40.5), criteria)

    assert e.points_to_exceed == 23
    assert e.required_pace == pytest.approx(5.75, abs=0.001)
    assert e.margin_vs_reference == pytest.approx(1.75, abs=0.001)
    assert e.signal is SignalLevel.MUY_EXIGENTE


def test_ejemplo_3_ritmo_necesario_2_75():
    """Q3, 30 puntos, quedan 04:00, UNDER 40.5 -> faltan 11, ritmo 2.75."""
    state = _quarter_state(30, 240)
    criteria = EntryCriteria(reference_pace=4.00)
    e = evaluate_line(state, _line(40.5), criteria)

    assert e.points_to_exceed == 11
    assert e.required_pace == pytest.approx(2.75, abs=0.001)
    assert e.margin_vs_reference == pytest.approx(-1.25, abs=0.001)
    assert e.signal is SignalLevel.PELIGROSO


# ------------------------------------------------------------ comparaciones
def test_margenes_contra_los_ritmos_reales():
    """Q3, 18 puntos en 06:00 jugados, quedan 04:00."""
    state = _quarter_state(18, 240)
    general = compute_general_metrics(state)
    criteria = EntryCriteria(reference_pace=4.00)
    e = evaluate_line(state, _line(40.5), criteria, general)

    # promedio del cuarto = 18 puntos / 6 minutos jugados = 3.00
    assert general.period_pace == pytest.approx(3.00, abs=0.001)
    assert e.margin_vs_period_pace == pytest.approx(5.75 - 3.00, abs=0.001)
    assert e.margin_vs_game_pace == pytest.approx(5.75 - general.game_pace, abs=1e-6)


def test_sin_promedios_confirmados_los_margenes_son_none():
    state = _quarter_state(18, 240)
    criteria = EntryCriteria()
    e = evaluate_line(state, _line(40.5), criteria, general=None)
    assert e.margin_vs_reference is not None
    assert e.margin_vs_period_pace is None
    assert e.margin_vs_game_pace is None


# ------------------------------------------------- varias lineas a la vez
def test_todas_las_lineas_se_evaluan_simultaneamente():
    state = _quarter_state(20, 240)   # 20 puntos, quedan 4 minutos
    criteria = EntryCriteria(reference_pace=4.00)
    snapshot = MarketSnapshot(key=MarketKey.quarter(3), lines=[
        _line(37.5, under=2.20), _line(38.5, under=2.05),
        _line(39.5, under=1.90), _line(40.5, under=1.75),
    ])
    evaluations = evaluate_market(state, snapshot, criteria)
    assert [e.line_value for e in evaluations] == [37.5, 38.5, 39.5, 40.5]

    esperado = {37.5: (18, 4.50), 38.5: (19, 4.75), 39.5: (20, 5.00), 40.5: (21, 5.25)}
    for e in evaluations:
        faltan, ritmo = esperado[e.line_value]
        assert e.points_to_exceed == faltan
        assert e.required_pace == pytest.approx(ritmo, abs=0.001)
        assert e.margin_vs_reference == pytest.approx(ritmo - 4.00, abs=0.001)


def test_mercado_vacio_no_produce_evaluaciones():
    assert evaluate_market(_quarter_state(20, 240), None, EntryCriteria()) == []
    assert evaluate_market(_quarter_state(20, 240), MarketSnapshot(), EntryCriteria()) == []


# ------------------------------------------------------------- no evaluable
def test_sin_marcador_inicial_la_linea_del_cuarto_no_es_evaluable():
    """Requisito acordado: NO EVALUABLE con motivo, nunca una senal parcial."""
    state = _state(period=3, clock=300, baseline=None)
    e = evaluate_line(state, _line(40.5), EntryCriteria())
    assert e.signal is SignalLevel.NO_EVALUABLE
    assert e.unavailable_reason == "FALTA MARCADOR INICIAL Q3"
    assert e.points_to_exceed is None
    assert e.required_pace is None
    assert e.margin_vs_reference is None


def test_el_mercado_de_partido_sigue_operativo_sin_marcador_inicial():
    """El bloqueo es POR LINEA, no global."""
    state = _state(period=3, clock=300, score_a=60, score_b=56, baseline=None)
    criteria = EntryCriteria()
    game_line = MarketLine(sportsbook="S", event="A vs B", key=MarketKey.game(),
                           line=153.5, over_odds=1.85, under_odds=1.80)
    quarter = evaluate_line(state, _line(40.5), criteria)
    game = evaluate_line(state, game_line, criteria)

    assert quarter.signal is SignalLevel.NO_EVALUABLE
    assert game.signal.is_evaluable
    assert game.scope_points == 116
    assert game.points_to_exceed == 38


def test_linea_en_revision_no_produce_senal():
    state = _quarter_state(20, 300)
    e = evaluate_line(state, _line(40.5), EntryCriteria(), under_review=True)
    assert e.under_review is True
    assert e.signal is SignalLevel.NO_EVALUABLE
    assert e.unavailable_reason == "LINEA EN REVISION"
    # los numeros si se calculan: lo que no se publica es la senal
    assert e.required_pace is not None


# ----------------------------------------- sin heuristicas ocultas (punto 3)
def test_el_tramo_final_no_altera_la_matematica():
    """5 puntos en 00:30 -> 10 pts/min, margen +6, MUY EXIGENTE tal cual."""
    state = _quarter_state(36, 30)   # faltan 5 para llegar a 41
    criteria = EntryCriteria(reference_pace=4.00)
    e = evaluate_line(state, _line(40.5), criteria)

    assert e.points_to_exceed == 5
    assert e.required_pace == pytest.approx(10.0, abs=0.001)
    assert e.margin_vs_reference == pytest.approx(6.0, abs=0.001)
    assert e.signal is SignalLevel.MUY_EXIGENTE   # no se degrada por el tiempo
    assert e.final_stretch is True                # solo se informa aparte


def test_el_indicador_de_tramo_final_es_configurable_y_desactivable():
    criteria = EntryCriteria(final_stretch_seconds=60)
    assert is_final_stretch(30, criteria) is True
    assert is_final_stretch(90, criteria) is False
    criteria.show_final_stretch = False
    assert is_final_stretch(30, criteria) is False


def test_sin_tiempo_restante_superar_la_linea_es_imposible():
    state = _quarter_state(20, 0)
    e = evaluate_line(state, _line(40.5), EntryCriteria())
    assert math.isinf(e.required_pace)
    assert e.signal is SignalLevel.MUY_EXIGENTE


def test_linea_ya_superada():
    state = _quarter_state(45, 240)
    e = evaluate_line(state, _line(40.5), EntryCriteria())
    assert e.exceeded is True
    assert e.points_to_exceed == 0
    assert e.required_pace == 0.0
    assert e.signal is SignalLevel.PELIGROSO


# ------------------------------------------------ enfoque por cuota objetivo
def _eval_set(state, criteria, pares):
    snapshot = MarketSnapshot(key=MarketKey.quarter(3),
                              lines=[_line(v, under=o) for v, o in pares])
    return evaluate_market(state, snapshot, criteria)


def test_enfoque_por_cuota_objetivo():
    """Cuota objetivo 1.80 sobre 2.10/1.94/1.81/1.65 -> enfoca 40.5 @ 1.81."""
    state = _quarter_state(20, 240)
    criteria = EntryCriteria(target_under_odds=1.80)
    evaluations = _eval_set(state, criteria,
                            [(38.5, 2.10), (39.5, 1.94), (40.5, 1.81), (41.5, 1.65)])
    foco = choose_focus(evaluations, criteria)
    assert foco.line_value == 40.5
    assert foco.under_odds == 1.81
    # y siguen visibles todas
    assert len(evaluations) == 4


def test_el_enfoque_no_es_el_de_mayor_margen():
    state = _quarter_state(20, 240)
    criteria = EntryCriteria(target_under_odds=1.80)
    evaluations = _eval_set(state, criteria,
                            [(38.5, 2.10), (39.5, 1.94), (40.5, 1.81), (41.5, 1.65)])
    mayor_margen = max(evaluations, key=lambda e: e.margin_vs_reference)
    foco = choose_focus(evaluations, criteria)
    assert mayor_margen.line_value == 41.5      # la linea mas alta exige mas
    assert foco.line_value == 40.5              # pero se enfoca por cuota


def test_la_seleccion_manual_manda_sobre_el_enfoque_automatico():
    state = _quarter_state(20, 240)
    criteria = EntryCriteria(target_under_odds=1.80)
    evaluations = _eval_set(state, criteria,
                            [(38.5, 2.10), (39.5, 1.94), (40.5, 1.81), (41.5, 1.65)])
    foco = choose_focus(evaluations, criteria, manual_line=38.5)
    assert foco.line_value == 38.5


def test_cambiar_la_cuota_objetivo_cambia_el_enfoque():
    state = _quarter_state(20, 240)
    evaluations = _eval_set(state, EntryCriteria(),
                            [(38.5, 2.10), (39.5, 1.94), (40.5, 1.81), (41.5, 1.65)])
    assert choose_focus(evaluations, EntryCriteria(target_under_odds=2.05)).line_value == 38.5
    assert choose_focus(evaluations, EntryCriteria(target_under_odds=1.60)).line_value == 41.5


def test_enfoque_sin_cuotas_legibles():
    state = _quarter_state(20, 240)
    snapshot = MarketSnapshot(key=MarketKey.quarter(3), lines=[
        MarketLine("S", "A vs B", MarketKey.quarter(3), 40.5, None, None)])
    evaluations = evaluate_market(state, snapshot, EntryCriteria())
    assert choose_focus(evaluations, EntryCriteria()).line_value == 40.5


def test_sin_lineas_no_hay_foco():
    assert choose_focus([], EntryCriteria()) is None


# ------------------------------------------------------------ clasificacion
@pytest.mark.parametrize("margin,esperado", [
    (1.75, SignalLevel.MUY_EXIGENTE),
    (1.00, SignalLevel.MUY_EXIGENTE),
    (0.50, SignalLevel.EXIGENTE),
    (0.20, SignalLevel.NEUTRO),
    (-0.30, SignalLevel.NEUTRO),
    (-1.25, SignalLevel.PELIGROSO),
    (None, SignalLevel.NO_EVALUABLE),
])
def test_escala_de_senal(margin, esperado):
    assert classify(margin, EntryCriteria()) is esperado


def test_umbrales_configurables_cambian_la_senal():
    exigente = EntryCriteria(threshold_very_demanding=0.10, threshold_demanding=0.05,
                             threshold_neutral=0.0)
    assert classify(0.20, exigente) is SignalLevel.MUY_EXIGENTE
    assert classify(0.20, EntryCriteria()) is SignalLevel.NEUTRO


def test_toda_senal_tiene_etiqueta_textual():
    for level in SignalLevel:
        assert level.label
        assert level.explanation


# ------------------------------------------- mercados de mitad y de partido
def _fiba_state(period, clock, score_a, score_b, baselines=None):
    s = GameState(rules=FIBA)
    s.period = Observed.confirmed(period)
    s.clock_seconds = Observed.confirmed(clock)
    s.score_a = Observed.confirmed(score_a)
    s.score_b = Observed.confirmed(score_b)
    for p, (a, b) in (baselines or {}).items():
        s.tracker.set_manual_baseline(p, a, b)
    return s


def _market_line(key, value, under=1.85, over=1.90):
    return MarketLine(sportsbook="BetPlay", event="A vs B", key=key,
                      line=value, over_odds=over, under_odds=under)


def test_caso_f_primera_mitad():
    """1H: 02:00 jugados, 10 puntos, UNDER 79.5 -> faltan 70, 18:00, 3.8889."""
    state = _fiba_state(1, 480, 6, 4, {1: (0, 0)})
    e = evaluate_line(state, _market_line(MarketKey.half_market(1), 79.5), EntryCriteria())
    assert e.scope_points == 10
    assert e.exceed_threshold == 80
    assert e.points_to_exceed == 70
    assert e.scope_remaining_seconds == 18 * 60
    assert e.required_pace == pytest.approx(3.8889, abs=0.0001)


def test_caso_g_partido_completo():
    """Partido: 22:00 jugados, 100 puntos, UNDER 179.5 -> 80, 18:00, 4.4444."""
    state = _fiba_state(3, 480, 52, 48)
    e = evaluate_line(state, _market_line(MarketKey.game(), 179.5), EntryCriteria())
    assert state.elapsed_game_seconds == 22 * 60
    assert e.scope_points == 100
    assert e.exceed_threshold == 180
    assert e.points_to_exceed == 80
    assert e.scope_remaining_seconds == 18 * 60
    assert e.required_pace == pytest.approx(4.4444, abs=0.0001)


def test_caso_h_segunda_mitad_desde_q3():
    """2H = Q3 + Q4. Con 04:00 jugados del Q3 quedan 6:00 + 10:00."""
    state = _fiba_state(3, 360, 55, 48, {3: (50, 44)})
    general = compute_general_metrics(state)
    e = evaluate_line(state, _market_line(MarketKey.half_market(2), 39.5),
                      EntryCriteria(reference_pace=4.00), general)

    assert e.scope_points == 9                       # (55-50) + (48-44)
    assert e.scope_remaining_seconds == 16 * 60      # 06:00 del Q3 + 10:00 del Q4
    assert e.points_to_exceed == 31                  # 40 - 9
    assert e.required_pace == pytest.approx(31 / 16, abs=1e-6)
    assert general.half_number == 2
    assert general.half_pace == pytest.approx(9 / 4, abs=1e-6)
    assert e.margin_vs_half_pace == pytest.approx(31 / 16 - 9 / 4, abs=1e-6)


def test_segunda_mitad_desde_q4_solo_cuenta_el_cuarto_actual():
    state = _fiba_state(4, 300, 70, 62, {3: (50, 44), 4: (62, 55)})
    e = evaluate_line(state, _market_line(MarketKey.half_market(2), 39.5), EntryCriteria())
    assert e.scope_remaining_seconds == 300          # solo lo que queda del Q4
    assert e.scope_points == (70 - 50) + (62 - 44)


def test_segunda_mitad_sin_marcador_inicial_no_es_evaluable():
    state = _fiba_state(3, 360, 55, 48)   # sin baseline del Q3
    e = evaluate_line(state, _market_line(MarketKey.half_market(2), 79.5), EntryCriteria())
    assert e.signal is SignalLevel.NO_EVALUABLE
    assert e.unavailable_reason == "FALTA MARCADOR INICIAL 2H"
    assert e.points_to_exceed is None


def test_caso_a_partido_evaluable_y_cuarto_no_evaluable_a_la_vez():
    """GAME actualizado y Q3 sin marcador inicial conviven correctamente."""
    state = _fiba_state(3, 480, 52, 48)
    criteria = EntryCriteria()
    juego = evaluate_line(state, _market_line(MarketKey.game(), 179.5), criteria)
    cuarto = evaluate_line(state, _market_line(MarketKey.quarter(3), 40.5), criteria)

    assert juego.signal.is_evaluable
    assert juego.points_to_exceed == 80
    assert cuarto.signal is SignalLevel.NO_EVALUABLE
    assert cuarto.unavailable_reason == "FALTA MARCADOR INICIAL Q3"


def test_los_cuatro_margenes_conviven():
    state = _fiba_state(3, 360, 55, 48, {3: (50, 44)})
    general = compute_general_metrics(state)
    e = evaluate_line(state, _market_line(MarketKey.game(), 179.5),
                      EntryCriteria(reference_pace=4.00), general)
    assert e.margin_vs_reference is not None
    assert e.margin_vs_period_pace is not None
    assert e.margin_vs_half_pace is not None
    assert e.margin_vs_game_pace is not None
    # cada margen se mide contra su propio ritmo
    assert e.margin_vs_reference == pytest.approx(e.required_pace - 4.00, abs=1e-9)
    assert e.margin_vs_half_pace == pytest.approx(e.required_pace - general.half_pace, abs=1e-9)


def test_en_prorroga_no_hay_mitad_en_curso():
    state = _fiba_state(5, 120, 90, 88, {5: (88, 86)})
    general = compute_general_metrics(state)
    assert general.half_number is None
    assert general.half_pace is None
    e = evaluate_line(state, _market_line(MarketKey.quarter(5), 20.5),
                      EntryCriteria(), general)
    assert e.margin_vs_half_pace is None          # no se inventa
    assert e.margin_vs_reference is not None      # el resto sigue funcionando
