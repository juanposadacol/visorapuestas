"""Un solo perfil de Stake que aguanta el partido entero.

El tablero de Stake cambia de columnas durante el juego. Estas pruebas
recorren el pipeline COMPLETO -- region -> OCR -> parser -> estabilizador ->
GameState -> seguimiento de apuestas manuales -- comprobando que la misma
region sirve del Q1 al Q4 sin volver a configurar nada.
"""

from __future__ import annotations

import pytest

from visorunder.calculations import manual_tracking
from visorunder.capture.roi import Rect, RoiKind
from visorunder.capture.roi_manager import RoiManager
from visorunder.capture.screen_capture import NullCapture
from visorunder.config.profiles import SportsbookProfile
from visorunder.diagnostics.logbus import LogBus
from visorunder.domain.game_state import GamePhase, PointsSource
from visorunder.domain.manual_bet import ManualBet
from visorunder.domain.market import MarketKey, Side
from visorunder.ocr.engines.stub_engine import StubEngine
from visorunder.pipeline.reader import LiveReader


# --------------------------------------------------------------------------
# Tableros reales de Stake, uno por fase del partido
# --------------------------------------------------------------------------
Q1 = """1 cuarto • 07:12
1  Puntos
Taiwan Beer Leopards  14  14
Shiga Lake Stars  11  11"""

Q2 = """2 cuarto • 04:31
1  2  Medio tiempo  Puntos
Taiwan Beer Leopards  28  10  38  38
Shiga Lake Stars  18  12  30  30"""

DESCANSO = """Medio tiempo
1  2  Medio tiempo  Puntos
Taiwan Beer Leopards  28  17  45  45
Shiga Lake Stars  18  23  41  41"""

Q3_INICIO = """3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  45  0  45
Shiga Lake Stars  18  23  41  0  41"""

Q3_AVANZADO = """3 cuarto • 06:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  45  8  53
Shiga Lake Stars  18  23  41  6  47"""

Q4 = """4 cuarto • 09:02
1  2  Medio tiempo  3  4  Puntos
Taiwan Beer Leopards  28  17  45  22  3  70
Shiga Lake Stars  18  23  41  19  5  65"""


def _stake_profile() -> SportsbookProfile:
    """El perfil que pidio el usuario: UNA region para todo el tablero."""
    profile = SportsbookProfile(name="Stake principal", sportsbook="Stake",
                                frame=Rect(0, 0, 1920, 1080))
    profile.set_roi(RoiKind.SCOREBOARD, Rect(300, 80, 900, 180))
    profile.set_roi(RoiKind.MARKET_BLOCK, Rect(1200, 350, 400, 300))
    return profile


@pytest.fixture()
def rig():
    profile = _stake_profile()
    engine = StubEngine()
    manager = RoiManager(profile, NullCapture(), use_anchor=False)
    reader = LiveReader(manager, engine, logbus=LogBus(), required_confirmations=2,
                        sportsbook="Stake", event_name="Taiwan vs Shiga")
    return reader, engine


#: Un salto de marcador mayor que unos pocos puntos es sospechoso para el
#: estabilizador y exige mas confirmaciones. Al saltar de un cuarto a otro en
#: estas pruebas el marcador avanza de golpe, asi que se insiste lo suficiente.
#: No se desactiva la estabilizacion: se cumple.
SALTO = 6


def _feed(reader, engine, tablero: str, times: int = 3):
    engine.set_text("SCOREBOARD", tablero)
    snapshot = None
    for _ in range(times):
        snapshot = reader.tick()
    return snapshot


# --------------------------------------------------------------------------
# 16-19. El tablero alimenta el GameState normal
# --------------------------------------------------------------------------
def test_el_tablero_llena_marcador_cuarto_y_reloj(rig):
    reader, engine = rig
    snap = _feed(reader, engine, Q3_INICIO)

    assert snap.state.period_value == 3
    assert snap.state.clock_value == 600
    assert (snap.state.score_a_value, snap.state.score_b_value) == (45, 41)
    assert snap.state.total_points == 86


