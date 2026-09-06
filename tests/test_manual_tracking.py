"""Seguimiento matematico en vivo de las apuestas manuales.

El ejemplo que manda es el del usuario:

    UNDER 40.5 en el Q4, con 32 puntos anotados en ese cuarto

        margen                   = 8.5
        puntos que todavia caben = 8    -> se acabaria en 40 y el UNDER aguanta
        puntos que cruzan        = 9    -> se acabaria en 41 y la linea cae

Margen y puntos enteros son cosas distintas y estas pruebas lo fijan.
"""

from __future__ import annotations

import math

import pytest

from visorunder.calculations.manual_tracking import (
    ManualBetTracking,
    TrackingStatus,
    margin_to_line,
    projected_scope_points,
    push_points,
    suggested_status,
    tolerable_points,
    track_manual_bet,
    track_manual_bets,
)
from visorunder.domain.game_state import GameState, PeriodPointsTracker
from visorunder.domain.manual_bet import ManualBet, ManualBetStatus
from visorunder.domain.market import MarketKey, Side
from visorunder.domain.rules import FIBA
from visorunder.domain.values import Observed


def _state(period: int, clock: int, score_a: int, score_b: int,
           baselines=None, rules=FIBA) -> GameState:
    """Estado de partido con las lineas base de cada cuarto ya conocidas."""
    tracker = PeriodPointsTracker(rules=rules)
    for periodo, (a, b) in (baselines or {}).items():
        tracker.set_baseline(periodo, a, b)
    state = GameState(rules=rules, tracker=tracker)
    state.period = Observed.confirmed(period)
    state.clock_seconds = Observed.confirmed(clock)
    state.score_a = Observed.confirmed(score_a)
    state.score_b = Observed.confirmed(score_b)
    return state


def _bet(key: MarketKey, side: Side, line: float, odds: float = 1.80,
         sportsbook: str = "BetPlay", stake: float = 0.0) -> ManualBet:
    return ManualBet(sportsbook=sportsbook, event="Equipo A vs Equipo B",
                     key=key, side=side, line=line, odds=odds, stake=stake)


# ---------------------------------------------------------------------------
# Aritmetica pura de la linea
# ---------------------------------------------------------------------------
def test_margen_y_puntos_enteros_no_son_lo_mismo():
    """El caso exacto del enunciado: linea 40.5, 32 puntos anotados."""
    assert margin_to_line(40.5, 32) == pytest.approx(8.5)
    assert tolerable_points(40.5, 32) == 8      # llega a 40 y aguanta
    assert push_points(40.5, 32) is None        # con .5 no hay empate


@pytest.mark.parametrize("line, current, margen, caben, cruzan", [
    (40.5, 32, 8.5, 8, 9),
    (40.5, 40, 0.5, 0, 1),      # el siguiente punto la supera
    (40.5, 41, -0.5, 0, 0),     # ya superada
    (185.5, 150, 35.5, 35, 36),
    (42.5, 32, 10.5, 10, 11),
])
def test_formulas_de_la_linea(line, current, margen, caben, cruzan):
    from visorunder.calculations.metrics import points_to_exceed

    assert margin_to_line(line, current) == pytest.approx(margen)
    assert tolerable_points(line, current) == caben
    assert points_to_exceed(line, current) == cruzan
    # Los puntos que cruzan son siempre uno mas que los que caben, salvo
    # cuando la linea ya esta superada y ambos valen cero.
    if cruzan > 0:
        assert cruzan == caben + 1


def test_lineas_enteras_tienen_zona_de_empate():
    """No se supone que toda linea acabe en .5."""
    assert margin_to_line(40.0, 32) == pytest.approx(8.0)
    assert tolerable_points(40.0, 32) == 8      # terminar en 40 no la supera
    assert push_points(40.0, 32) == 8           # y 40 exacto es empate
    from visorunder.calculations.metrics import points_to_exceed
    assert points_to_exceed(40.0, 32) == 9      # 41 la supera


def test_sin_marcador_no_se_inventa_nada():
    assert margin_to_line(40.5, None) is None
    assert tolerable_points(40.5, None) is None
    assert push_points(40.0, None) is None
    assert projected_scope_points(None, 300, 300) is None
    assert projected_scope_points(32, None, 300) is None
    assert projected_scope_points(32, 300, None) is None


