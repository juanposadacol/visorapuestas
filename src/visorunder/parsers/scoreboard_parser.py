"""Tablero completo con columnas VARIABLES (el caso de Stake).

EL PROBLEMA
-----------
Stake no muestra un tablero fijo: va anadiendo columnas conforme avanza el
partido, y las nuevas se insertan ANTES del total.

    Q1:  1 | Puntos
    Q2:  1 | 2 | Medio tiempo | Puntos
    Q3:  1 | 2 | Medio tiempo | 3 | Puntos
    Q4:  1 | 2 | Medio tiempo | 3 | 4 | Puntos

Una region fija sobre "Puntos" apunta al total en el Q2 y a otra cosa en el
Q3. Por eso un ROI por columna es inviable: habria que redibujarlo cada cuarto.

LA SOLUCION
-----------
Se lee UNA region que abarca el tablero entero y se localiza cada columna
SEMANTICAMENTE, por su encabezado, nunca por su posicion. El total es la
columna cuyo encabezado dice "Puntos"; si esa palabra no se reconoce, no se
inventa un total.

"MEDIO TIEMPO" NO ES UN PERIODO
-------------------------------
Es una columna ACUMULADA (Q1+Q2). Con este tablero real:

    1=28  2=17  Medio tiempo=45  3=0  Puntos=45

los parciales son 28, 17 y 0. Sumar el 45 del descanso daria 90, que es el
doble de la primera mitad. Aqui el descanso viaja en su propio campo y jamas
entra en `breakdown`.

COHERENCIA
----------
El tablero se valida contra si mismo antes de creerselo:

    Q1 + Q2            == Medio tiempo
    suma de los cuartos == Puntos

Una lectura que no cuadre se marca `suspicious`, y el estabilizador ya se
niega a confirmar lo sospechoso: un OCR malo no puede pisar un estado bueno.

POR QUE SE TRABAJA SOBRE UN FLUJO DE TOKENS
-------------------------------------------
RapidOCR devuelve UNA LINEA POR CAJA DETECTADA, no una por fila visual. El
tablero real llega como "3 cuarto / 10:00 / 1 / 2 / Medio tiempo / ..." con
cada celda en su propia linea. Por eso no se parte por lineas: se aplana todo
a una secuencia de tokens y se localiza el encabezado como la RACHA mas larga
de columnas reconocibles que contenga un ancla ("Puntos" o "Medio tiempo").
A partir de ahi el numero de columnas dice cuantos numeros lleva cada fila.

Asi funciona igual si el motor conserva las filas visuales y si las deshace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .base import ParseResult
from .clock_parser import parse_clock
from .normalize import clean, normalize_label
from .quarter_parser import GAME_OVER, HALFTIME, parse_period

#: Un cuarto de baloncesto no llega a 100 puntos ni un partido a 250.
MAX_PERIOD_POINTS = 99
MAX_TOTAL_POINTS = 250


class ColumnKind(str, Enum):
    """Que representa una columna del tablero."""

    PERIOD = "PERIOD"      # un cuarto o una prorroga concretos
    HALFTIME = "HALFTIME"  # acumulado Q1+Q2: NUNCA un periodo
    TOTAL = "TOTAL"        # el marcador del partido


@dataclass(frozen=True)
class Column:
    kind: ColumnKind
    #: Numero de periodo cuando `kind` es PERIOD. None en los demas casos.
    period: Optional[int] = None

    @property
    def label(self) -> str:
        if self.kind is ColumnKind.PERIOD:
            return f"Q{self.period}"
        return self.kind.value


# --------------------------------------------------------------------------
# Reconocimiento de encabezados, tolerante al ruido tipico del OCR
# --------------------------------------------------------------------------
#: "Medio tiempo", "medio tienpo", "Descanso", "HT", "MT".
_HALFTIME = r"(?:medi[o0]\s*t[iy][e3]mp[o0]|descans[o0]|half\s*time|halftime|\bmt\b|\bht\b)"

#: "Puntos", "Punto", "Punt0s", "Puntos:", "Pts", "Total".
#: Se exige la raiz "punt"/"pts"/"total": no vale cualquier palabra.
_TOTAL = r"(?:punt[o0]?s?[.:]?|\bpts?[.:]?\b|t[o0]tal(?:es)?[.:]?)"

#: "OT", "OT2", "PR", "Prorroga 1". El indice viaja en su propio grupo para
#: no depender de `lastindex`, que devuelve el grupo exterior.
_OVERTIME = r"(?:[o0]t|pr[o0]rr[o0]ga|pr)\s*(?P<ot_index>\d)?"

_HEADER_TOKEN = re.compile(
    rf"(?P<halftime>{_HALFTIME})"
    rf"|(?P<total>{_TOTAL})"
    rf"|(?P<overtime>{_OVERTIME})"
    r"|(?P<period>\d{1,2})"
)

#: Reloj MM:SS dentro de una linea con mas texto ("3 cuarto - 10:00").
_CLOCK_IN_LINE = re.compile(r"\b(\d{1,2})\s*[:.]\s*(\d{2})\b")

#: Separadores que las casas usan entre el cuarto y el reloj.
_SEPARATORS = re.compile(r"[•·|/*]+")


@dataclass(frozen=True)
class ScoreboardRead:
    """Lectura normalizada de un tablero de columnas variables."""

    period: Optional[int] = None
    clock_seconds: Optional[int] = None
    team_a: Optional[str] = None
    team_b: Optional[str] = None
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    #: Parciales REALES por periodo. El descanso nunca esta aqui.
    breakdown_a: Dict[int, int] = field(default_factory=dict)
    breakdown_b: Dict[int, int] = field(default_factory=dict)
    #: Acumulado de la primera mitad tal y como lo publica la casa.
    halftime_a: Optional[int] = None
    halftime_b: Optional[int] = None
    #: Columnas detectadas, en el orden en que aparecen.
    columns: Tuple[Column, ...] = ()
    #: True si el total salio de la columna "Puntos"; False si se dedujo.
    total_from_header: bool = False
    phase: str = ""

    @property
    def periods(self) -> Tuple[int, ...]:
        return tuple(sorted(self.breakdown_a))

    @property
    def has_scores(self) -> bool:
        return self.score_a is not None and self.score_b is not None

    def breakdown_pairs(self) -> List[Tuple[int, int, int]]:
        """(periodo, puntos_a, puntos_b) solo de los periodos completos."""
        pares = []
        for period in sorted(set(self.breakdown_a) & set(self.breakdown_b)):
            pares.append((period, self.breakdown_a[period], self.breakdown_b[period]))
        return pares

    def __str__(self) -> str:
        """Resumen de una linea para el panel de diagnostico.

        El `repr` del dataclass ocuparia varias lineas por lectura y el log se
        vuelve inservible; aqui se dice lo justo para entender que se leyo.
        """
        columnas = "/".join(c.label for c in self.columns) or "--"
        marcador = ("--" if not self.has_scores
                    else f"{self.score_a}-{self.score_b}")
        parciales = " ".join(f"Q{p}:{a}+{b}" for p, a, b in self.breakdown_pairs())
        partes = [f"[{columnas}]", marcador]
        if self.period is not None:
            partes.append(f"P{self.period}")
        if self.clock_seconds is not None:
            partes.append(f"{self.clock_seconds}s")
        if parciales:
            partes.append(parciales)
        if not self.total_from_header:
            partes.append("(total deducido)")
        return " ".join(partes)


# --------------------------------------------------------------------------
# Clasificacion de tokens
# --------------------------------------------------------------------------
#: Se comparan TOKENS COMPLETOS, nunca subcadenas: asi un equipo llamado
#: "Punta Cana" no se confunde jamas con la columna "Puntos".
_TOTAL_TOKEN = re.compile(rf"^{_TOTAL}$")
_HALFTIME_TOKEN = re.compile(rf"^{_HALFTIME}$")
_OVERTIME_TOKEN = re.compile(rf"^{_OVERTIME}$")

#: "Medio tiempo" ocupa dos tokens; el segundo se reconoce aparte.
_HALFTIME_FIRST = re.compile(r"^(?:medi[o0]|half)$")
_HALFTIME_SECOND = re.compile(r"^t[iy][e3]mp[o0]$|^time$")


def _tidy(token: str) -> str:
    """Token normalizado y sin la puntuacion que suele pegar el OCR."""
    return normalize_label(token).strip(" .,:;|-–—•·")


def _classify(token: str, regulation_quarters: int) -> Optional[Column]:
    """Convierte UN token en su columna, o None si no es un encabezado."""
    limpio = _tidy(token)
    if not limpio:
        return None
    if _HALFTIME_TOKEN.match(limpio):
        return Column(ColumnKind.HALFTIME)
    if _TOTAL_TOKEN.match(limpio):
        return Column(ColumnKind.TOTAL)
    match = _OVERTIME_TOKEN.match(limpio)
    if match:
        index = int(match.group("ot_index")) if match.group("ot_index") else 1
        return Column(ColumnKind.PERIOD, regulation_quarters + index)
    if limpio.isdigit():
        period = int(limpio)
        if 1 <= period <= regulation_quarters:
            return Column(ColumnKind.PERIOD, period)
    return None


def _read_columns(tokens: List[str], start: int,
                  regulation_quarters: int) -> Tuple[List[Column], int]:
    """Lee la racha de columnas que empieza en `start`.

    Devuelve las columnas y el indice del primer token que ya no lo es.
    """
    columns: List[Column] = []
    index = start
    while index < len(tokens):
        # "Medio tiempo" viene partido en dos tokens.
        if (index + 1 < len(tokens)
                and _HALFTIME_FIRST.match(_tidy(tokens[index]))
                and _HALFTIME_SECOND.match(_tidy(tokens[index + 1]))):
            columns.append(Column(ColumnKind.HALFTIME))
            index += 2
            continue
        column = _classify(tokens[index], regulation_quarters)
        if column is None:
            break
        columns.append(column)
        index += 1
    return columns, index


def _is_valid_header(columns: List[Column], regulation_quarters: int) -> bool:
    """Un encabezado de tablero tiene una forma reconocible.

    Estas reglas son las que impiden que la fase del partido se cuele como si
    fuera una columna. Con el tablero del descanso, el texto empieza por
    "Medio tiempo" (la fase) y JUSTO DESPUES viene el encabezado, que trae su
    propia columna "Medio tiempo": sin estas reglas las dos se pegarian en una
    sola racha y el tablero saldria con una columna de mas.

    Se exige que:
    * haya un ancla con palabra: sin ella no se distingue de una fila de datos;
    * los periodos vayan en orden creciente y sin repetirse;
    * el descanso y el total aparezcan como mucho una vez;
    * el total, si esta, cierre el tablero, que es donde lo pone la casa.
    """
    if not columns:
        return False
    if not any(c.kind in (ColumnKind.TOTAL, ColumnKind.HALFTIME)
               or (c.period is not None and c.period > regulation_quarters)
               for c in columns):
        return False
    if sum(1 for c in columns if c.kind is ColumnKind.HALFTIME) > 1:
        return False
    totales = [i for i, c in enumerate(columns) if c.kind is ColumnKind.TOTAL]
    if len(totales) > 1:
        return False
    if totales and totales[0] != len(columns) - 1:
        return False
    periodos = [c.period for c in columns if c.kind is ColumnKind.PERIOD]
    return all(a < b for a, b in zip(periodos, periodos[1:]))


def _find_header(tokens: List[str],
                 regulation_quarters: int) -> Tuple[Optional[List[Column]], int, int]:
    """Localiza el encabezado: la racha valida mas larga.

    De cada racha de columnas se prueba el trozo mas largo que tenga forma de
    encabezado, no la racha entera: asi un token suelto pegado por delante (la
    fase del partido, el numero del cuarto) se queda fuera en vez de correr
    todas las columnas una posicion.
    """
    mejor: Optional[List[Column]] = None
    mejor_inicio = mejor_fin = -1
    index = 0
    while index < len(tokens):
        columns, fin = _read_columns(tokens, index, regulation_quarters)
        if not columns:
            index += 1
            continue
        # Trozos contiguos, del mas largo al mas corto.
        for longitud in range(len(columns), 0, -1):
            for offset in range(0, len(columns) - longitud + 1):
                trozo = columns[offset:offset + longitud]
                if not _is_valid_header(trozo, regulation_quarters):
                    continue
                if mejor is None or len(trozo) > len(mejor):
                    # Los tokens del descanso ocupan dos posiciones, asi que
                    # los indices se recalculan contando columna por columna.
                    inicio = _token_index(tokens, index, offset, regulation_quarters)
                    final = _token_index(tokens, index, offset + longitud,
                                         regulation_quarters)
                    mejor, mejor_inicio, mejor_fin = trozo, inicio, final
                break
            if mejor is not None and len(mejor) == longitud:
                break
        index = max(fin, index + 1)
    return mejor, mejor_inicio, mejor_fin


def _token_index(tokens: List[str], start: int, columns_ahead: int,
                 regulation_quarters: int) -> int:
    """Indice del token donde empieza la columna numero `columns_ahead`."""
    index = start
    vistas = 0
    while index < len(tokens) and vistas < columns_ahead:
        if (index + 1 < len(tokens)
                and _HALFTIME_FIRST.match(_tidy(tokens[index]))
                and _HALFTIME_SECOND.match(_tidy(tokens[index + 1]))):
            index += 2
        else:
            index += 1
        vistas += 1
    return index


def _read_team_row(tokens: List[str], start: int,
                   expected: int) -> Optional[Tuple[str, List[int], int]]:
    """Lee "Taiwan Beer Leopards 28 17 45 0 45" desde `start`.

    Devuelve (nombre, numeros, indice siguiente). El nombre son los tokens no
    numericos que preceden a la tirada de numeros, de modo que un nombre con
    digitos ("Philadelphia 76ers") no descoloca nada: lo que manda es que haya
    exactamente `expected` numeros seguidos al final.
    """
    nombre: List[str] = []
    index = start
    while index < len(tokens):
        # Tirada COMPLETA de numeros que empieza aqui.
        numeros: List[int] = []
        cursor = index
        while cursor < len(tokens):
            limpio = _tidy(tokens[cursor]).replace(" ", "")
            if not limpio.isdigit():
                break
            numeros.append(int(limpio))
            cursor += 1

        if len(numeros) >= expected:
            # Si sobran numeros por la izquierda son del nombre del equipo
            # ("Real Madrid 2"), no del tablero: los datos son SIEMPRE los
            # ultimos, que es donde la casa pone las columnas.
            sobran = len(numeros) - expected
            nombre.extend(clean(tokens[index + i]) for i in range(sobran))
            texto = " ".join(nombre).strip(" -–—•·|")
            if not any(ch.isalpha() for ch in texto):
                return None
            return texto, numeros[sobran:], cursor

        # Ni el nombre ni una tirada suficiente: se avanza un token.
        nombre.append(clean(tokens[index]))
        index += 1
    return None


def _parse_status_line(text: str, regulation_quarters: int) -> Tuple[Optional[int], Optional[int], str]:
    """Extrae (periodo, reloj, fase) del texto que rodea al tablero.

    Se le pasa SOLO lo que queda fuera del encabezado y de las filas de
    equipo. Es una precaucion deliberada: dentro del encabezado "Medio tiempo"
    es una columna acumulada, y tratarla como la fase del partido pondria el
    partido en el descanso en pleno tercer cuarto.
    """
    texto = _SEPARATORS.sub(" ", clean(text))
    if not texto:
        return None, None, ""

    clock_seconds: Optional[int] = None
    match = _CLOCK_IN_LINE.search(texto)
    if match:
        parsed = parse_clock(match.group(0), max_period_seconds=20 * 60)
        if parsed.ok:
            clock_seconds = parsed.value
        texto = (texto[:match.start()] + " " + texto[match.end():]).strip()

    period: Optional[int] = None
    phase = ""
    if texto:
        parsed = parse_period(texto, regulation_quarters=regulation_quarters)
        if parsed.value is not None:
            period = int(parsed.value)
        elif parsed.normalized in (HALFTIME, GAME_OVER):
            phase = parsed.normalized
    return period, clock_seconds, phase


# --------------------------------------------------------------------------
# Coherencia
# --------------------------------------------------------------------------
def _coherence_problem(breakdown: Dict[int, int], halftime: Optional[int],
                       total: Optional[int], halftime_after: int,
                       total_from_header: bool) -> str:
    """Devuelve el motivo por el que la fila NO cuadra. Vacio si cuadra."""
    primeros = [p for p in range(1, halftime_after + 1)]
    if halftime is not None and all(p in breakdown for p in primeros):
        suma = sum(breakdown[p] for p in primeros)
        if suma != halftime:
            return (f"la primera mitad no cuadra: "
                    f"{'+'.join(str(breakdown[p]) for p in primeros)} = {suma} "
                    f"pero el descanso dice {halftime}")

    if total is not None and total_from_header and breakdown:
        # Solo se compara cuando el encabezado publica todos los periodos
        # jugados de forma contigua desde el primero.
        periodos = sorted(breakdown)
        if periodos == list(range(1, len(periodos) + 1)):
            suma = sum(breakdown.values())
            if suma != total:
                return (f"los parciales no suman el total: {suma} != {total}")
    return ""


def _implied_total(breakdown: Dict[int, int]) -> Optional[int]:
    """Total deducido de los parciales, SOLO si estan todos y contiguos.

    Sin la columna "Puntos" no se afirma un total salvo que los parciales lo
    determinen sin huecos. Preferimos "--" a un marcador inventado.
    """
    if not breakdown:
        return None
    periodos = sorted(breakdown)
    if periodos != list(range(1, len(periodos) + 1)):
        return None
    return sum(breakdown.values())


# --------------------------------------------------------------------------
# Parser publico
# --------------------------------------------------------------------------
def parse_scoreboard(text: str, *, regulation_quarters: int = 4,
                     halftime_after_period: int = 2,
                     confidence: float = 0.0) -> ParseResult:
    """Convierte el texto OCR del tablero en un `ScoreboardRead`.

    No asume ni el numero de columnas ni su orden: los deduce del encabezado
    en cada lectura, que es lo que permite sobrevivir a que Stake inserte una
    columna nueva al empezar un cuarto.
    """
    raw = clean(text)
    if not raw:
        return ParseResult.fail(raw, "sin texto")

    tokens = raw.replace("|", " ").split()

    # 1. El encabezado manda: dice cuantas columnas hay y que es cada una.
    columns, header_start, header_end = _find_header(tokens, regulation_quarters)
    if not columns:
        return ParseResult.fail(raw, "no se reconoce el encabezado del tablero")

    normalized = " | ".join(c.label for c in columns)

    # 2. Detras del encabezado van las dos filas de equipo, cada una con
    #    tantos numeros como columnas tenga el tablero.
    filas: List[Tuple[str, List[int]]] = []
    cursor = header_end
    while len(filas) < 2:
        fila = _read_team_row(tokens, cursor, len(columns))
        if fila is None:
            break
        nombre, numeros, cursor = fila
        filas.append((nombre, numeros))

    if len(filas) < 2:
        return ParseResult(value=None, raw=raw, normalized=normalized,
                           confidence=confidence,
                           reason=f"faltan filas de equipo: {len(filas)} de 2")

    # 3. Cada valor se coloca por el TIPO de su columna, no por su posicion.
    def _repartir(valores: List[int]) -> Tuple[Dict[int, int], Optional[int], Optional[int]]:
        breakdown: Dict[int, int] = {}
        halftime: Optional[int] = None
        total: Optional[int] = None
        for column, valor in zip(columns, valores):
            if column.kind is ColumnKind.PERIOD and column.period is not None:
                breakdown[column.period] = valor
            elif column.kind is ColumnKind.HALFTIME:
                halftime = valor          # acumulado: NUNCA un periodo
            elif column.kind is ColumnKind.TOTAL:
                total = valor
        return breakdown, halftime, total

    (nombre_a, valores_a), (nombre_b, valores_b) = filas[0], filas[1]
    breakdown_a, halftime_a, total_a = _repartir(valores_a)
    breakdown_b, halftime_b, total_b = _repartir(valores_b)

    if any(v > MAX_PERIOD_POINTS for v in list(breakdown_a.values()) + list(breakdown_b.values())):
        return ParseResult(value=None, raw=raw, normalized=normalized, confidence=confidence,
                           reason="puntos por cuarto inverosimiles")
    if any(v is not None and v > MAX_TOTAL_POINTS for v in (total_a, total_b)):
        return ParseResult(value=None, raw=raw, normalized=normalized, confidence=confidence,
                           reason="marcador inverosimil")

    total_from_header = any(c.kind is ColumnKind.TOTAL for c in columns)
    if not total_from_header:
        # Sin columna "Puntos" el total solo se afirma si los parciales lo
        # determinan por completo. Nunca se inventa.
        total_a = _implied_total(breakdown_a)
        total_b = _implied_total(breakdown_b)

    # 4. Cuarto y reloj: se buscan FUERA del encabezado, porque ahi
    #    "Medio tiempo" es una COLUMNA y no la fase del partido.
    contexto = " ".join(tokens[:header_start] + tokens[cursor:])
    period, clock_seconds, phase = _parse_status_line(contexto, regulation_quarters)

    lectura = ScoreboardRead(
        period=period,
        clock_seconds=clock_seconds,
        team_a=nombre_a or None,
        team_b=nombre_b or None,
        score_a=total_a,
        score_b=total_b,
        breakdown_a=breakdown_a,
        breakdown_b=breakdown_b,
        halftime_a=halftime_a,
        halftime_b=halftime_b,
        columns=tuple(columns),
        total_from_header=total_from_header,
        phase=phase,
    )

    # 5. El tablero se valida contra si mismo antes de creerselo.
    problemas = []
    for etiqueta, bd, ht, tot in (("A", breakdown_a, halftime_a, total_a),
                                  ("B", breakdown_b, halftime_b, total_b)):
        motivo = _coherence_problem(bd, ht, tot, halftime_after_period, total_from_header)
        if motivo:
            problemas.append(f"equipo {etiqueta}: {motivo}")

    if problemas:
        # Sospechosa, no descartada: el estabilizador se negara a confirmarla
        # y el estado bueno anterior se queda exactamente como estaba.
        return ParseResult(value=lectura, raw=raw, normalized=normalized,
                           confidence=confidence, suspicious=True,
                           reason="; ".join(problemas))

    return ParseResult(value=lectura, raw=raw, normalized=normalized, confidence=confidence)
