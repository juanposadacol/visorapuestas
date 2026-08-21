"""Traduccion del payload del navegador a los objetos del dominio.

Regla del proyecto: NO se crea un modelo paralelo para los datos del
navegador. Lo que llega por el puente acaba siendo exactamente los mismos
`MarketKey`, `MarketLine` y `MarketSnapshot` que ya usan el radar y las
metricas, de modo que el motor no sabe ni le importa de donde salieron.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..domain.market import MarketKey, MarketLine, MarketSnapshot, MarketType

DEFAULT_SPORTSBOOK = "BetPlay"


def parse_observed_at(value: Any) -> float:
    """Convierte el ISO-8601 del navegador a epoch. Si falla, usa el ahora."""
    if isinstance(value, str) and value:
        texto = value.replace("Z", "+00:00")
        try:
            momento = datetime.fromisoformat(texto)
        except ValueError:
            return time.time()
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        return momento.timestamp()
    return time.time()


def payload_to_market_key(payload: Dict[str, Any]) -> MarketKey:
    """Traduce el mercado del cable a la clave del dominio."""
    market = payload.get("visibleMarket") or {}
    tipo = market.get("marketType")
    if tipo == "QUARTER_TOTAL":
        return MarketKey.quarter(int(market["period"]))
    if tipo == "HALF_TOTAL":
        return MarketKey.half_market(int(market["half"]))
    if tipo == "GAME_TOTAL":
        return MarketKey.game()
    raise ValueError(f"marketType no soportado: {tipo!r}")


def event_name(payload: Dict[str, Any]) -> str:
    evento = payload.get("event") or {}
    return str(evento.get("name") or "")


def event_id(payload: Dict[str, Any]) -> Optional[str]:
    evento = payload.get("event") or {}
    identificador = evento.get("id")
    return str(identificador) if identificador else None


def payload_to_snapshot(payload: Dict[str, Any],
                        sportsbook: str = DEFAULT_SPORTSBOOK) -> MarketSnapshot:
    """Construye el MarketSnapshot que consume el radar."""
    key = payload_to_market_key(payload)
    observado = parse_observed_at(payload.get("observedAt"))
    nombre = event_name(payload)

    lineas: List[MarketLine] = []
    for entrada in payload.get("lines") or []:
        lineas.append(MarketLine(
            sportsbook=sportsbook,
            event=nombre,
            key=key,
            line=float(entrada["line"]),
            over_odds=None if entrada.get("overOdds") is None else float(entrada["overOdds"]),
            under_odds=None if entrada.get("underOdds") is None else float(entrada["underOdds"]),
            timestamp=observado,
            # Viene del DOM y ya ha pasado dos validaciones: se considera
            # confirmada, a diferencia de una lectura de OCR recien hecha.
            confirmed=True,
            raw_text=str((payload.get("visibleMarket") or {}).get("rawTitle") or ""),
        ))

    return MarketSnapshot(key=key, lines=lineas, timestamp=observado, suspended=False,
                          raw_text=str((payload.get("visibleMarket") or {}).get("rawTitle") or ""))


def sides_confirmed(payload: Dict[str, Any]) -> bool:
    """False si el reparto OVER/UNDER salio de la posicion y no de una palabra."""
    return bool((payload.get("visibleMarket") or {}).get("sidesConfirmed"))


def market_confidence(payload: Dict[str, Any]) -> float:
    try:
        return float((payload.get("visibleMarket") or {}).get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def payload_to_game_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Campos del estado del partido que trae el DOM, si es que trae alguno.

    Devuelve un diccionario con solo las claves presentes. El reloj se entrega
    ya convertido a segundos, que es como razona todo el motor temporal.
    """
    estado = payload.get("gameState")
    if not isinstance(estado, dict):
        return {}

    from ..domain.time_utils import try_clock_to_seconds

    salida: Dict[str, Any] = {}
    for origen, destino in (("scoreA", "score_a"), ("scoreB", "score_b"),
                            ("period", "period")):
        valor = estado.get(origen)
        if isinstance(valor, int) and not isinstance(valor, bool):
            salida[destino] = valor
    reloj = estado.get("clock")
    if isinstance(reloj, str):
        segundos = try_clock_to_seconds(reloj)
        if segundos is not None:
            salida["clock_seconds"] = segundos

    # Reloj en OTRA semantica: viaja crudo y lo convierte quien conoce las
    # reglas de la competicion (el lector, con su GameRules). Aqui solo se
    # traslada, porque este modulo no sabe cuanto dura un cuarto.
    crudo = estado.get("clockRaw")
    semantica = estado.get("clockSemantics")
    if isinstance(crudo, str) and isinstance(semantica, str):
        segundos = try_clock_to_seconds(crudo)
        if segundos is not None:
            salida["clock_raw_seconds"] = segundos
            salida["clock_semantics"] = semantica
    for origen, destino, periodos_destino in (
            ("teamA", "team_a", "periods_a"),
            ("teamB", "team_b", "periods_b")):
        valor = estado.get(origen)
        if isinstance(valor, str) and valor.strip():
            salida[destino] = valor.strip()[:60]
            continue
        if not isinstance(valor, dict):
            continue
        nombre = valor.get("name")
        if isinstance(nombre, str) and nombre.strip():
            salida[destino] = nombre.strip()[:60]
        periodos = valor.get("periods")
        if isinstance(periodos, dict):
            salida[periodos_destino] = {
                str(label): (points if isinstance(points, int) and not isinstance(points, bool)
                             else None)
                for label, points in periodos.items()
            }
    return salida


def describe_payload(payload: Dict[str, Any]) -> str:
    """Resumen corto para el log de diagnostico."""
    try:
        key = payload_to_market_key(payload)
        etiqueta = key.label
    except ValueError:
        etiqueta = "mercado desconocido"
    lineas = payload.get("lines") or []
    return f"{etiqueta}: {len(lineas)} linea(s)"
