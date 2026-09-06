"""Tablero de columnas variables (Stake): que la columna se mueva no importa.

El tablero de Stake va anadiendo columnas conforme avanza el partido y las
inserta ANTES del total:

    Q1:  1 | Puntos
    Q2:  1 | 2 | Medio tiempo | Puntos
    Q3:  1 | 2 | Medio tiempo | 3 | Puntos
    Q4:  1 | 2 | Medio tiempo | 3 | 4 | Puntos

Estas pruebas fijan que el total se localiza por su ENCABEZADO y nunca por su
posicion, y que "Medio tiempo" jamas se cuenta como un periodo.
"""

from __future__ import annotations

import pytest

from visorunder.parsers.scoreboard_parser import (
    ColumnKind,
    parse_scoreboard,
)

#: El tablero real que observo el usuario en el Q3.
Q3_REAL = """3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  45  0  45
Shiga Lake Stars  18  23  41  0  41"""


def _read(texto: str, **kwargs):
    resultado = parse_scoreboard(texto, **kwargs)
    assert resultado.value is not None, f"no se pudo leer: {resultado.reason}"
    return resultado


def _labels(lectura) -> str:
    return " ".join(c.label for c in lectura.columns)


# ---------------------------------------------------------------------------
# 1-5. El mismo tablero en cada fase del partido
# ---------------------------------------------------------------------------
def test_scoreboard_q1():
    resultado = _read("""1 cuarto • 07:12
1  Puntos
Taiwan Beer Leopards  14  14
Shiga Lake Stars  11  11""")
    lectura = resultado.value

    assert _labels(lectura) == "Q1 TOTAL"
    assert lectura.period == 1
    assert lectura.clock_seconds == 7 * 60 + 12
    assert (lectura.score_a, lectura.score_b) == (14, 11)
    assert lectura.breakdown_a == {1: 14}
    assert lectura.halftime_a is None, "en el Q1 todavia no hay descanso"


def test_scoreboard_q2():
    resultado = _read("""2 cuarto • 04:31
1  2  Medio tiempo  Puntos
Taiwan Beer Leopards  28  10  38  38
Shiga Lake Stars  18  12  30  30""")
    lectura = resultado.value

    assert _labels(lectura) == "Q1 Q2 HALFTIME TOTAL"
    assert lectura.period == 2
    assert (lectura.score_a, lectura.score_b) == (38, 30)
    assert lectura.breakdown_a == {1: 28, 2: 10}
    assert lectura.halftime_a == 38


def test_scoreboard_descanso():
    """En el descanso la FASE dice "Medio tiempo" y el encabezado tambien.

    Son dos cosas distintas y no pueden fundirse en una sola columna.
    """
    resultado = _read("""Medio tiempo
1  2  Medio tiempo  Puntos
Taiwan Beer Leopards  28  17  45  45
Shiga Lake Stars  18  23  41  41""")
    lectura = resultado.value

    assert _labels(lectura) == "Q1 Q2 HALFTIME TOTAL", (
        "la fase del partido se colo como una columna del tablero")
    assert lectura.phase == "HALFTIME"
    assert lectura.breakdown_a == {1: 28, 2: 17}
    assert lectura.halftime_a == 45
    assert (lectura.score_a, lectura.score_b) == (45, 41)


def test_scoreboard_q3_caso_real():
    """El tablero exacto que observo el usuario."""
    resultado = _read(Q3_REAL)
    lectura = resultado.value

    assert _labels(lectura) == "Q1 Q2 HALFTIME Q3 TOTAL"
    assert lectura.period == 3
    assert lectura.clock_seconds == 600
    assert lectura.team_a == "Taiwan Beer Leopards"
    assert lectura.team_b == "Shiga Lake Stars"
    assert (lectura.score_a, lectura.score_b) == (45, 41)
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 0}
    assert lectura.breakdown_b == {1: 18, 2: 23, 3: 0}
    assert (lectura.halftime_a, lectura.halftime_b) == (45, 41)
    assert not resultado.suspicious


def test_scoreboard_q4():
    resultado = _read("""4 cuarto • 09:02
1  2  Medio tiempo  3  4  Puntos
Taiwan Beer Leopards  28  17  45  22  3  70
Shiga Lake Stars  18  23  41  19  5  65""")
    lectura = resultado.value

    assert _labels(lectura) == "Q1 Q2 HALFTIME Q3 Q4 TOTAL"
    assert lectura.period == 4
    assert (lectura.score_a, lectura.score_b) == (70, 65)
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 22, 4: 3}
    assert lectura.halftime_a == 45