# ---------------------------------------------------------------------------
# 7 / 8. Apuesta manual del Q4, UNDER y OVER
# ---------------------------------------------------------------------------
def test_apuesta_manual_q4_under():
    """Q4 en curso: 32 puntos en el cuarto, quedan 5:00, UNDER 40.5."""
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (74, 60)})
    # El cuarto lleva (90-74) + (74-60) = 16 + 14 = 30 puntos.
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    assert seguimiento.scope_points == 30
    assert seguimiento.margin == pytest.approx(10.5)
    assert seguimiento.tolerable_points == 10
    assert seguimiento.points_to_cross == 11
    assert seguimiento.exceed_threshold == 41
    assert seguimiento.exceeded is False
    assert seguimiento.scope_remaining_seconds == 300


def test_apuesta_manual_q4_under_ejemplo_del_enunciado():
    """32 puntos exactos en el Q4 contra UNDER 40.5."""
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (72, 60)})   # (90-72) + (74-60) = 18 + 14 = 32
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    assert seguimiento.scope_points == 32
    assert seguimiento.margin == pytest.approx(8.5)
    assert seguimiento.tolerable_points == 8
    assert seguimiento.points_to_cross == 9
    assert seguimiento.status in (TrackingStatus.FAVORABLE, TrackingStatus.AT_RISK)
    # Y la frase de detalle distingue las tres cifras sin ambiguedad.
    texto = seguimiento.describe_margin()
    assert "8.5" in texto and "caben 8" in texto and "con 9" in texto


def test_apuesta_manual_q4_over():
    """OVER 40.5 con 32 puntos: necesita 9 puntos para superar la linea."""
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (72, 60)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.OVER, 40.5))

    assert seguimiento.scope_points == 32
    assert seguimiento.points_to_cross == 9
    assert seguimiento.side is Side.OVER
    assert "faltan 9 puntos" in seguimiento.describe_margin()


def test_under_y_over_leen_la_misma_realidad_al_reves():
    """Con la misma linea y el mismo marcador, los estados son opuestos."""
    state = _state(period=4, clock=120, score_a=100, score_b=84,
                   baselines={4: (72, 60)})   # 28 + 24 = 52 puntos en el Q4
    under = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))
    over = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.OVER, 40.5))

    assert under.exceeded is True and over.exceeded is True
    assert under.status is TrackingStatus.EXCEEDED
    assert over.status is TrackingStatus.EXCEEDED
    assert suggested_status(under) is ManualBetStatus.LOST
    assert suggested_status(over) is ManualBetStatus.WON


# ---------------------------------------------------------------------------
# 9. Apuesta manual del partido completo
# ---------------------------------------------------------------------------
def test_apuesta_manual_de_partido():
    state = _state(period=3, clock=400, score_a=78, score_b=72)
    seguimiento = track_manual_bet(state, _bet(MarketKey.game(), Side.UNDER, 185.5))

    assert seguimiento.scope_points == 150          # total del partido
    assert seguimiento.margin == pytest.approx(35.5)
    assert seguimiento.tolerable_points == 35
    assert seguimiento.points_to_cross == 36
    assert seguimiento.market_label == "Partido"
    # El tiempo restante es el del PARTIDO, no el del cuarto.
    assert seguimiento.scope_remaining_seconds == 400 + FIBA.period_seconds(4)


# ---------------------------------------------------------------------------
# 10 / 11. Mitades: 1H usa Q1+Q2 y 2H usa Q3+Q4
# ---------------------------------------------------------------------------
def test_apuesta_manual_primera_mitad_usa_q1_mas_q2():
    # Q1 termino 25-20 (45) y Q2 termino 22-18 (40): la 1H son 85 puntos.
    state = _state(period=3, clock=500, score_a=60, score_b=45,
                   baselines={1: (0, 0), 2: (25, 20), 3: (47, 38)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.half_market(1), Side.UNDER, 90.5))

    assert seguimiento.scope_points == 85           # (47-0) + (38-0)
    assert seguimiento.margin == pytest.approx(5.5)
    assert seguimiento.settled is True, "la 1.a mitad ya termino en el Q3"
    assert seguimiento.scope_remaining_seconds == 0
    assert seguimiento.status is TrackingStatus.WON
    assert suggested_status(seguimiento) is ManualBetStatus.WON


def test_apuesta_manual_segunda_mitad_usa_q3_mas_q4():
    state = _state(period=3, clock=300, score_a=60, score_b=50,
                   baselines={3: (47, 38)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.half_market(2), Side.UNDER, 95.5))

    assert seguimiento.scope_points == 25           # (60-47) + (50-38)
    assert seguimiento.settled is False
    # Queda lo que resta del Q3 mas el Q4 entero.
    assert seguimiento.scope_remaining_seconds == 300 + FIBA.period_seconds(4)


