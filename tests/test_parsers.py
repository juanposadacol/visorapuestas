"""Requisito 21: reglas de validacion de cada campo."""

import pytest

from visorunder.domain.market import MarketType
from visorunder.parsers.clock_parser import looks_like_period_change, parse_clock
from visorunder.parsers.market_parser import parse_lines_block, parse_market_label
from visorunder.parsers.odds_parser import parse_line, parse_odds
from visorunder.parsers.quarter_parser import parse_period
from visorunder.parsers.score_parser import parse_breakdown, parse_score, parse_score_pair


# ------------------------------------------------------------------- reloj
@pytest.mark.parametrize("text,expected", [("05:28", 328), ("10:00", 600), ("00:00", 0), ("O5:2B", 328)])
def test_reloj_valido(text, expected):
    r = parse_clock(text)
    assert r.ok and r.value == expected


def test_reloj_con_segundos_invalidos_se_rechaza():
    r = parse_clock("05:75")
    assert r.value is None and "no reconocido" in r.reason


def test_reloj_mayor_que_el_cuarto_se_rechaza():
    r = parse_clock("11:30", max_period_seconds=600)
    assert r.value is None and "supera" in r.reason


def test_reloj_sin_separador_es_sospechoso_no_confirmable():
    r = parse_clock("0528")
    assert r.value == 328
    assert r.suspicious is True
    assert r.ok is False


def test_cambio_de_cuarto_por_el_reloj():
    assert looks_like_period_change(1, 600, 600) is True
    assert looks_like_period_change(300, 299, 600) is False
    assert looks_like_period_change(None, 600, 600) is False


# --------------------------------------------------------------- marcador
def test_marcador_simple():
    assert parse_score("43").value == 43
    assert parse_score("l0").value == 10


def test_marcador_inverosimil_se_rechaza():
    assert parse_score("9999").value is None
    assert parse_score("").value is None


def test_marcador_par():
    assert parse_score_pair("43 - 31").value == (43, 31)
    assert parse_score_pair("43:31").value == (43, 31)
    assert parse_score_pair("xx").value is None


def test_desglose_por_cuartos():
    assert parse_breakdown("24 18 19 22").value == [24, 18, 19, 22]
    # con total al final
    assert parse_breakdown("24 18 19 22 83").value == [24, 18, 19, 22]
    assert parse_breakdown("24 18 19 22 30").value is None


# ----------------------------------------------------------------- cuarto
@pytest.mark.parametrize("text,expected", [
    ("Q3", 3), ("3Q", 3), ("3", 3), ("3.er Cuarto", 3), ("Cuarto 2", 2),
    ("2º periodo", 2), ("1er cuarto", 1), ("Q4", 4),
])
def test_cuarto_valido(text, expected):
    assert parse_period(text).value == expected


def test_prorroga():
    assert parse_period("OT").value == 5
    assert parse_period("OT2").value == 6
    assert parse_period("Prórroga").value == 5


def test_descanso_y_final():
    assert parse_period("Descanso").value is None
    assert parse_period("Descanso").normalized == "HALFTIME"
    assert parse_period("Finalizado").normalized == "GAME_OVER"


# ------------------------------------------------------------------ cuotas
@pytest.mark.parametrize("text,expected", [("1.87", 1.87), ("1,87", 1.87), ("2.25", 2.25), ("10.50", 10.5)])
def test_cuota_valida(text, expected):
    r = parse_odds(text)
    assert r.ok and r.value == pytest.approx(expected)


def test_cuota_187_no_se_corrige_en_silencio():
    """Requisito 21: 187 probablemente es 1.87, pero queda NO CONFIRMADA."""
    r = parse_odds("187")
    assert r.value == pytest.approx(1.87)
    assert r.suspicious is True
    assert r.ok is False
    assert r.hint == "1.87"


def test_cuota_fuera_de_rango():
    assert parse_odds("45.00").value is None
    assert parse_odds("0.50").value is None


# ------------------------------------------------------------------ lineas
@pytest.mark.parametrize("text,expected", [("40.5", 40.5), ("153.5", 153.5), ("37,5", 37.5), ("40", 40.0)])
def test_linea_valida(text, expected):
    r = parse_line(text)
    assert r.ok and r.value == pytest.approx(expected)


def test_linea_con_decimal_atipico_es_sospechosa():
    r = parse_line("40.3")
    assert r.value == 40.3 and r.suspicious is True


def test_linea_fuera_de_rango():
    assert parse_line("2.5").value is None
    assert parse_line("999").value is None


# ---------------------------------------------------------- etiqueta mercado
def test_etiqueta_de_cuarto():
    r = parse_market_label("3.er Cuarto - Total de puntos")
    assert r.ok
    assert r.value.market_type is MarketType.QUARTER_TOTAL
    assert r.value.period == 3