# ---------------------------------------------------------------------------
# 6. La columna Puntos se mueve y da igual
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("etiqueta, texto, indice_total, esperado", [
    ("Q1", """1 cuarto • 07:12
1  Puntos
Taiwan  14  14
Shiga  11  11""", 1, 14),
    ("Q2", """2 cuarto • 04:31
1  2  Medio tiempo  Puntos
Taiwan  28  10  38  38
Shiga  18  12  30  30""", 3, 38),
    ("Q3", """3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan  28  17  45  0  45
Shiga  18  23  41  0  41""", 4, 45),
    ("Q4", """4 cuarto • 09:02
1  2  Medio tiempo  3  4  Puntos
Taiwan  28  17  45  22  3  70
Shiga  18  23  41  19  5  65""", 5, 70),
])
def test_la_columna_puntos_cambia_de_sitio(etiqueta, texto, indice_total, esperado):
    """El total se localiza por su encabezado, nunca por su coordenada."""
    lectura = _read(texto).value

    posicion = [i for i, c in enumerate(lectura.columns) if c.kind is ColumnKind.TOTAL]
    assert posicion == [indice_total], f"{etiqueta}: el total no esta donde se espera"
    assert lectura.score_a == esperado
    assert lectura.total_from_header is True


def test_el_mismo_perfil_sobrevive_a_todo_el_partido():
    """Q1 -> Q2 -> descanso -> Q3 -> Q4 con la MISMA region, sin redefinir nada."""
    secuencia = [
        ("""1 cuarto • 07:12
1  Puntos
Taiwan  14  14
Shiga  11  11""", 14, {1: 14}),
        ("""2 cuarto • 04:31
1  2  Medio tiempo  Puntos
Taiwan  28  10  38  38
Shiga  18  12  30  30""", 38, {1: 28, 2: 10}),
        ("""Medio tiempo
1  2  Medio tiempo  Puntos
Taiwan  28  17  45  45
Shiga  18  23  41  41""", 45, {1: 28, 2: 17}),
        ("""3 cuarto • 05:00
1  2  Medio tiempo  3  Puntos
Taiwan  28  17  45  12  57
Shiga  18  23  41  9  50""", 57, {1: 28, 2: 17, 3: 12}),
        ("""4 cuarto • 09:02
1  2  Medio tiempo  3  4  Puntos
Taiwan  28  17  45  22  3  70
Shiga  18  23  41  19  5  65""", 70, {1: 28, 2: 17, 3: 22, 4: 3}),
    ]
    for texto, total, parciales in secuencia:
        lectura = _read(texto).value
        assert lectura.score_a == total
        assert lectura.breakdown_a == parciales


# ---------------------------------------------------------------------------
# 7-9. "Medio tiempo" es acumulado; coherencia
# ---------------------------------------------------------------------------
def test_medio_tiempo_nunca_es_un_periodo():
    """28 + 17 + 45 + 0 = 90 seria el error. Los parciales son 28, 17 y 0."""
    lectura = _read(Q3_REAL).value

    assert 45 not in lectura.breakdown_a.values() or lectura.breakdown_a.get(3) != 45
    assert sum(lectura.breakdown_a.values()) == 45, "el descanso se sumo como periodo"
    assert lectura.halftime_a == 45
    assert len(lectura.breakdown_a) == 3, "el descanso ocupo un hueco de periodo"
    # Y ninguna columna de periodo apunta al acumulado.
    periodos = [c.period for c in lectura.columns if c.kind is ColumnKind.PERIOD]
    assert periodos == [1, 2, 3]


def test_la_primera_mitad_tiene_que_cuadrar():
    lectura = _read(Q3_REAL).value
    assert lectura.breakdown_a[1] + lectura.breakdown_a[2] == lectura.halftime_a
    assert lectura.breakdown_b[1] + lectura.breakdown_b[2] == lectura.halftime_b


def test_los_parciales_tienen_que_sumar_el_total():
    lectura = _read(Q3_REAL).value
    assert sum(lectura.breakdown_a.values()) == lectura.score_a
    assert sum(lectura.breakdown_b.values()) == lectura.score_b


# ---------------------------------------------------------------------------
# 10. Una lectura incoherente no puede pisar un estado bueno
# ---------------------------------------------------------------------------
def test_un_descanso_que_no_cuadra_se_marca_sospechoso():
    resultado = parse_scoreboard("""3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  85  0  45
Shiga Lake Stars  18  23  41  0  41""")

    assert resultado.suspicious is True
    assert "no cuadra" in resultado.reason
    assert resultado.ok is False, (
        "una lectura sospechosa no puede confirmarse en el estabilizador")


