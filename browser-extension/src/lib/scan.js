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
  const api = factory(
    typeof require === 'function' ? require('./options.js') : root.VDIAG.options
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { scan: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (optionsLib) {
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

  /**
   * Elige que mercado se considera "el que estoy viendo".
   *
   * En la prueba real sobre BetPlay ganaba la pestana ("Cuarto 3", confianza
   * 0.55) en lugar del titulo del mercado ("Total de puntos - Cuarto 3",
   * confianza 0.95), y el panel acababa diciendo DESCONOCIDO. La regla es:
   * manda el candidato con mas confianza, no el primero que aparezca.
   *
   * @param {Array} records  mercados detectados
   * @param {number} minConfidence  confianza minima para considerarlo
   */
  function chooseVisibleMarket(records, minConfidence) {
    const minimo = minConfidence === undefined ? 0.9 : minConfidence;
    const candidatos = (records || []).filter(
      (r) => r.isVisible && r.existsInDom && (r.lines || []).length &&
             (r.confidence || 0) >= minimo);
    if (!candidatos.length) return null;
    candidatos.sort((a, b) => {
      const porConfianza = (b.confidence || 0) - (a.confidence || 0);
      if (Math.abs(porConfianza) > 1e-9) return porConfianza;
      return (b.lines || []).length - (a.lines || []).length;
    });
    return candidatos[0];
  }

  //: Profundidad maxima al subir de la cabecera hacia el contenedor del mercado.
  const MAX_CLIMB = 8;

  /**
   * Cabeceras que nombran un mercado dentro de un arbol.
   *
   * Se recorre con el adaptador, asi que sirve igual para el DOM y para un
   * arbol de prueba. Se queda con las mas internas para no confundir la
   * tarjeta entera con su titulo.
   */
  function findMarketHeaders(root, adapter, identify, options) {
    const opciones = options || {};
    const maxTexto = opciones.maxHeaderLength || 160;
    const candidatos = [];
    const visitar = (node, chain) => {
      const hijos = adapter.children(node);
      if (hijos.length > (opciones.maxHeaderChildren || 3)) return;
      const contenido = adapter.text(node);
      if (!contenido || contenido.length > maxTexto) return;
      const identificado = identify(contenido);
      if (!identificado.candidate) return;
      candidatos.push({ element: node, chain, identified: identificado });
    };
    walkTree(root, adapter, visitar, []);
    const contiene = (a, b) => descendants(a, adapter).has(b);
    return pickInnermost(candidatos, contiene);
  }

  function walkTree(node, adapter, visit, chain) {
    visit(node, chain);
    for (const hijo of adapter.children(node)) {
      walkTree(hijo, adapter, visit, [node, ...chain]);
    }
  }

  function descendants(node, adapter) {
    const conjunto = new Set();
    const pila = [...adapter.children(node)];
    while (pila.length) {
      const actual = pila.pop();
      conjunto.add(actual);
      pila.push(...adapter.children(actual));
    }
    return conjunto;
  }

  /**
   * Contenedor de un mercado: se sube desde su cabecera hasta que aparecen sus
   * lineas, sin llegar nunca a abarcar la cabecera de otro mercado. Esa
   * frontera es lo que impide que en la pestana TODO se mezclen el total del
   * partido, el de la mitad y el del cuarto.
   */
  function findMarketContainer(header, allHeaders, adapter, extract) {
    let mejor = { container: header.element, result: extract(header.element) };
    let node = header.element;
    const cadena = header.chain || [];
    for (let i = 0; i < MAX_CLIMB && i < cadena.length; i += 1) {
      node = cadena[i];
      if (wouldInvadeAnotherMarket(node, header, allHeaders,
                                   (a, b) => descendants(a, adapter).has(b))) {
        break;
      }
      const resultado = extract(node);
      if (resultado.lines.length > mejor.result.lines.length) {
        mejor = { container: node, result: resultado };
      }
    }
    return mejor;
  }

  //: Cuanto se sube buscando la cabecera de SECCION de la vista TODO.
  const SECTION_MAX_CLIMB = 8;
  //: Cuanto se baja buscando el primer texto de un contenedor.
  const FIRST_LEAF_MAX_DEPTH = 12;

  /** Primer texto que aparece dentro de un contenedor. */
  function firstLeafText(node, adapter) {
    let actual = node;
    for (let i = 0; i < FIRST_LEAF_MAX_DEPTH && actual; i += 1) {
      const hijos = adapter.children(actual);
      if (!hijos.length) return (adapter.text(actual) || '').trim();
      actual = hijos[0];
    }
    return '';
  }

  /**
   * Seccion de la vista TODO a la que pertenece una cabecera de mercado.
   *
   * En BetPlay, dentro de la pestana TODO, los mercados cuelgan de secciones
   * ("PARTIDO", "SECOND HALF", "Cuarto 4"). Un titulo como "Total de puntos -
   * Prorroga incluida" no dice a que periodo pertenece, pero su seccion si: sin
   * este contexto el mercado se quedaba en DESCONOCIDO con confianza 0.50.
   *
   * Se sube por la cadena de padres y se mira el PRIMER texto de cada ancestro,
   * que es donde las casas ponen el titulo de la seccion.
   */
  function findSectionKey(header, adapter, sectionOf) {
    if (typeof sectionOf !== 'function') return null;
    const cadena = header.chain || [];
    const propio = (adapter.text(header.element) || '').trim();
    for (let i = 0; i < cadena.length && i < SECTION_MAX_CLIMB; i += 1) {
      const etiqueta = firstLeafText(cadena[i], adapter);
      if (!etiqueta || etiqueta === propio) continue;
      const clave = sectionOf(etiqueta);
      if (clave) return { key: clave, label: etiqueta };
    }
    return null;
  }

  /**
   * Escaneo completo: devuelve un registro por mercado reconocido, cada uno
   * con SUS lineas, extraidas solo de SU contenedor.
   */
  function scanMarkets(root, adapter, deps) {
    const identify = deps.identify;
    const sectionOf = deps.sectionOf;
    const extract = deps.extract ||
      ((node) => optionsLib.extractMarketLines(node, adapter, deps.extractOptions));
    const todas = findMarketHeaders(root, adapter, identify, deps.headerOptions);

    // Las cabeceras de SECCION ("PARTIDO", "Second Half", "Cuarto 4") no son
    // mercados: son el contexto de los mercados que vienen debajo. Antes se
    // colaban en la lista como DESCONOCIDO con confianza 0.55 y llenaban el
    // panel de ruido. Se apartan aqui, pero siguen sirviendo de frontera para
    // que un mercado no invada al vecino.
    const secciones = [];
    const cabeceras = [];
    for (const header of todas) {
      const esSeccion = !header.identified.isTotal &&
        typeof sectionOf === 'function' &&
        !!sectionOf(adapter.text(header.element));
      if (esSeccion) secciones.push(header);
      else cabeceras.push(header);
    }

    const registros = [];
    for (const header of cabeceras) {
      const { container, result } = findMarketContainer(header, todas, adapter, extract);
      const seccion = findSectionKey(header, adapter, sectionOf);
      // Se vuelve a identificar YA con el contexto de la seccion.
      const identificado = seccion
        ? identify(adapter.text(header.element), { sectionKey: seccion.key })
        : header.identified;
      registros.push({
        key: identificado.key,
        candidate: identificado.candidate,
        confidence: identificado.confidence,
        headerText: adapter.text(header.element),
        reasons: identificado.reasons,
        sectionKey: seccion ? seccion.key : null,
        sectionLabel: seccion ? seccion.label : null,
        container,
        lines: result.lines,
        rejected: result.rejected,
        sideMarkers: result.sideMarkers,
      });
    }
    return registros;
  }

  return { pickInnermost, wouldInvadeAnotherMarket, preferReading, chooseVisibleMarket,
           findMarketHeaders, findMarketContainer, findSectionKey, firstLeafText,
           scanMarkets, descendants };
});
