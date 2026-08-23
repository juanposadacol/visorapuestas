/**
 * Guardia de semantica para el reloj estructural de BetPlay/Kambi durante Q1.
 *
 * En BetPlay el marcador Kambi muestra tiempo JUGADO acumulado del partido.
 * Durante Q1 ese valor (p. ej. 08:40) cabe tambien dentro de un cuarto y la
 * heuristica generica puede confundirlo con tiempo restante. Esta capa se
 * aplica solo al marcador estructural, solo en BetPlay (el manifest limita el
 * content script a ese host) y solo en Q1. Q2+ siguen usando la inferencia
 * general ya estabilizada.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  root.VDIAG = root.VDIAG || {};
  if (root.VDIAG.gamestate) api.install(root.VDIAG.gamestate);
  root.VDIAG.clockQ1Guard = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const GAME_ELAPSED = 'GAME_ELAPSED';
  const PERIOD_REMAINING = 'PERIOD_REMAINING';
  const STRUCTURAL_SOURCE = 'structural';
  const GUARDED_SOURCE = 'kambi-structural-q1';

  function isBetplayStructuralQ1(result) {
    const game = result && result.gameState;
    const diagnostics = result && result.diagnostics && result.diagnostics.clock;
    return !!(
      result && result.structured &&
      game && game.period === 1 && game.clockRaw &&
      diagnostics && diagnostics.source === STRUCTURAL_SOURCE
    );
  }

  /**
   * Corrige SOLO la representacion temporal. No toca marcador, parciales,
   * mercados, cuotas ni formulas. Python recibe GAME_ELAPSED y hace la
   * conversion con GameRules (FIBA/NBA).
   */
  function correctResult(result) {
    if (!isBetplayStructuralQ1(result)) return result;

    const game = result.gameState;
    const diagnostics = result.diagnostics.clock;
    const originalSemantics = game.clockSemantics || diagnostics.semantics || null;

    // Si la heuristica habia publicado 08:40 como "restante", hay que retirar
    // ese `clock`: para GAME_ELAPSED solo viajan clockRaw + clockSemantics.
    delete game.clock;
    game.clockSemantics = GAME_ELAPSED;

    if (result.memory && result.memory.clock) {
      result.memory.clock.semantics = GAME_ELAPSED;
      result.memory.clock.value = null;
      result.memory.clock.seconds = null;
      result.memory.clock.q1StructuralGuard = true;
    }

    diagnostics.originalSemantics = originalSemantics;
    diagnostics.semantics = GAME_ELAPSED;
    diagnostics.value = null;
    diagnostics.source = GUARDED_SOURCE;
    diagnostics.confidence = 1;
    diagnostics.reason = 'BetPlay/Kambi Q1: reloj estructural interpretado como tiempo jugado acumulado';
    if (diagnostics.status !== 'CLOCK_STOPPED') diagnostics.status = 'CONFIRMED';

    return result;
  }

  function install(gamestate) {
    if (!gamestate || gamestate.__clockQ1GuardInstalled) return gamestate;
    if (typeof gamestate.extractGameState !== 'function' ||
        typeof gamestate.extractGameStateFromRoots !== 'function') {
      return gamestate;
    }

    const extractOne = gamestate.extractGameState;
    const extractMany = gamestate.extractGameStateFromRoots;

    gamestate.extractGameState = function (...args) {
      return correctResult(extractOne.apply(this, args));
    };
    gamestate.extractGameStateFromRoots = function (...args) {
      return correctResult(extractMany.apply(this, args));
    };

    Object.defineProperty(gamestate, '__clockQ1GuardInstalled', {
      value: true,
      enumerable: false,
      configurable: false,
      writable: false,
    });
    return gamestate;
  }

  return {
    GAME_ELAPSED,
    PERIOD_REMAINING,
    GUARDED_SOURCE,
    isBetplayStructuralQ1,
    correctResult,
    install,
  };
});