def test_un_total_que_no_suma_se_marca_sospechoso():
    resultado = parse_scoreboard("""3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  45  0  99
Shiga Lake Stars  18  23  41  0  41""")

    assert resultado.suspicious is True
    assert "no suman el total" in resultado.reason
    assert resultado.ok is False


def test_puntos_por_cuarto_inverosimiles_se_rechazan():
    resultado = parse_scoreboard("""3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  170  198  0  198
Shiga Lake Stars  18  23  41  0  41""")
    assert resultado.value is None
    assert "inverosimiles" in resultado.reason


# ---------------------------------------------------------------------------
# 11-13. OCR imperfecto
# ---------------------------------------------------------------------------
def test_ocr_punt0s_y_medi0_tiemp0():
    lectura = _read("""3 cuarto • 10:00
1  2  Medi0 tiemp0  3  Punt0s
Taiwan Beer Leopards  28  17  45  0  45
Shiga Lake Stars  18  23  41  0  41""").value

    assert _labels(lectura) == "Q1 Q2 HALFTIME Q3 TOTAL"
    assert lectura.score_a == 45
    assert lectura.halftime_a == 45


@pytest.mark.parametrize("cabecera", ["Puntos", "Punt0s", "Punto", "Puntos:", "Pts", "Total"])
def test_variantes_de_la_palabra_puntos(cabecera):
    lectura = _read(f"""3 cuarto • 10:00
1  2  Medio tiempo  3  {cabecera}
Taiwan  28  17  45  0  45
Shiga  18  23  41  0  41""").value
    assert lectura.total_from_header is True
    assert lectura.score_a == 45


@pytest.mark.parametrize("estado, periodo, reloj", [
    ("3 cuarto • 10:00", 3, 600),
    ("3cuarto 10:00", 3, 600),
    ("3 cuarto. 10.00", 3, 600),
    ("3er cuarto | 09:59", 3, 599),
])
def test_variantes_del_cuarto_y_del_reloj(estado, periodo, reloj):
    lectura = _read(f"""{estado}
1  2  Medio tiempo  3  Puntos
Taiwan  28  17  45  0  45
Shiga  18  23  41  0  41""").value
    assert lectura.period == periodo
    assert lectura.clock_seconds == reloj


def test_un_nombre_parecido_a_puntos_no_es_una_columna():
    """"Punta Cana" no puede confundirse con la columna "Puntos"."""
    lectura = _read("""3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Punta Cana  28  17  45  0  45
Shiga Lake Stars  18  23  41  0  41""").value

    assert lectura.team_a == "Punta Cana"
    assert len(lectura.columns) == 5
    assert lectura.score_a == 45


def test_nombre_de_equipo_con_digitos():
    lectura = _read("""4 cuarto • 02:00
1  2  Medio tiempo  3  4  Puntos
Philadelphia 76ers  28  17  45  22  3  70
Shiga Lake Stars  18  23  41  19  5  65""").value

    assert lectura.team_a == "Philadelphia 76ers"
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 22, 4: 3}


def test_una_caja_por_linea_como_devuelve_rapidocr():
    """RapidOCR entrega UNA LINEA POR CAJA, no una por fila visual."""
    lectura = _read("\n".join([
        "3 cuarto", "10:00",
        "1", "2", "Medio tiempo", "3", "Puntos",
        "Taiwan Beer Leopards", "28", "17", "45", "0", "45",
        "Shiga Lake Stars", "18", "23", "41", "0", "41",
    ])).value

    assert lectura.period == 3
    assert lectura.clock_seconds == 600
    assert (lectura.score_a, lectura.score_b) == (45, 41)
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 0}
    assert lectura.halftime_a == 45


# ---------------------------------------------------------------------------
# 14-15. Tableros incompletos: no se inventa nada
# ---------------------------------------------------------------------------
def test_sin_columna_puntos_el_total_sale_de_los_parciales():
    """Solo cuando los parciales lo determinan sin huecos."""
    resultado = _read("""3 cuarto • 10:00
1  2  Medio tiempo  3
Taiwan Beer Leopards  28  17  45  0
Shiga Lake Stars  18  23  41  0""")
    lectura = resultado.value

    assert lectura.total_from_header is False
    assert lectura.score_a == 45      # 28 + 17 + 0, sin contar el descanso
    assert lectura.score_b == 41


