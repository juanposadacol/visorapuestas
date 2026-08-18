"""Utilidades de tiempo.

REGLA FUNDAMENTAL DEL PROYECTO (requisito 31):
toda la logica interna trabaja en SEGUNDOS ENTEROS.
La conversion a minutos decimales se hace UNICAMENTE al calcular ratios
(puntos por minuto), nunca para almacenar ni comparar tiempos.

Error clasico que estas funciones evitan:
    "06:30" NO es 6.30 minutos, es 6.5 minutos.
"""

from __future__ import annotations

import re
from typing import Optional

#: Formatos aceptados al parsear un reloj de partido.
#: - "05:28"  -> 328 s
#: - "5:28"   -> 328 s
#: - "12:00"  -> 720 s
#: - "28.4"   -> ultimo minuto en algunas casas (28.4 s) -> 28 s
_CLOCK_MMSS = re.compile(r"^(\d{1,3}):(\d{1,2})$")
_CLOCK_TENTHS = re.compile(r"^(\d{1,2})[.,](\d)$")
_CLOCK_ONLY_SECONDS = re.compile(r"^(\d{1,2})$")

MAX_REASONABLE_CLOCK_SECONDS = 3600  # 60 min: cota de cordura, no regla de juego


class ClockFormatError(ValueError):
    """El texto recibido no representa un reloj valido."""


def clock_to_seconds(text: str, *, allow_tenths: bool = True) -> int:
    """Convierte un reloj de partido a segundos enteros.

    >>> clock_to_seconds("05:28")
    328
    >>> clock_to_seconds("10:00")
    600
    >>> clock_to_seconds("00:00")
    0

    En el ultimo minuto muchas casas muestran decimas ("28.4"). Se trunca
    a segundos enteros porque la aplicacion razona siempre en segundos.

    Lanza ClockFormatError si el texto no es un reloj valido. Nunca devuelve
    un valor "adivinado": si no se puede leer con seguridad, es un error y el
    llamador debe tratarlo como dato NO DISPONIBLE (requisito 33).
    """
    if text is None:
        raise ClockFormatError("reloj vacio")
    raw = str(text).strip()
    if not raw:
        raise ClockFormatError("reloj vacio")

    m = _CLOCK_MMSS.match(raw)
    if m:
        minutes = int(m.group(1))
        seconds = int(m.group(2))
        # Requisito 21: los segundos de un reloj MM:SS van de 00 a 59.
        if seconds > 59:
            raise ClockFormatError(f"segundos fuera de rango en {raw!r}")
        total = minutes * 60 + seconds
        if total > MAX_REASONABLE_CLOCK_SECONDS:
            raise ClockFormatError(f"reloj inverosimil: {raw!r}")
        return total

    if allow_tenths:
        m = _CLOCK_TENTHS.match(raw)
        if m:
            return int(m.group(1))

    m = _CLOCK_ONLY_SECONDS.match(raw)
    if m:
        seconds = int(m.group(1))
        if seconds > 59:
            raise ClockFormatError(f"segundos fuera de rango en {raw!r}")
        return seconds

    raise ClockFormatError(f"formato de reloj no reconocido: {raw!r}")


def try_clock_to_seconds(text: str) -> Optional[int]:
    """Version tolerante: devuelve None en lugar de lanzar."""
    try:
        return clock_to_seconds(text)
    except ClockFormatError:
        return None


def seconds_to_clock(seconds: int) -> str:
    """Formatea segundos como MM:SS (o HH:MM:SS jamas: aqui MM puede pasar de 59).

    >>> seconds_to_clock(328)
    '05:28'
    >>> seconds_to_clock(928)
    '15:28'
    >>> seconds_to_clock(0)
    '00:00'
    """
    if seconds is None:
        raise ValueError("seconds es None")
    total = int(seconds)
    if total < 0:
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def seconds_to_decimal_minutes(seconds: int) -> float:
    """Convierte segundos a minutos DECIMALES para usar en ratios.

    >>> round(seconds_to_decimal_minutes(328), 4)
    5.4667
    >>> seconds_to_decimal_minutes(390)
    6.5
    """
    return int(seconds) / 60.0


def decimal_minutes_to_seconds(minutes: float) -> int:
    """Inversa de seconds_to_decimal_minutes, redondeando al segundo."""
    return int(round(float(minutes) * 60.0))


def format_optional_clock(seconds: Optional[int], placeholder: str = "--") -> str:
    """Formatea un reloj que puede ser desconocido (requisito 33)."""
    if seconds is None:
        return placeholder
    return seconds_to_clock(seconds)
