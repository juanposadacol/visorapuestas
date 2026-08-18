/**
 * Clasificacion de visibilidad (punto critico del diagnostico).
 *
 * Hay que distinguir tres cosas que se confunden con facilidad:
 *
 *   A. el nodo existe en el DOM y esta visible;
 *   B. el nodo existe en el DOM pero esta oculto;
 *   C. el nodo no existe en el DOM.
 *
 * Y ademas: estar FUERA DEL VIEWPORT no es estar oculto. Un mercado al que
 * hay que bajar con scroll sigue existiendo y sigue siendo visible; solo no
 * cae dentro de la ventana ahora mismo. Se informa aparte.
 *
 * Esta funcion es pura: recibe hechos ya medidos del DOM para poder probarla
 * sin navegador.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { visibility: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * @param {object} facts
   *   displayNone       algun ancestro o el propio nodo con display:none
   *   visibilityHidden  visibility: hidden|collapse
   *   opacityZero       opacidad 0
   *   hiddenAttr        atributo hidden
   *   ariaHidden        aria-hidden="true"
   *   zeroArea          rectangulo sin area
   *   inViewport        cae dentro de la ventana (informativo)
   *   detached          el nodo ya no cuelga del documento
   */
  function classifyVisibility(facts) {
    const f = facts || {};
    const reasons = [];

    if (f.detached) {
      return { existsInDom: false, isVisible: false, inViewport: false,
               reasons: ['el nodo ya no cuelga del documento'] };
    }

    if (f.displayNone) reasons.push('display:none');
    if (f.visibilityHidden) reasons.push('visibility:hidden');
    if (f.opacityZero) reasons.push('opacity:0');
    if (f.hiddenAttr) reasons.push('atributo hidden');
    if (f.ariaHidden) reasons.push('aria-hidden=true');
    if (f.zeroArea) reasons.push('rectangulo sin area');

    const isVisible = reasons.length === 0;
    // Fuera del viewport NO cuenta como oculto: solo se informa.
    if (isVisible && f.inViewport === false) reasons.push('fuera del viewport (sigue visible)');

    return {
      existsInDom: true,
      isVisible,
      inViewport: f.inViewport !== false,
      reasons,
    };
  }

  /** Resumen corto para el informe: EXISTE / OCULTO / NO EXISTE. */
  function describe(state) {
    if (!state || !state.existsInDom) return 'NO EXISTE EN DOM';
    if (state.isVisible) return state.inViewport ? 'VISIBLE' : 'VISIBLE (fuera del viewport)';
    return `OCULTO (${state.reasons.join(', ')})`;
  }

  return { classifyVisibility, describe };
});
