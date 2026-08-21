"""Validacion del payload que envia la extension.

Es la MISMA comprobacion que hace `browser-extension/src/lib/payload.js` antes
de enviar. Duplicarla a proposito en los dos lados no es redundancia inutil:
el navegador puede estar desactualizado, y la aplicacion no debe fiarse de que
lo que llega por el puente venga bien formado.

Reglas de fondo:
* solo se aceptan los campos conocidos; lo demas se rechaza;
* los numeros se comprueban por rango, no solo por tipo;
* nada dudoso entra: si el payload no cumple, no se usa.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

PROTOCOL_VERSION = 1

#: Debe coincidir con MIN_MARKET_CONFIDENCE de payload.js.
MIN_MARKET_CONFIDENCE = 0.9
MAX_LINES = 40

MIN_LINE = 15.0
MAX_LINE = 400.0
MIN_ODDS = 1.01
MAX_ODDS = 100.0

MARKET_TYPES = {"GAME_TOTAL", "HALF_TOTAL", "QUARTER_TOTAL"}

TOP_LEVEL_FIELDS = {"protocol", "source", "observedAt", "event", "visibleMarket",
                    "lines", "gameState"}
EVENT_FIELDS = {"id", "name"}
MARKET_FIELDS = {"marketType", "period", "half", "confidence", "rawTitle", "sidesConfirmed"}
LINE_FIELDS = {"line", "overOdds", "underOdds"}
#: `clock` es el RESTANTE del cuarto, que es lo que usa el motor temporal.
#: `clockRaw` + `clockSemantics` existen porque no todas las casas muestran eso:
#: BetPlay/Kambi muestra el tiempo JUGADO del partido ("Q4 - 33:52"), y
#: convertirlo exige conocer la duracion del cuarto, que la extension no sabe.
GAME_STATE_FIELDS = {"scoreA", "scoreB", "period", "clock", "clockRaw",
                     "clockSemantics", "teamA", "teamB", "confidence"}

#: Que representa el reloj que manda la extension.
CLOCK_SEMANTICS = {"PERIOD_REMAINING", "GAME_ELAPSED"}


class BridgeValidationError(ValueError):
    """El payload recibido no cumple el contrato."""

    def __init__(self, errors: List[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _unknown_fields(data: Dict[str, Any], allowed: set, where: str) -> List[str]:
    sobran = set(data) - allowed
    return [f"campos desconocidos en {where}: {sorted(sobran)}"] if sobran else []


def _check_number(value: Any, minimo: float, maximo: float, nombre: str,
                  errors: List[str], allow_none: bool = False) -> None:
    if value is None:
        if not allow_none:
            errors.append(f"{nombre} ausente")
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{nombre} no es un numero: {value!r}")
        return
    if not (minimo <= float(value) <= maximo):
        errors.append(f"{nombre} fuera de rango [{minimo}, {maximo}]: {value}")


def validate_browser_payload(data: Any) -> Tuple[bool, List[str]]:
    """Comprueba el payload completo. Devuelve (valido, errores)."""
    errors: List[str] = []
    if not isinstance(data, dict):
        return False, ["el payload no es un objeto"]

    errors += _unknown_fields(data, TOP_LEVEL_FIELDS, "el payload")

    if data.get("protocol") != PROTOCOL_VERSION:
        errors.append(f"protocolo desconocido: {data.get('protocol')!r}")
    if data.get("source") != "betplay":
        errors.append(f"fuente desconocida: {data.get('source')!r}")
    if not isinstance(data.get("observedAt"), str) or not data["observedAt"]:
        errors.append("observedAt ausente o invalido")

    evento = data.get("event")
    if evento is not None:
        if not isinstance(evento, dict):
            errors.append("event no es un objeto")
        else:
            errors += _unknown_fields(evento, EVENT_FIELDS, "event")
            for campo in ("id", "name"):
                valor = evento.get(campo)
                if valor is not None and not isinstance(valor, str):
                    errors.append(f"event.{campo} no es texto")
                elif isinstance(valor, str) and len(valor) > 200:
                    errors.append(f"event.{campo} demasiado largo")

    market = data.get("visibleMarket")
    if not isinstance(market, dict):
        errors.append("falta visibleMarket")
    else:
        errors += _unknown_fields(market, MARKET_FIELDS, "visibleMarket")
        tipo = market.get("marketType")
        if tipo not in MARKET_TYPES:
            errors.append(f"marketType desconocido: {tipo!r}")
        periodo = market.get("period")
        mitad = market.get("half")
        if tipo == "QUARTER_TOTAL":
            if not isinstance(periodo, int) or isinstance(periodo, bool) or not (1 <= periodo <= 4):
                errors.append(f"period invalido para QUARTER_TOTAL: {periodo!r}")
        elif periodo is not None:
            errors.append("period solo aplica a QUARTER_TOTAL")
        if tipo == "HALF_TOTAL":
            if mitad not in (1, 2):
                errors.append(f"half invalido para HALF_TOTAL: {mitad!r}")
        elif mitad is not None:
            errors.append("half solo aplica a HALF_TOTAL")
        _check_number(market.get("confidence"), MIN_MARKET_CONFIDENCE, 1.0,
                      "visibleMarket.confidence", errors)
        titulo = market.get("rawTitle")
        if titulo is not None and (not isinstance(titulo, str) or len(titulo) > 200):
            errors.append("rawTitle invalido")

    lineas = data.get("lines")
    if not isinstance(lineas, list) or not lineas:
        errors.append("sin lineas")
    elif len(lineas) > MAX_LINES:
        errors.append(f"demasiadas lineas: {len(lineas)}")
    else:
        for indice, linea in enumerate(lineas):
            if not isinstance(linea, dict):
                errors.append(f"linea {indice} no es un objeto")
                continue
            errors += _unknown_fields(linea, LINE_FIELDS, f"lines[{indice}]")
            _check_number(linea.get("line"), MIN_LINE, MAX_LINE, f"lines[{indice}].line", errors)
            for lado in ("overOdds", "underOdds"):
                _check_number(linea.get(lado), MIN_ODDS, MAX_ODDS,
                              f"lines[{indice}].{lado}", errors, allow_none=True)
            if linea.get("overOdds") is None and linea.get("underOdds") is None:
                errors.append(f"lines[{indice}] sin ninguna cuota")

    estado = data.get("gameState")
    if estado is not None:
        if not isinstance(estado, dict):
            errors.append("gameState no es un objeto")
        else:
            errors += _unknown_fields(estado, GAME_STATE_FIELDS, "gameState")
            for campo in ("scoreA", "scoreB"):
                valor = estado.get(campo)
                if valor is None:
                    continue
                if isinstance(valor, bool) or not isinstance(valor, int) or not (0 <= valor <= 300):
                    errors.append(f"gameState.{campo} invalido: {valor!r}")
            periodo = estado.get("period")
            if periodo is not None and (isinstance(periodo, bool) or
                                        not isinstance(periodo, int) or not (1 <= periodo <= 9)):
                errors.append(f"gameState.period invalido: {periodo!r}")
            import re
            for campo in ("clock", "clockRaw"):
                reloj = estado.get(campo)
                if reloj is None:
                    continue
                if not isinstance(reloj, str) or not re.fullmatch(r"\d{1,3}:[0-5]\d", reloj):
                    errors.append(f"gameState.{campo} invalido: {reloj!r}")
            semantica = estado.get("clockSemantics")
            if semantica is not None and semantica not in CLOCK_SEMANTICS:
                errors.append(f"gameState.clockSemantics invalida: {semantica!r}")
            if estado.get("clockRaw") is not None and semantica is None:
                errors.append("gameState.clockRaw sin clockSemantics: no se puede interpretar")

    return (not errors), errors


def ensure_valid(data: Any) -> Dict[str, Any]:
    """Devuelve el payload validado o lanza BridgeValidationError."""
    valido, errores = validate_browser_payload(data)
    if not valido:
        raise BridgeValidationError(errores)
    return data
