"""Requisitos 20, 21 y 37: nada dudoso llega a los calculos."""

import pytest

from visorunder.domain.values import ValueStatus
from visorunder.ocr.stabilization import (
    Stabilizer,
    clock_validator,
    line_validator,
    period_validator,
    score_validator,
)
from visorunder.parsers.base import ParseResult


def _r(value, suspicious=False, confidence=0.9):
    return ParseResult(value=value, raw=str(value), normalized=str(value),
                       confidence=confidence, suspicious=suspicious)


def test_confirma_tras_tres_lecturas_iguales():
    s = Stabilizer("linea", required=3, ttl=10)
    assert s.submit(_r(40.5)).status is ValueStatus.UNKNOWN
    assert s.submit(_r(40.5)).status is ValueStatus.UNKNOWN
    obs = s.submit(_r(40.5))
    assert obs.status is ValueStatus.CONFIRMED and obs.value == 40.5


def test_lecturas_inestables_no_confirman_nada():
    s = Stabilizer("linea", required=3, ttl=10)
    for value in (40.5, 41.5, 40.5, 42.5):
        assert s.submit(_r(value)).status is ValueStatus.UNKNOWN


def test_lectura_sospechosa_nunca_confirma():
    s = Stabilizer("cuota", required=2, ttl=10)
    for _ in range(10):
        obs = s.submit(_r(1.87, suspicious=True))
    assert obs.status is ValueStatus.UNKNOWN


def test_valor_confirmado_caduca():
    s = Stabilizer("reloj", required=1, ttl=1.0)
    s.submit(_r(328), now=1000.0)
    assert s.current(now=1000.5).status is ValueStatus.CONFIRMED
    assert s.current(now=1002.0).status is ValueStatus.UNKNOWN


def test_lectura_perdida_no_borra_de_inmediato():
    s = Stabilizer("reloj", required=1, ttl=5.0)
    s.submit(_r(328), now=1000.0)
    fallo = ParseResult(value=None, raw="???", reason="sin texto")
    obs = s.submit(fallo, now=1001.0)
    assert obs.status is ValueStatus.CONFIRMED and obs.value == 328


def test_marcador_ignora_el_valor_absurdo_aislado():
    """36, 36, 86, 36 -> el 86 no se acepta."""
    s = Stabilizer("marcador", required=2, ttl=30, validator=score_validator())
    s.submit(_r(36)); s.submit(_r(36))
    assert s.confirmed.value == 36
    s.submit(_r(86))
    assert s.confirmed.value == 36
    s.submit(_r(36))
    assert s.confirmed.value == 36


def test_marcador_acepta_un_salto_real_si_insiste():
    s = Stabilizer("marcador", required=2, ttl=30, validator=score_validator(), stubborn_extra=4)
    s.submit(_r(36)); s.submit(_r(36))
    for _ in range(8):
        s.submit(_r(50))
    assert s.confirmed.value == 50


def test_marcador_no_retrocede_facilmente():
    s = Stabilizer("marcador", required=2, ttl=30, validator=score_validator())
    s.submit(_r(40)); s.submit(_r(40))
    s.submit(_r(4)); s.submit(_r(4)); s.submit(_r(4))
    assert s.confirmed.value == 40


def test_marcador_sube_normalmente():
    s = Stabilizer("marcador", required=2, ttl=30, validator=score_validator())
    s.submit(_r(40)); s.submit(_r(40))
    s.submit(_r(43)); s.submit(_r(43))
    assert s.confirmed.value == 43


def test_reloj_baja_sin_problema_y_no_sube_a_capricho():
    s = Stabilizer("reloj", required=2, ttl=30, validator=clock_validator(lambda: 600))
    s.submit(_r(328)); s.submit(_r(328))
    s.submit(_r(327)); s.submit(_r(327))
    assert s.confirmed.value == 327
    s.submit(_r(500)); s.submit(_r(500))
    assert s.confirmed.value == 327


def test_reloj_reinicia_al_empezar_cuarto_nuevo():
    """00:02 -> 00:01 -> 00:00 -> 10:00 indica cambio de cuarto."""
    s = Stabilizer("reloj", required=2, ttl=30, validator=clock_validator(lambda: 600))
    for v in (2, 2, 1, 1, 0, 0):
        s.submit(_r(v))
    assert s.confirmed.value == 0
    for _ in range(3):
        s.submit(_r(600))
    assert s.confirmed.value == 600


def test_cuarto_avanza_pero_no_retrocede():
    s = Stabilizer("cuarto", required=2, ttl=30, validator=period_validator())
    s.submit(_r(2)); s.submit(_r(2))
    s.submit(_r(3)); s.submit(_r(3))
    assert s.confirmed.value == 3
    s.submit(_r(1)); s.submit(_r(1)); s.submit(_r(1))
    assert s.confirmed.value == 3


def test_cuarto_fuera_de_rango_se_rechaza():
    s = Stabilizer("cuarto", required=2, ttl=30, validator=period_validator())
    for _ in range(20):
        s.submit(_r(0))
    assert s.confirmed.value is None


def test_valor_manual_es_fiable_de_inmediato():
    s = Stabilizer("marcador", required=5, ttl=30)
    obs = s.set_manual(33)
    assert obs.status is ValueStatus.MANUAL and obs.is_usable


def test_linea_con_salto_enorme_necesita_insistir():
    s = Stabilizer("linea", required=2, ttl=30, validator=line_validator(max_move=10))
    s.submit(_r(40.5)); s.submit(_r(40.5))
    s.submit(_r(140.5)); s.submit(_r(140.5))
    assert s.confirmed.value == 40.5
    for _ in range(3):
        s.submit(_r(140.5))
    assert s.confirmed.value == 140.5


def test_estadisticas_para_diagnostico():
    s = Stabilizer("marcador", required=2, ttl=30, validator=score_validator())
    s.submit(_r(36)); s.submit(_r(36)); s.submit(_r(10))
    assert s.stats.submissions == 3
    assert s.stats.confirmations == 1
    assert s.stats.rejections == 1
    assert "bajaria" in s.stats.last_reason
