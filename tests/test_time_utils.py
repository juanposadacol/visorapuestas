"""Requisito 31: el tiempo se maneja en segundos y se convierte bien a decimales."""

import pytest

from visorunder.domain.time_utils import (
    ClockFormatError,
    clock_to_seconds,
    decimal_minutes_to_seconds,
    format_optional_clock,
    seconds_to_clock,
    seconds_to_decimal_minutes,
    try_clock_to_seconds,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("05:28", 328),
        ("5:28", 328),
        ("10:00", 600),
        ("00:00", 0),
        ("12:00", 720),
        ("00:01", 1),
        (" 04:32 ", 272),
    ],
)
def test_clock_to_seconds(text, expected):
    assert clock_to_seconds(text) == expected


def test_clock_with_tenths_last_minute():
    # Muchas casas muestran decimas en el ultimo minuto: "28.4"
    assert clock_to_seconds("28.4") == 28
    assert clock_to_seconds("9,7") == 9


@pytest.mark.parametrize("text", ["", "  ", None, "abc", "05:75", "1:2:3", "99:99"])
def test_clock_invalid_raises(text):
    with pytest.raises(ClockFormatError):
        clock_to_seconds(text)


def test_try_clock_returns_none_instead_of_guessing():
    assert try_clock_to_seconds("basura") is None


@pytest.mark.parametrize("seconds,expected", [(328, "05:28"), (272, "04:32"), (928, "15:28"), (0, "00:00"), (2060, "34:20")])
def test_seconds_to_clock(seconds, expected):
    assert seconds_to_clock(seconds) == expected


def test_decimal_minutes_never_confuses_seconds_with_decimals():
    # 6:30 son 6.5 minutos, NO 6.30
    assert seconds_to_decimal_minutes(390) == 6.5
    # 5:28 -> 5 + 28/60
    assert seconds_to_decimal_minutes(328) == pytest.approx(5.466666, abs=1e-4)
    # 4:32 -> 4 + 32/60
    assert seconds_to_decimal_minutes(272) == pytest.approx(4.533333, abs=1e-4)


def test_decimal_minutes_roundtrip():
    assert decimal_minutes_to_seconds(seconds_to_decimal_minutes(328)) == 328


def test_format_optional_clock_shows_placeholder():
    assert format_optional_clock(None) == "--"
    assert format_optional_clock(328) == "05:28"