def test_sin_puntos_y_con_huecos_no_se_afirma_el_total():
    lectura = _read("""3 cuarto • 10:00
1  3  Medio tiempo
Taiwan Beer Leopards  28  0  45
Shiga Lake Stars  18  0  41""").value

    assert lectura.total_from_header is False
    assert lectura.score_a is None, "faltaba el Q2: el total no se puede afirmar"
    assert lectura.score_b is None
    assert lectura.breakdown_a == {1: 28, 3: 0}


def test_sin_encabezado_no_hay_tablero():
    resultado = parse_scoreboard("""3 cuarto • 10:00
Taiwan Beer Leopards  28  17  45  0  45
Shiga Lake Stars  18  23  41  0  41""")
    assert resultado.value is None
    assert "encabezado" in resultado.reason


def test_con_una_sola_fila_no_hay_tablero():
    resultado = parse_scoreboard("""3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
Taiwan Beer Leopards  28  17  45  0  45""")
    assert resultado.value is None
    assert "filas de equipo" in resultado.reason


def test_texto_vacio():
    resultado = parse_scoreboard("")
    assert resultado.value is None
    assert resultado.reason == "sin texto"


def test_texto_arbitrario_no_produce_un_marcador():
    """No se puede ser tan permisivo que cualquier texto valga."""
    for basura in ("hola que tal", "Cuotas 1.85 1.95 2.10",
                   "Total de puntos 185.5", "-- -- --"):
        resultado = parse_scoreboard(basura)
        assert resultado.value is None, f"{basura!r} produjo un tablero"


# ---------------------------------------------------------------------------
# Prorroga
# ---------------------------------------------------------------------------
def test_la_prorroga_es_un_periodo_mas():
    lectura = _read("""OT 03:00
1  2  Medio tiempo  3  4  OT  Puntos
Taiwan  28  17  45  22  8  6  81
Shiga  18  23  41  19  15  9  84""").value

    assert _labels(lectura) == "Q1 Q2 HALFTIME Q3 Q4 Q5 TOTAL"
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 22, 4: 8, 5: 6}
    assert lectura.score_a == 81
    assert sum(lectura.breakdown_a.values()) == 81


def test_reglas_nba_cambian_el_indice_de_la_prorroga():
    lectura = _read("""OT 03:00
1  2  Medio tiempo  3  4  OT  Puntos
Taiwan  28  17  45  22  8  6  81
Shiga  18  23  41  19  15  9  84""", regulation_quarters=4).value
    assert 5 in lectura.breakdown_a


# ---------------------------------------------------------------------------
# Estructura devuelta
# ---------------------------------------------------------------------------
def test_breakdown_pairs_solo_devuelve_periodos_de_los_dos_equipos():
    lectura = _read(Q3_REAL).value
    assert lectura.breakdown_pairs() == [(1, 28, 18), (2, 17, 23), (3, 0, 0)]
    assert lectura.has_scores is True
    assert lectura.periods == (1, 2, 3)


def test_un_nombre_que_acaba_en_numero_no_descoloca_las_columnas():
    """Los datos son SIEMPRE los ultimos numeros de la tirada."""
    lectura = _read("""4 cuarto • 02:00
1  2  Medio tiempo  3  4  Puntos
Real Madrid 2  28  17  45  22  3  70
Shiga Lake Stars  18  23  41  19  5  65""").value

    assert lectura.team_a == "Real Madrid 2"
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 22, 4: 3}
    assert lectura.score_a == 70
    assert lectura.halftime_a == 45


def test_una_fila_de_puros_numeros_sin_nombre_no_vale():
    """Sin nombre de equipo no se puede afirmar de quien es la fila."""
    resultado = parse_scoreboard("""3 cuarto • 10:00
1  2  Medio tiempo  3  Puntos
28  17  45  0  45
18  23  41  0  41""")
    assert resultado.value is None


def test_el_numero_del_cuarto_pegado_al_encabezado_no_corre_las_columnas():
    """"4" (la fase) seguido del encabezado del Q4 no anade una columna."""
    lectura = _read("""4
1  2  Medio tiempo  3  4  Puntos
Taiwan  28  17  45  22  3  70
Shiga  18  23  41  19  5  65""").value

    assert _labels(lectura) == "Q1 Q2 HALFTIME Q3 Q4 TOTAL"
    assert lectura.breakdown_a == {1: 28, 2: 17, 3: 22, 4: 3}
    assert lectura.score_a == 70
