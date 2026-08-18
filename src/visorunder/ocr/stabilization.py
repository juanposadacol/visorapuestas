"""Estabilizacion de lecturas OCR (requisitos 20, 21 y 37).

Modelo RAW -> CONFIRMED:

    lectura 1: 40.5   (RAW, 1/3)
    lectura 2: 40.5   (RAW, 2/3)
    lectura 3: 40.5   -> CONFIRMED 40.5

Ademas de exigir repeticiones, cada campo tiene un VALIDADOR que conoce la
fisica del dato: el marcador no baja, el reloj no sube dentro del cuarto, etc.
Un valor que el validador considera improbable no se descarta para siempre:
se le exige MAS insistencia (confianza temporal). Asi un 86 aislado entre
lecturas de 36 se ignora, pero un marcador que realmente salto porque la app
estuvo pausada acaba aceptandose.

Un valor confirmado CADUCA (`ttl`). Si el OCR se pierde, el dato deja de ser
fiable y la interfaz vuelve a "--" en vez de congelar un numero viejo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

from ..domain.values import Observed, ValueStatus
from ..parsers.base import ParseResult

T = TypeVar("T")


@dataclass(frozen=True)
class Verdict:
    """Resultado de validar un candidato contra el valor ya confirmado."""

    ok: bool = True
    reason: str = ""
    extra_confirmations: int = 0
    hard: bool = False  # imposible por definicion: no se acepta ni insistiendo

    @staticmethod
    def accept() -> "Verdict":
        return Verdict(True, "", 0)

    @staticmethod
    def doubt(reason: str, extra: int = 2) -> "Verdict":
        """Sospechoso: se acepta solo si insiste mas veces."""
        return Verdict(True, reason, extra)

    @staticmethod
    def reject(reason: str, extra: int = 6) -> "Verdict":
        """Improbable: hace falta mucha insistencia para aceptarlo."""
        return Verdict(False, reason, extra)

    @staticmethod
    def forbid(reason: str) -> "Verdict":
        """Imposible: por mucho que se repita, jamas se confirma."""
        return Verdict(False, reason, 0, hard=True)


Validator = Callable[[Any, Optional[Any]], Verdict]

#: Atajo de "confianza temporal": (candidato, confirmado, segundos transcurridos)
#: -> True si el valor es COHERENTE con la evolucion esperada y puede
#: confirmarse sin esperar repeticiones. Lo usa el reloj, que por naturaleza
#: cambia en cada lectura y nunca se repetiria lo suficiente.
FastPath = Callable[[Any, Any, float], bool]


@dataclass
class StabilizerStats:
    submissions: int = 0
    confirmations: int = 0
    rejections: int = 0
    misses: int = 0
    last_reason: str = ""
    last_raw: str = ""
    last_normalized: str = ""


class Stabilizer(Generic[T]):
    """Convierte una secuencia de lecturas en un valor confirmado."""

    def __init__(self, name: str, *, required: int = 3, ttl: float = 3.0,
                 validator: Optional[Validator] = None, stubborn_extra: int = 6,
                 min_confidence: float = 0.0,
                 fast_path: Optional[FastPath] = None) -> None:
        self.name = name
        self.required = max(1, int(required))
        self.ttl = float(ttl)
        self.validator = validator
        self.stubborn_extra = int(stubborn_extra)
        self.min_confidence = float(min_confidence)
        self.fast_path = fast_path

        self._confirmed: Observed[T] = Observed.unknown()
        self._pending: Optional[T] = None
        self._pending_count: int = 0
        self._pending_needed: int = self.required
        self._pending_result: Optional[ParseResult] = None
        self.stats = StabilizerStats()

    # ------------------------------------------------------------------ API
    @property
    def confirmed(self) -> Observed[T]:
        return self._confirmed

    @property
    def pending(self) -> Optional[T]:
        return self._pending

    @property
    def progress(self) -> str:
        if self._pending is None:
            return ""
        return f"{self._pending_count}/{self._pending_needed}"

    def current(self, now: Optional[float] = None) -> Observed[T]:
        """Valor vigente, caducando el confirmado si esta obsoleto."""
        now = now if now is not None else time.time()
        obs = self._confirmed
        if obs.status is ValueStatus.CONFIRMED and self.ttl > 0 and obs.is_stale(self.ttl, now):
            self._confirmed = Observed.unknown()
        return self._confirmed

    def set_manual(self, value: T) -> Observed[T]:
        """Valor introducido por el usuario: fiable de inmediato."""
        self._confirmed = Observed.manual(value)
        self._pending = None
        self._pending_count = 0
        return self._confirmed

    def reset(self) -> None:
        self._confirmed = Observed.unknown()
        self._pending = None
        self._pending_count = 0
        self._pending_result = None

    def submit(self, result: ParseResult, now: Optional[float] = None) -> Observed[T]:
        """Entrega una lectura al estabilizador y devuelve el valor vigente."""
        now = now if now is not None else time.time()
        self.stats.submissions += 1
        self.stats.last_raw = result.raw
        self.stats.last_normalized = result.normalized

        # Lectura inutilizable: no toca el valor confirmado, solo lo deja envejecer.
        if result.value is None:
            self.stats.misses += 1
            self.stats.last_reason = result.reason or "sin valor"
            self._pending = None
            self._pending_count = 0
            return self.current(now)

        if result.suspicious:
            self.stats.misses += 1
            self.stats.last_reason = result.reason or "lectura sospechosa"
            return self.current(now)

        if self.min_confidence > 0.0 and result.confidence < self.min_confidence:
            self.stats.misses += 1
            self.stats.last_reason = f"confianza {result.confidence:.2f} < {self.min_confidence:.2f}"
            return self.current(now)

        candidate = result.value
        confirmed_value = self._confirmed.usable_value()

        if candidate == confirmed_value:
            # Refresca la frescura del dato ya confirmado.
            self._confirmed = Observed(
                value=confirmed_value,
                status=self._confirmed.status,
                confidence=max(self._confirmed.confidence, result.confidence),
                raw_text=result.raw,
                updated_at=now,
                source=self.name,
            )
            self._pending = None
            self._pending_count = 0
            self.stats.last_reason = ""
            return self._confirmed

        # Confianza temporal: un valor coherente con la evolucion esperada del
        # dato ya confirmado se acepta sin exigir repeticiones. Sin esto el
        # reloj no podria refrescarse segundo a segundo (requisito 4).
        if (self.fast_path is not None and confirmed_value is not None
                and self.fast_path(candidate, confirmed_value,
                                   now - self._confirmed.updated_at)):
            self._confirmed = Observed(
                value=candidate, status=ValueStatus.CONFIRMED,
                confidence=result.confidence, raw_text=result.raw,
                updated_at=now, source=self.name)
            self.stats.confirmations += 1
            self.stats.last_reason = ""
            self._pending = None
            self._pending_count = 0
            return self._confirmed

        verdict = self.validator(candidate, confirmed_value) if self.validator else Verdict.accept()
        if verdict.hard:
            # Valor imposible (fuera de rango): se descarta siempre.
            self.stats.rejections += 1
            self.stats.last_reason = verdict.reason
            self._pending = None
            self._pending_count = 0
            return self.current(now)
        needed = self.required + verdict.extra_confirmations
        if not verdict.ok:
            needed = max(needed, self.required + self.stubborn_extra)
            self.stats.rejections += 1

        if candidate == self._pending:
            self._pending_count += 1
        else:
            self._pending = candidate
            self._pending_count = 1
        self._pending_needed = needed
        self._pending_result = result
        self.stats.last_reason = verdict.reason

        if self._pending_count >= needed:
            self._confirmed = Observed(
                value=candidate,
                status=ValueStatus.CONFIRMED,
                confidence=result.confidence,
                raw_text=result.raw,
                updated_at=now,
                source=self.name,
            )
            self.stats.confirmations += 1
            self._pending = None
            self._pending_count = 0
            return self._confirmed

        return self.current(now)


# --------------------------------------------------------------------------
# Validadores concretos (requisito 21)
# --------------------------------------------------------------------------
def score_validator(max_jump: int = 6) -> Validator:
    """El marcador no baja y sube de a pocos puntos.

    36, 36, 86, 36  ->  el 86 no se acepta automaticamente.
    """

    def _validate(candidate: int, confirmed: Optional[int]) -> Verdict:
        if confirmed is None:
            return Verdict.accept()
        delta = int(candidate) - int(confirmed)
        if delta < 0:
            return Verdict.reject(f"el marcador bajaria {confirmed} -> {candidate}")
        if delta > max_jump:
            return Verdict.doubt(f"salto grande {confirmed} -> {candidate}", extra=3)
        return Verdict.accept()

    return _validate


def clock_validator(period_seconds_getter: Callable[[], Optional[int]],
                    max_backward_jump: int = 90) -> Validator:
    """El reloj baja dentro del cuarto; solo sube al empezar uno nuevo."""

    def _validate(candidate: int, confirmed: Optional[int]) -> Verdict:
        if confirmed is None:
            return Verdict.accept()
        if candidate <= confirmed:
            # Baja o se detiene: comportamiento normal.
            if confirmed - candidate > max_backward_jump:
                return Verdict.doubt(f"salto atras de {confirmed - candidate}s", extra=2)
            return Verdict.accept()
        period_seconds = period_seconds_getter()
        if period_seconds and candidate >= period_seconds - 5 and confirmed <= 5:
            # 00:02 -> 00:01 -> 00:00 -> 10:00: cambio de cuarto.
            return Verdict.doubt("posible inicio de cuarto", extra=1)
        return Verdict.reject(f"el reloj subiria {confirmed} -> {candidate}")

    return _validate


def period_validator(regulation_quarters: int = 4, max_period: int = 9) -> Validator:
    """El cuarto avanza de uno en uno y nunca retrocede."""

    def _validate(candidate: int, confirmed: Optional[int]) -> Verdict:
        if not (1 <= int(candidate) <= max_period):
            return Verdict.forbid(f"cuarto fuera de rango: {candidate}")
        if confirmed is None:
            return Verdict.accept()
        delta = int(candidate) - int(confirmed)
        if delta < 0:
            return Verdict.reject(f"el cuarto retrocederia {confirmed} -> {candidate}")
        if delta > 1:
            return Verdict.doubt(f"salto de cuarto {confirmed} -> {candidate}", extra=3)
        return Verdict.accept()

    return _validate


def line_validator(max_move: float = 20.0) -> Validator:
    """Las lineas se mueven poco a poco; un salto enorme es sospechoso."""

    def _validate(candidate: float, confirmed: Optional[float]) -> Verdict:
        if confirmed is None:
            return Verdict.accept()
        if abs(float(candidate) - float(confirmed)) > max_move:
            return Verdict.doubt(f"movimiento de linea grande {confirmed} -> {candidate}", extra=2)
        return Verdict.accept()

    return _validate


def clock_fast_path(tolerance_seconds: float = 3.0) -> FastPath:
    """Confianza temporal del reloj (requisito 20).

    El reloj de un partido no se repite entre lecturas: baja continuamente.
    Exigirle N lecturas identicas lo dejaria congelado. En su lugar se acepta
    de inmediato la lectura que sea COHERENTE con el tiempo real transcurrido:

        confirmado - transcurrido - tolerancia  <=  candidato  <=  confirmado

    Un reloj parado (tiempo muerto, falta) tambien encaja, porque el candidato
    puede ser igual al confirmado. Cualquier lectura fuera de esa ventana cae
    en el camino lento y necesita repetirse para confirmarse.
    """

    def _coherent(candidate: int, confirmed: int, elapsed: float) -> bool:
        if candidate > confirmed:
            return False  # subir es cosa del cambio de cuarto: camino lento
        expected_min = confirmed - elapsed - tolerance_seconds
        return candidate >= expected_min

    return _coherent