def test_los_parciales_llegan_al_gamestate(rig):
    reader, engine = rig
    snap = _feed(reader, engine, Q3_INICIO)

    assert snap.state.period_score(1).total == 46      # 28 + 18
    assert snap.state.period_score(2).total == 40      # 17 + 23
    assert snap.state.period_score(3).total == 0
    # Y vienen del desglose de la casa, no de un baseline inferido.
    assert snap.state.period_score(1).source is PointsSource.BREAKDOWN


def test_los_nombres_de_equipo_salen_del_tablero(rig):
    reader, engine = rig
    snap = _feed(reader, engine, Q3_INICIO)

    assert snap.state.team_a.usable_value() == "Taiwan Beer Leopards"
    assert snap.state.team_b.usable_value() == "Shiga Lake Stars"


def test_el_descanso_no_se_cuenta_como_periodo(rig):
    """1H = 45+41 = 86, no 86 + los 86 del acumulado."""
    reader, engine = rig
    snap = _feed(reader, engine, Q3_INICIO)

    assert snap.state.half_score(1).total == 86        # (28+18) + (17+23)
    assert snap.state.total_points == 86
    # Si el descanso se hubiera colado como periodo, la mitad se duplicaria.
    assert snap.state.half_score(1).total == snap.state.total_points


# --------------------------------------------------------------------------
# 20-21. El mismo perfil sobrevive a los cambios de cuarto
# --------------------------------------------------------------------------
def test_q1_a_q2_sin_redefinir_la_region(rig):
    reader, engine = rig
    regiones = set(reader.roi_manager.profile.rois)

    snap = _feed(reader, engine, Q1)
    assert snap.state.period_value == 1
    assert snap.state.total_points == 25
    assert snap.state.period_score(1).total == 25

    snap = _feed(reader, engine, Q2, times=SALTO)
    assert snap.state.period_value == 2
    assert snap.state.total_points == 68
    assert snap.state.period_score(2).total == 22      # 10 + 12

    assert set(reader.roi_manager.profile.rois) == regiones, (
        "no puede hacer falta tocar ninguna region")


def test_q2_a_q3_sin_redefinir_la_region(rig):
    """La columna Puntos se mueve de la 4.a a la 5.a posicion."""
    reader, engine = rig
    _feed(reader, engine, Q2)

    snap = _feed(reader, engine, Q3_INICIO, times=SALTO)
    assert snap.state.period_value == 3
    assert (snap.state.score_a_value, snap.state.score_b_value) == (45, 41)
    assert snap.state.period_score(3).total == 0


def test_q3_a_q4_sin_redefinir_la_region(rig):
    """Y otra vez: de la 5.a a la 6.a posicion."""
    reader, engine = rig
    _feed(reader, engine, Q3_AVANZADO)

    snap = _feed(reader, engine, Q4, times=SALTO)
    assert snap.state.period_value == 4
    assert (snap.state.score_a_value, snap.state.score_b_value) == (70, 65)
    assert snap.state.period_score(3).total == 41      # 22 + 19
    assert snap.state.period_score(4).total == 8       # 3 + 5


def test_el_partido_entero_con_una_sola_region(rig):
    """Q1 -> Q2 -> descanso -> Q3 -> Q4 sin tocar la configuracion."""
    reader, engine = rig
    esperado = [
        (Q1, 1, 25),
        (Q2, 2, 68),
        (Q3_INICIO, 3, 86),
        (Q3_AVANZADO, 3, 100),
        (Q4, 4, 135),
    ]
    for tablero, periodo, total in esperado:
        snap = _feed(reader, engine, tablero, times=SALTO)
        assert snap.state.period_value == periodo, f"fallo en Q{periodo}"
        assert snap.state.total_points == total, f"fallo el total en Q{periodo}"

    assert list(reader.roi_manager.profile.rois) == [
        RoiKind.SCOREBOARD, RoiKind.MARKET_BLOCK]