def test_etiqueta_de_partido():
    r = parse_market_label("Partido - Total de puntos")
    assert r.ok and r.value.market_type is MarketType.GAME_TOTAL


def test_etiqueta_de_mitad():
    r = parse_market_label("1.ª mitad - Total de puntos")
    assert r.value.market_type is MarketType.HALF_TOTAL and r.value.half == 1


def test_etiqueta_ambigua_es_sospechosa():
    r = parse_market_label("Total de puntos")
    assert r.value.market_type is MarketType.GAME_TOTAL
    assert r.suspicious is True


# ------------------------------------------------------------ bloque lineas
def test_bloque_horizontal_multiples_lineas():
    text = """37.5 OVER 1.55 UNDER 2.25
38.5 OVER 1.68 UNDER 2.05
39.5 OVER 1.80 UNDER 1.90
40.5 OVER 1.95 UNDER 1.72"""
    snap = parse_lines_block(text, sportsbook="Sportium", event="A vs B")
    assert len(snap.lines) == 4
    first = snap.lines[0]
    assert (first.line, first.over_odds, first.under_odds) == (37.5, 1.55, 2.25)
    last = snap.lines[-1]
    assert (last.line, last.over_odds, last.under_odds) == (40.5, 1.95, 1.72)


def test_bloque_vertical_una_sola_linea():
    text = "40.5\nOVER 1.75\nUNDER 1.87"
    snap = parse_lines_block(text)
    assert len(snap.lines) == 1
    ln = snap.lines[0]
    assert (ln.line, ln.over_odds, ln.under_odds) == (40.5, 1.75, 1.87)


def test_bloque_vertical_sin_palabras_usa_orden_visual():
    text = "40.5\n1.75\n1.87"
    snap = parse_lines_block(text)
    ln = snap.lines[0]
    assert (ln.line, ln.over_odds, ln.under_odds) == (40.5, 1.75, 1.87)


def test_bloque_en_espanol_mas_menos():
    text = "Más de 153.5  1.80\nMenos de 153.5  1.95"
    snap = parse_lines_block(text)
    assert len(snap.lines) == 1
    ln = snap.lines[0]
    assert ln.line == 153.5
    assert ln.over_odds == 1.80
    assert ln.under_odds == 1.95


def test_mercado_suspendido_se_detecta():
    snap = parse_lines_block("40.5 SUSPENDIDO")
    assert snap.suspended is True


def test_bloque_vacio_no_inventa_lineas():
    assert parse_lines_block("").is_empty
    assert parse_lines_block("basura sin numeros").is_empty


def test_linea_asociada_al_mercado_indicado():
    from visorunder.domain.market import MarketKey
    snap = parse_lines_block("40.5 1.95 1.72", key=MarketKey.quarter(3))
    assert snap.lines[0].quarter == 3
    assert snap.lines[0].market_type is MarketType.QUARTER_TOTAL


# --------------------------- tiempo jugado del partido -> restante del cuarto

def test_convierte_tiempo_jugado_en_restante_del_cuarto():
    from visorunder.domain.rules import FIBA, NBA
    from visorunder.domain.time_utils import period_remaining_from_game_elapsed as convertir

    # El caso REAL de BetPlay: "Q4 - 33:52" con reglas FIBA (4x10).
    assert convertir(33 * 60 + 52, 4, FIBA) == 6 * 60 + 8

    # El mismo valor con NBA (4x12) no cae dentro del cuarto 4: sin respuesta.
    assert convertir(33 * 60 + 52, 4, NBA) is None

    # Principios y finales exactos de cuarto.
    assert convertir(30 * 60, 4, FIBA) == 10 * 60      # acaba de empezar el Q4
    assert convertir(40 * 60, 4, FIBA) == 0            # se acabo el partido
    assert convertir(0, 1, FIBA) == 10 * 60

    # Prorroga: el periodo 5 dura 5 minutos y empieza en 40:00.
    assert convertir(40 * 60 + 30, 5, FIBA) == 4 * 60 + 30


def test_no_convierte_lo_que_no_cuadra():
    from visorunder.domain.rules import FIBA
    from visorunder.domain.time_utils import period_remaining_from_game_elapsed as convertir

    assert convertir(5 * 60, 4, FIBA) is None          # 05:00 no es del cuarto 4
    assert convertir(45 * 60, 4, FIBA) is None         # pasado el final
    assert convertir(None, 4, FIBA) is None
    assert convertir(600, None, FIBA) is None
    assert convertir(-1, 1, FIBA) is None
    assert convertir(600, 0, FIBA) is None