def test_mercado_que_todavia_no_empezo():
    """Una linea del Q4 mientras se juega el Q2 no se evalua como si corriera."""
    state = _state(period=2, clock=400, score_a=40, score_b=35,
                   baselines={2: (22, 18)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    assert seguimiento.started is False
    assert seguimiento.status is TrackingStatus.NOT_STARTED
    assert suggested_status(seguimiento) is None


# ---------------------------------------------------------------------------
# 12. Varias apuestas simultaneas, cada una por su cuenta
# ---------------------------------------------------------------------------
def test_varias_apuestas_simultaneas_no_se_mezclan():
    """El caso del enunciado: dos casas, dos lineas y un mercado de partido."""
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (72, 60)})      # Q4 = 32 ; partido = 164

    apuestas = [
        _bet(MarketKey.quarter(4), Side.UNDER, 40.5, sportsbook="BetPlay"),
        _bet(MarketKey.quarter(4), Side.UNDER, 42.5, sportsbook="Stake"),
        _bet(MarketKey.game(), Side.UNDER, 185.5, sportsbook="BetPlay"),
    ]
    seguimientos = track_manual_bets(state, apuestas)
    assert len(seguimientos) == 3

    betplay_q4, stake_q4, betplay_partido = seguimientos

    # Mismo mercado, casas y lineas distintas: NO comparten margen.
    assert betplay_q4.sportsbook == "BetPlay" and stake_q4.sportsbook == "Stake"
    assert betplay_q4.scope_points == stake_q4.scope_points == 32
    assert betplay_q4.margin == pytest.approx(8.5)
    assert stake_q4.margin == pytest.approx(10.5)
    assert betplay_q4.points_to_cross == 9
    assert stake_q4.points_to_cross == 11

    # Y el mercado de partido usa el total del partido, no el del cuarto.
    assert betplay_partido.scope_points == 164
    assert betplay_partido.margin == pytest.approx(21.5)
    assert betplay_partido.points_to_cross == 22
    assert betplay_partido.key != betplay_q4.key


def test_sin_partido_en_vivo_no_se_inventan_metricas():
    apuestas = [_bet(MarketKey.quarter(4), Side.UNDER, 40.5)]
    seguimientos = track_manual_bets(None, apuestas)

    assert len(seguimientos) == 1
    seguimiento = seguimientos[0]
    assert seguimiento.scope_points is None
    assert seguimiento.margin is None
    assert seguimiento.projection is None
    assert seguimiento.status is TrackingStatus.NO_DATA
    assert seguimiento.unavailable_reason == "SIN PARTIDO EN VIVO"
    # Los datos de la apuesta si siguen ahi.
    assert seguimiento.line == 40.5
    assert seguimiento.market_label == "Q4"


# ---------------------------------------------------------------------------
# 13. Proyeccion y diferencia contra la linea
# ---------------------------------------------------------------------------
def test_proyeccion_y_diferencia_contra_la_linea():
    """32 puntos en 5:00 jugados y 5:00 por jugar -> proyeccion 64."""
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (72, 60)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    assert seguimiento.scope_elapsed_seconds == 300
    assert seguimiento.current_pace == pytest.approx(32 / 5.0)
    assert seguimiento.projection == pytest.approx(64.0)
    assert seguimiento.projection_vs_line == pytest.approx(64.0 - 40.5)
    # La proyeccion se pasa de la linea: el UNDER va en contra.
    assert seguimiento.status is TrackingStatus.AT_RISK


def test_proyeccion_por_debajo_de_la_linea_es_favorable():
    """Ritmo lento: la proyeccion queda del lado del UNDER."""
    state = _state(period=4, clock=120, score_a=82, score_b=70,
                   baselines={4: (72, 60)})   # 10 + 10 = 20 puntos en 8:00
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    assert seguimiento.scope_points == 20
    assert seguimiento.scope_elapsed_seconds == 480
    assert seguimiento.projection == pytest.approx(25.0)
    assert seguimiento.projection_vs_line == pytest.approx(-15.5)
    assert seguimiento.status is TrackingStatus.FAVORABLE


def test_ritmo_necesario_para_cruzar_la_linea():
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (72, 60)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    # Faltan 9 puntos en 5 minutos -> 1.8 puntos por minuto.
    assert seguimiento.required_pace == pytest.approx(9 / 5.0)