def test_el_tablero_del_descanso_se_entiende(rig):
    """En el descanso el tablero no trae reloj y aun asi se lee entero.

    La FASE la sigue derivando el reloj, igual que con la region PERIOD de
    toda la vida: el tablero no cambia esa politica. Lo que importa aqui es
    que los parciales de las dos mitades se lean bien y que la columna del
    descanso no se cuele como un periodo.
    """
    reader, engine = rig
    _feed(reader, engine, Q2, times=SALTO)
    snap = _feed(reader, engine, DESCANSO, times=SALTO)

    assert snap.state.period_score(1).total == 46
    assert snap.state.period_score(2).total == 40
    assert snap.state.half_score(1).total == 86
    assert snap.state.total_points == 86, "el acumulado del descanso se duplico"


# --------------------------------------------------------------------------
# 10. Una lectura incoherente no pisa el estado bueno
# --------------------------------------------------------------------------
def test_una_lectura_incoherente_no_pisa_el_estado(rig):
    reader, engine = rig
    _feed(reader, engine, Q3_INICIO)
    bueno = (reader.state.score_a_value, reader.state.score_b_value)
    assert bueno == (45, 41)

    incoherente = """3 cuarto • 09:50
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  85  0  45
Shiga Lake Stars  18  23  41  0  41"""
    snap = _feed(reader, engine, incoherente, times=5)

    assert (snap.state.score_a_value, snap.state.score_b_value) == bueno, (
        "una lectura que no cuadra no puede sobrescribir un estado estable")
    assert snap.state.period_score(1).total == 46


def test_una_lectura_ilegible_no_borra_el_estado(rig):
    reader, engine = rig
    _feed(reader, engine, Q3_INICIO)

    snap = _feed(reader, engine, "ruido sin tablero", times=2)
    assert (snap.state.score_a_value, snap.state.score_b_value) == (45, 41)


def test_una_sola_lectura_no_confirma_nada(rig):
    """El tablero no se salta la estabilizacion."""
    reader, engine = rig
    snap = _feed(reader, engine, Q3_INICIO, times=1)

    assert snap.state.score_a_value is None
    assert snap.state.period_value is None


# --------------------------------------------------------------------------
# 22-26. Las apuestas manuales se alimentan del tablero, sin saber de Stake
# --------------------------------------------------------------------------
def _bet(key: MarketKey, line: float, side: Side = Side.UNDER) -> ManualBet:
    return ManualBet(sportsbook="Stake", event="Taiwan vs Shiga", key=key,
                     side=side, line=line, odds=1.80)


def test_apuesta_manual_q3_usa_los_puntos_del_q3(rig):
    """El caso del enunciado: Q3 UNDER 40.5 con el Q3 recien empezado."""
    reader, engine = rig
    snap = _feed(reader, engine, Q3_INICIO)

    seguimiento = manual_tracking.track_manual_bet(
        snap.state, _bet(MarketKey.quarter(3), 40.5))
    assert seguimiento.scope_points == 0
    assert seguimiento.margin == pytest.approx(40.5)
    assert seguimiento.points_to_cross == 41

    # Avanza el Q3: 8 + 6 = 14 puntos.
    snap = _feed(reader, engine, Q3_AVANZADO)
    seguimiento = manual_tracking.track_manual_bet(
        snap.state, _bet(MarketKey.quarter(3), 40.5))
    assert seguimiento.scope_points == 14
    assert seguimiento.margin == pytest.approx(26.5)
    assert seguimiento.points_to_cross == 27


