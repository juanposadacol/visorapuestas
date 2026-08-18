"""Umbrales de frescura de los mercados.

La aplicacion lee la PANTALLA. Un mercado que la casa no esta mostrando no
puede considerarse actualizado, por mucho que se leyera hace un momento. Estos
umbrales deciden a partir de cuando una lectura deja de ser reciente y cuando
pasa a estar directamente desactualizada.

Son configurables a proposito: dependen de lo rapido que navegues entre las
pestanas de tu casa y de lo movido que este el partido.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass
class FreshnessCriteria:
    """Cuando una lectura deja de ser fiable como 'lo que hay ahora'."""

    #: Hasta aqui, un mercado no visible se considera RECIENTE.
    recent_after_seconds: float = 5.0
    #: A partir de aqui, DESACTUALIZADO.
    stale_after_seconds: float = 15.0
    #: Pasado este tiempo sin verlo, ni siquiera se conservan sus lineas como
    #: representativas: el mercado pasa a NO DISPONIBLE. 0 = no caducar nunca.
    forget_after_seconds: float = 0.0

    def validate(self) -> "FreshnessCriteria":
        self.recent_after_seconds = max(0.5, float(self.recent_after_seconds))
        self.stale_after_seconds = max(self.recent_after_seconds + 0.5,
                                       float(self.stale_after_seconds))
        self.forget_after_seconds = max(0.0, float(self.forget_after_seconds))
        return self

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FreshnessCriteria":
        criteria = FreshnessCriteria()
        for key, value in (data or {}).items():
            if hasattr(criteria, key):
                setattr(criteria, key, value)
        return criteria.validate()

    def describe(self) -> str:
        return (f"reciente hasta {self.recent_after_seconds:g}s, "
                f"desactualizado a partir de {self.stale_after_seconds:g}s")
