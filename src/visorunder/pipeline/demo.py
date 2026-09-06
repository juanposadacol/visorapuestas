"""Modo demostracion: partido simulado sin tocar la pantalla.

Sirve para dos cosas muy practicas:

* probar la interfaz y comprobar los calculos sin tener abierta una casa de
  apuestas ni haber configurado todavia las regiones;
* ejecutar pruebas automaticas del programa completo.

El simulador alimenta el MISMO pipeline que en produccion (parsers,
validadores, estabilizador, metricas). Lo unico que cambia es el origen del
texto: en vez del OCR sobre la pantalla, lo genera este modulo.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

from ..capture.roi import Rect, RoiKind
from ..config.profiles import SportsbookProfile
from ..domain.rules import FIBA, GameRules
from ..domain.time_utils import seconds_to_clock
from ..ocr.engines.stub_engine import StubEngine


@dataclass
class DemoGame:
    """Partido sintetico: el reloj corre y los equipos anotan."""

    rules: GameRules = FIBA
    period: int = 3
    clock_seconds: int = 328
    score_a: int = 43
    score_b: int = 31
    team_a: str = "CAL IRVINE"
    team_b: str = "CHINESE TAIPEI"
    market_period: int = 3
    lines: Tuple[float, ...] = (37.5, 38.5, 39.5, 40.5)
    #: Pestana que la casa esta mostrando: "QUARTER", "GAME", "HALF1", "HALF2".
    visible_tab: str = "QUARTER"
    game_lines: Tuple[float, ...] = (176.5, 178.5, 180.5, 182.5)
    half_lines: Tuple[float, ...] = (78.5, 80.5, 82.5)
    speed: float = 1.0
    seed: int = 7
    _rng: random.Random = field(default=None, repr=False)
    _last_tick: float = field(default_factory=time.time, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def advance(self, now: Optional[float] = None) -> None:
        """Hace correr el reloj y anotar puntos de vez en cuando."""
        now = now if now is not None else time.time()
        elapsed = (now - self._last_tick) * self.speed
        if elapsed < 1.0:
            return
        steps = int(elapsed)
        self._last_tick = now

        for _ in range(steps):
            if self.clock_seconds <= 0:
                self._next_period()
                continue
            self.clock_seconds -= 1
            if self._rng.random() < 0.05:
                points = self._rng.choice([2, 2, 2, 3, 1])
                if self._rng.random() < 0.5:
                    self.score_a += points
                else:
                    self.score_b += points

    def _next_period(self) -> None:
        self.period += 1
        self.clock_seconds = self.rules.period_seconds(self.period)
        self.market_period = self.period

    # -------------------------------------------------------------- textos
    def text_for(self, roi_kind: str) -> Optional[Tuple[str, float]]:
        """Devuelve (texto, confianza) como lo haria un OCR real."""
        self.advance()
        confidence = 0.93
        if roi_kind == RoiKind.CLOCK.value:
            return (seconds_to_clock(self.clock_seconds), confidence)
        if roi_kind == RoiKind.PERIOD.value:
            return (self.rules.label(self.period), confidence)
        if roi_kind == RoiKind.SCORE_PAIR.value:
            return (f"{self.score_a} - {self.score_b}", confidence)
        if roi_kind == RoiKind.TEAM_A.value:
            return (self.team_a, confidence)
        if roi_kind == RoiKind.TEAM_B.value:
            return (self.team_b, confidence)
        if roi_kind == RoiKind.MARKET_LABEL.value:
            return (self._label_text(), confidence)
        if roi_kind == RoiKind.MARKET_BLOCK.value:
            return (self._market_text(), confidence)
        return ("", 0.0)

    def show_tab(self, tab: str) -> None:
        """Simula que el usuario pincha otra pestana de la casa."""
        self.visible_tab = tab

    def _label_text(self) -> str:
        if self.visible_tab == "GAME":
            return "Partido - Total de puntos"
        if self.visible_tab == "HALF1":
            return "1.a mitad - Total de puntos"
        if self.visible_tab == "HALF2":
            return "2.a mitad - Total de puntos"
        return f"{self.market_period}.er Cuarto - Total de puntos"

    def _visible_lines(self) -> Tuple[float, ...]:
        if self.visible_tab == "GAME":
            return self.game_lines
        if self.visible_tab in ("HALF1", "HALF2"):
            return self.half_lines
        return self.lines

    def _market_text(self) -> str:
        rows = []
        for index, line in enumerate(self._visible_lines()):
            over = 1.55 + index * 0.13
            under = 2.25 - index * 0.17
            rows.append(f"{line:g} OVER {over:.2f} UNDER {under:.2f}")
        return "\n".join(rows)

    def move_lines(self, delta: float) -> None:
        """Simula que la casa mueve todas sus lineas (requisito 7)."""
        self.lines = tuple(round(line + delta, 1) for line in self.lines)


def demo_engine(game: DemoGame) -> StubEngine:
    return StubEngine(provider=game.text_for)


def demo_profile(name: str = "DEMO (partido simulado)") -> SportsbookProfile:
    """Perfil ficticio con todas las regiones definidas.

    Las coordenadas no importan: la captura es nula y el texto lo pone el
    simulador. Sirve para arrancar la aplicacion sin configurar nada.
    """
    profile = SportsbookProfile(name=name, sportsbook="DEMO", frame=Rect(0, 0, 1920, 1080))
    boxes = {
        RoiKind.CLOCK: Rect(100, 100, 120, 40),
        RoiKind.PERIOD: Rect(240, 100, 80, 40),
        RoiKind.SCORE_PAIR: Rect(340, 100, 200, 40),
        RoiKind.TEAM_A: Rect(100, 60, 220, 30),
        RoiKind.TEAM_B: Rect(340, 60, 220, 30),
        RoiKind.MARKET_LABEL: Rect(1200, 300, 400, 40),
        RoiKind.MARKET_BLOCK: Rect(1200, 350, 400, 300),
    }
    for kind, rect in boxes.items():
        profile.set_roi(kind, rect)
    profile.engine = "stub"
    profile.reads_per_second = 4.0
    profile.stabilization_required = 2
    profile.notes = "Perfil de demostracion: no lee la pantalla real."
    return profile