def test_apuesta_manual_q4_usa_los_puntos_del_q4(rig):
    reader, engine = rig
    snap = _feed(reader, engine, Q4)

    seguimiento = manual_tracking.track_manual_bet(
        snap.state, _bet(MarketKey.quarter(4), 40.5))
    assert seguimiento.scope_points == 8            # 3 + 5
    assert seguimiento.margin == pytest.approx(32.5)
    assert seguimiento.points_to_cross == 33


def test_apuesta_manual_1h_usa_q1_mas_q2(rig):
    """Y NUNCA la columna del descanso."""
    reader, engine = rig
    snap = _feed(reader, engine, Q4)

    seguimiento = manual_tracking.track_manual_bet(
        snap.state, _bet(MarketKey.half_market(1), 90.5))
    assert seguimiento.scope_points == 86            # (28+18) + (17+23)
    assert seguimiento.margin == pytest.approx(4.5)


def test_apuesta_manual_2h_usa_q3_mas_q4(rig):
    """La 2.a mitad son Q3+Q4; el acumulado del descanso no entra."""
    reader, engine = rig
    snap = _feed(reader, engine, Q4)

    seguimiento = manual_tracking.track_manual_bet(
        snap.state, _bet(MarketKey.half_market(2), 60.5))
    assert seguimiento.scope_points == 49            # (22+19) + (3+5)
    assert seguimiento.margin == pytest.approx(11.5)
    # Y no se parece a la 1.a mitad ni al descanso.
    assert seguimiento.scope_points != 86


def test_apuesta_manual_de_partido_usa_el_total(rig):
    reader, engine = rig
    snap = _feed(reader, engine, Q4)

    seguimiento = manual_tracking.track_manual_bet(
        snap.state, _bet(MarketKey.game(), 185.5))
    assert seguimiento.scope_points == 135           # 70 + 65
    assert seguimiento.margin == pytest.approx(50.5)


def test_varias_apuestas_a_la_vez_desde_el_tablero(rig):
    reader, engine = rig
    snap = _feed(reader, engine, Q4)

    apuestas = [
        _bet(MarketKey.quarter(4), 40.5),
        _bet(MarketKey.half_market(2), 60.5),
        _bet(MarketKey.game(), 185.5),
    ]
    seguimientos = manual_tracking.track_manual_bets(snap.state, apuestas)
    assert [t.scope_points for t in seguimientos] == [8, 49, 135]


