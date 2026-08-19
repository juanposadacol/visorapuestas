/**
 * Parte PURA del recorrido del DOM.
 *
 * Las decisiones delicadas del escaneo (quedarse con la cabecera mas interna,
 * saber hasta donde se puede subir sin invadir otro mercado, elegir entre dos
 * lecturas del mismo mercado) no necesitan un navegador: solo necesitan saber
 * quien contiene a quien. Se aislan aqui con esa relacion inyectada, para
 * poder probarlas con `node --test` sin montar un DOM.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { scan: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * De un conjunto de candidatos anidados, se queda con los mas internos.
   *
   * Si una tarjeta entera y su titulo mencionan el mismo mercado, el titulo es
   * el que interesa: la tarjeta arrastraria texto de sus vecinos.
   *
   * @param {Array} candidates  objetos con `.element`
   * @param {Function} contains (a, b) => true si el elemento a contiene al b
   */
  function pickInnermost(candidates, contains) {
    const lista = candidates || [];
    return lista.filter(
      (a) => !lista.some((b) => b !== a && contains(a.element, b.element)));
  }

  /**
   * Decide si se puede seguir subiendo desde una cabecera hacia su contenedor.
   * En cuanto el ancestro abarca la cabecera de OTRO mercado, subir mas
   * mezclaria lineas de mercados distintos, que es el error que hay que evitar.
   */
  function wouldInvadeAnotherMarket(ancestor, header, allHeaders, contains) {
    return (allHeaders || []).some(
      (otra) => otra !== header && contains(ancestor, otra.element));
  }

  /**
   * Entre dos lecturas del mismo mercado (movil y escritorio, por ejemplo)
   * gana la que trae mas lineas; con empate, la visible.
   */
  function preferReading(previous, candidate) {
    if (!previous) return candidate;
    const masLineas = (candidate.lines || []).length - (previous.lines || []).length;
    if (masLineas > 0) return candidate;
    if (masLineas < 0) return previous;
    if (candidate.isVisible && !previous.isVisible) return candidate;
    return previous;
  }

  return { pickInnermost, wouldInvadeAnotherMarket, preferReading };
});