def test_reloj_a_cero_hace_imposible_cruzar_pero_no_liquida():
    """El 0:00 del marcador NO cierra el cuarto por si solo.

    Mientras el cuarto en curso no cambia, el dominio no lo da por cerrado:
    el reloj puede estar parado en 0:00 durante una interrupcion. El ritmo
    necesario ya es imposible, pero la apuesta no se marca ganada todavia.
    """
    state = _state(period=4, clock=0, score_a=90, score_b=74,
                   baselines={4: (72, 60)})
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), Side.UNDER, 40.5))

    assert seguimiento.settled is False
    assert math.isinf(seguimiento.required_pace)
    assert suggested_status(seguimiento) is None, (
        "no se liquida sin saber que el mercado termino de verdad")


def test_cuarto_ya_cerrado_se_liquida():
    """Apuesta del Q3 mientras se juega el Q4: ese mercado si termino."""
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={3: (55, 45), 4: (72, 60)})
    # El Q3 termino en (72-55) + (60-45) = 17 + 15 = 32 puntos.
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(3), Side.UNDER, 40.5))

    assert seguimiento.scope_points == 32
    assert seguimiento.settled is True
    assert seguimiento.scope_remaining_seconds == 0
    assert seguimiento.status is TrackingStatus.WON
    assert suggested_status(seguimiento) is ManualBetStatus.WON


def test_empate_exacto_en_linea_entera():
    """Linea entera y el cuarto termina justo en ella: NULA, no ganada."""
    state = _state(period=4, clock=300, score_a=95, score_b=80,
                   baselines={3: (52, 48), 4: (72, 68)})
    # El Q3 termino en (72-52) + (68-48) = 20 + 20 = 40 puntos exactos.
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(3), Side.UNDER, 40.0))

    assert seguimiento.scope_points == 40
    assert seguimiento.settled is True
    assert seguimiento.status is TrackingStatus.PUSH
    assert suggested_status(seguimiento) is ManualBetStatus.VOID


def test_linea_entera_superada_por_un_punto():
    """41 puntos con linea 40.0: superada, no empate."""
    state = _state(period=4, clock=300, score_a=95, score_b=81,
                   baselines={3: (52, 48), 4: (72, 69)})
    # El Q3 termino en (72-52) + (69-48) = 20 + 21 = 41 puntos.
    seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(3), Side.UNDER, 40.0))

    assert seguimiento.scope_points == 41
    assert seguimiento.status is TrackingStatus.LOST
    assert suggested_status(seguimiento) is ManualBetStatus.LOST


# ---------------------------------------------------------------------------
# 14. Actualizacion automatica cuando cambia el marcador
# ---------------------------------------------------------------------------
def test_el_seguimiento_cambia_solo_al_cambiar_el_marcador():
    """32 -> 34 -> 36 -> 39 sin tocar la apuesta."""
    apuesta = _bet(MarketKey.quarter(4), Side.UNDER, 40.5)
    esperado = {
        32: (8.5, 8, 9),
        34: (6.5, 6, 7),
        36: (4.5, 4, 5),
        39: (1.5, 1, 2),
        41: (-0.5, 0, 0),      # superada
    }

    for puntos, (margen, caben, cruzan) in esperado.items():
        state = _state(period=4, clock=300, score_a=72 + puntos, score_b=60,
                       baselines={4: (72, 60)})
        seguimiento = track_manual_bet(state, apuesta)
        assert seguimiento.scope_points == puntos
        assert seguimiento.margin == pytest.approx(margen)
        assert seguimiento.tolerable_points == caben
        assert seguimiento.points_to_cross == cruzan

    # Al superar la linea el estado deja de ser una estimacion.
    state = _state(period=4, clock=300, score_a=113, score_b=60,
                   baselines={4: (72, 60)})
    assert track_manual_bet(state, apuesta).status is TrackingStatus.EXCEEDED


# ---------------------------------------------------------------------------
# El sistema no liquida sin informacion fiable
# ---------------------------------------------------------------------------
def test_no_se_liquida_mientras_el_mercado_sigue_vivo():
    state = _state(period=4, clock=300, score_a=90, score_b=74,
                   baselines={4: (72, 60)})
    for side in (Side.UNDER, Side.OVER):
        seguimiento = track_manual_bet(state, _bet(MarketKey.quarter(4), side, 40.5))
        assert suggested_status(seguimiento) is None, (
            "no se puede proponer resultado con el mercado en juego")


def test_sin_datos_no_se_propone_resultado():
    seguimiento = ManualBetTracking(bet=_bet(MarketKey.game(), Side.UNDER, 185.5))
    assert seguimiento.status is TrackingStatus.NO_DATA
    assert suggested_status(seguimiento) is None
    assert seguimiento.is_live is False