def test_el_seguimiento_manual_no_depende_del_tablero():
    """manual_tracking consume GameState, nunca el tablero ni una casa.

    Se mira el CODIGO, no los comentarios: el modulo puede citar a Stake al
    explicar un ejemplo, pero no puede importar nada suyo ni ramificar por
    casa. Asi una apuesta manual funciona igual venga el marcador del DOM de
    BetPlay, del tablero de Stake o de las regiones sueltas de otra casa.
    """
    import ast
    import inspect

    arbol = ast.parse(inspect.getsource(manual_tracking))

    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            importados.add(nodo.module or "")
        elif isinstance(nodo, ast.Import):
            importados.update(alias.name for alias in nodo.names)

    assert not any("scoreboard" in m for m in importados), (
        f"el seguimiento manual importa el tablero: {importados}")
    assert not any("parsers" in m or "pipeline" in m for m in importados), (
        f"el seguimiento manual no puede depender de la lectura: {importados}")

    # Y en el codigo ejecutable no aparece ninguna casa concreta.
    literales = [n.value.lower() for n in ast.walk(arbol)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    codigo = [t for t in literales if "\n" not in t and len(t) < 60]
    assert not any("stake" in t or "betplay" in t for t in codigo), (
        "el seguimiento manual ramifica por casa de apuestas")


# --------------------------------------------------------------------------
# 28. Los perfiles antiguos siguen funcionando
# --------------------------------------------------------------------------
def test_un_perfil_clasico_sin_tablero_funciona_igual():
    """Regiones sueltas de siempre: nada cambia para ellas."""
    profile = SportsbookProfile(name="Sportium 1080", sportsbook="Sportium",
                                frame=Rect(0, 0, 1920, 1080))
    profile.set_roi(RoiKind.CLOCK, Rect(100, 100, 100, 40))
    profile.set_roi(RoiKind.PERIOD, Rect(220, 100, 60, 40))
    profile.set_roi(RoiKind.SCORE_PAIR, Rect(300, 100, 200, 40))
    profile.set_roi(RoiKind.MARKET_BLOCK, Rect(1200, 350, 400, 300))

    engine = StubEngine()
    engine.set_text("CLOCK", "05:28")
    engine.set_text("PERIOD", "Q3")
    engine.set_text("SCORE_PAIR", "43 - 31")
    reader = LiveReader(RoiManager(profile, NullCapture(), use_anchor=False), engine,
                        logbus=LogBus(), required_confirmations=2)

    snap = None
    for _ in range(3):
        snap = reader.tick()

    assert snap.state.clock_value == 328
    assert snap.state.period_value == 3
    assert (snap.state.score_a_value, snap.state.score_b_value) == (43, 31)
    assert profile.missing_required() == []


def test_las_regiones_propias_mandan_sobre_el_tablero():
    """Si el perfil define el reloj aparte, ese reloj es el que vale."""
    profile = _stake_profile()
    profile.set_roi(RoiKind.CLOCK, Rect(100, 100, 100, 40))

    engine = StubEngine()
    engine.set_text("SCOREBOARD", Q3_INICIO)     # el tablero dice 10:00
    engine.set_text("CLOCK", "02:15")            # la region propia dice 02:15
    reader = LiveReader(RoiManager(profile, NullCapture(), use_anchor=False), engine,
                        logbus=LogBus(), required_confirmations=2)

    snap = None
    for _ in range(3):
        snap = reader.tick()

    assert snap.state.clock_value == 135, "la region propia debe mandar"
    # Y el resto del tablero se sigue aprovechando.
    assert snap.state.period_value == 3
    assert (snap.state.score_a_value, snap.state.score_b_value) == (45, 41)


# --------------------------------------------------------------------------
# 29. Configuracion del perfil
# --------------------------------------------------------------------------
def test_el_tablero_cubre_reloj_cuarto_y_marcador():
    profile = _stake_profile()
    assert profile.missing_required() == [], (
        "con el tablero no deben hacer falta cuatro regiones mas")


def test_sin_tablero_siguen_faltando_las_regiones_de_siempre():
    profile = SportsbookProfile(name="Vacio", sportsbook="Otra")
    faltan = set(profile.missing_required())
    assert {RoiKind.CLOCK, RoiKind.PERIOD, RoiKind.SCORE_PAIR} <= faltan


def test_el_tablero_declara_que_cubre():
    cubre = set(RoiKind.SCOREBOARD.covers)
    assert {RoiKind.CLOCK, RoiKind.PERIOD, RoiKind.SCORE_PAIR} <= cubre
    assert RoiKind.SCOREBOARD.is_required is False, (
        "no puede ser obligatorio para todas las casas")
    assert RoiKind.MARKET_BLOCK not in cubre, (
        "el tablero no trae las lineas del mercado")


# --------------------------------------------------------------------------
# 27. BetPlay por DOM conserva la prioridad
# --------------------------------------------------------------------------
def _betplay_payload(score_a: int, score_b: int, clock: str, period: int = 3):
    return {
        "protocol": 1, "source": "betplay",
        "observedAt": "2026-08-19T02:00:00.000Z",
        "event": {"id": "9876543", "name": "Taiwan vs Shiga"},
        "visibleMarket": {"marketType": "QUARTER_TOTAL", "period": period, "half": None,
                          "confidence": 0.95,
                          "rawTitle": f"Total de puntos - Cuarto {period}",
                          "sidesConfirmed": True},
        "lines": [{"line": 44.5, "overOdds": 1.75, "underOdds": 1.90}],
        "gameState": {"scoreA": score_a, "scoreB": score_b,
                      "period": period, "clock": clock},
    }


def test_el_dom_de_betplay_manda_sobre_el_tablero_ocr():
    """Con las dos fuentes vivas, el DOM gana: viene estructurado de la pagina."""
    from visorunder.bridge.source import BrowserSource

    profile = _stake_profile()
    engine = StubEngine()
    engine.set_text("SCOREBOARD", Q3_INICIO)        # el OCR dice 45-41, 10:00
    fuente = BrowserSource()
    fuente.accept(_betplay_payload(score_a=58, score_b=52, clock="06:24"))

    reader = LiveReader(RoiManager(profile, NullCapture(), use_anchor=False), engine,
                        logbus=LogBus(), required_confirmations=2,
                        browser_source=fuente)
    snap = None
    for _ in range(3):
        snap = reader.tick()

    assert (snap.state.score_a_value, snap.state.score_b_value) == (58, 52), (
        "el tablero OCR piso al DOM")
    assert snap.state.clock_value == 6 * 60 + 24
    assert snap.state.period_value == 3


def test_sin_dom_el_tablero_ocr_toma_el_relevo():
    """Stake no tiene extension: el tablero debe bastarse solo."""
    from visorunder.bridge.source import BrowserSource

    profile = _stake_profile()
    engine = StubEngine()
    engine.set_text("SCOREBOARD", Q3_INICIO)
    fuente = BrowserSource()                        # nunca recibe nada

    reader = LiveReader(RoiManager(profile, NullCapture(), use_anchor=False), engine,
                        logbus=LogBus(), required_confirmations=2,
                        browser_source=fuente)
    snap = None
    for _ in range(3):
        snap = reader.tick()

    assert (snap.state.score_a_value, snap.state.score_b_value) == (45, 41)
    assert snap.state.clock_value == 600
    assert snap.state.period_score(3).total == 0


# --------------------------------------------------------------------------
# Prorroga y mitades: ni se duplica el descanso ni se contamina la 2.a mitad
# --------------------------------------------------------------------------
PRORROGA = """OT 03:00
1  2  Medio tiempo  3  4  OT  Puntos
Taiwan Beer Leopards  28  17  45  22  8  6  81
Shiga Lake Stars  18  23  41  19  15  9  84"""


def test_la_prorroga_no_contamina_las_mitades(rig):
    reader, engine = rig
    snap = _feed(reader, engine, PRORROGA, times=SALTO)
    state = snap.state

    assert state.period_score(5).total == 15          # 6 + 9, la prorroga
    assert state.half_score(1).total == 86            # (28+18) + (17+23)
    assert state.half_score(2).total == 64            # (22+19) + (8+15)
    assert state.total_points == 165                  # 81 + 84
    # La suma de los periodos coincide con el total: nada se conto dos veces.
    assert sum(state.period_score(p).total for p in range(1, 6)) == 165
    # Y el acumulado del descanso (45+41=86) no se ha sumado por su cuenta.
    assert state.total_points != 165 + 86


def test_las_mitades_no_incluyen_el_acumulado_del_descanso(rig):
    """1H son Q1+Q2. Si el descanso entrara, saldria el doble."""
    reader, engine = rig
    snap = _feed(reader, engine, Q4, times=SALTO)

    assert snap.state.half_score(1).total == 86
    assert snap.state.half_score(2).total == 49       # (22+19) + (3+5)
    assert (snap.state.half_score(1).total
            + snap.state.half_score(2).total) == snap.state.total_points


def test_el_tablero_se_resume_en_una_linea_para_el_log():
    """El repr completo del dataclass haria inservible el diagnostico."""
    from visorunder.parsers.scoreboard_parser import parse_scoreboard

    resumen = str(parse_scoreboard(Q3_INICIO).value)
    assert "\n" not in resumen
    assert len(resumen) < 120
    assert "45-41" in resumen and "Q3:0+0" in resumen
