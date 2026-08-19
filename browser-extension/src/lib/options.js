/**
 * Extraccion de lineas por ESTRUCTURA, no aplanando el contenedor a texto.
 *
 * Por que existe este modulo: en la prueba real sobre BetPlay se detectaba el
 * OVER de una linea pero nunca el UNDER. Aplanar el contenedor a una cadena y
 * leerla en orden funciona en un solo tipo de maquetacion; en cuanto la casa
 * pone las dos opciones como nodos hermanos, o saca el valor de la linea a un
 * nodo aparte que comparten ambas, el emparejamiento se rompe.
 *
 * Aqui se trabaja sobre el arbol:
 *   1. se localizan los nodos hoja que contienen una CUOTA;
 *   2. de cada uno se deduce su LADO (por palabra propia, por la de un
 *      ancestro cercano, o por su posicion entre hermanos);
 *   3. se busca la LINEA a la que pertenece subiendo hasta el ancestro mas
 *      cercano que la contenga;
 *   4. se agrupan por linea, juntando las dos opciones hermanas.
 *
 * El arbol se recorre a traves de un ADAPTADOR, asi que la misma logica sirve
 * para el DOM real y para arboles de juguete en los tests.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text,
    typeof require === 'function' ? require('./lines.js') : root.VDIAG.lines
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { options: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text, linesLib) {
  'use strict';

  const OVER_WORDS = ['mas de', 'mas', 'over', 'alta', 'arriba', 'encima'];
  const UNDER_WORDS = ['menos de', 'menos', 'under', 'baja', 'abajo', 'debajo'];

  /** Adaptador para el DOM real. */
  const DOM_ADAPTER = {
    children: (node) => Array.from(node.children || []),
    text: (node) => (node.textContent || ''),
    // Texto propio del nodo, sin el de sus hijos elemento: distingue
    // "Mas de" (etiqueta) de "Mas de 44.5 1.75" (contenedor entero).
    ownText: (node) => Array.from(node.childNodes || [])
      .filter((n) => n.nodeType === 3)
      .map((n) => n.nodeValue || '')
      .join(' '),
  };

  function sideFromText(raw) {
    const normalized = text.normalizeOrdinals(raw || '');
    if (!normalized) return '';
    // "menos de" antes que "mas": "mas" es subcadena de otras palabras.
    for (const palabra of UNDER_WORDS) {
      if (new RegExp(`\\b${palabra}\\b`).test(normalized)) return 'under';
    }
    for (const palabra of OVER_WORDS) {
      if (new RegExp(`\\b${palabra}\\b`).test(normalized)) return 'over';
    }
    return '';
  }

  /** Numeros con forma de cuota que contiene un texto. */
  function oddsIn(raw) {
    const encontrados = [];
    for (const token of linesLib.tokenize(raw || '')) {
      if (linesLib.isStrictOddsShaped(token.value, token.decimals)) encontrados.push(token.value);
    }
    return encontrados;
  }

  /** Numeros con forma de linea de total que contiene un texto. */
  function linesIn(raw, allowWholeLines) {
    const encontrados = [];
    for (const token of linesLib.tokenize(raw || '')) {
      if (linesLib.isStrictLineShaped(token.value, token.decimals, allowWholeLines)) {
        encontrados.push(token.value);
      }
    }
    return encontrados;
  }

  /** Recorrido en profundidad devolviendo cada nodo con su cadena de padres. */
  function walk(root, adapter, visit, chain) {
    const padres = chain || [];
    visit(root, padres);
    for (const hijo of adapter.children(root)) {
      walk(hijo, adapter, visit, [root, ...padres]);
    }
  }

  /**
   * Nodos hoja que contienen exactamente una cuota.
   * Se toma el mas interno para no confundir el boton con su contenedor.
   */
  function findOddsNodes(root, adapter) {
    const encontrados = [];
    walk(root, adapter, (node, chain) => {
      const propias = oddsIn(adapter.text(node));
      if (propias.length !== 1) return;
      const hijos = adapter.children(node);
      const algunHijoLaTiene = hijos.some((h) => oddsIn(adapter.text(h)).length === 1);
      if (algunHijoLaTiene) return;      // hay uno mas interno
      encontrados.push({ node, chain, odds: propias[0] });
    });
    return encontrados;
  }

  /** Cuenta cuantos lados distintos menciona un texto. */
  function sidesMentioned(raw) {
    const normalized = text.normalizeOrdinals(raw || '');
    const tieneUnder = UNDER_WORDS.some((w) => new RegExp(`\\b${w}\\b`).test(normalized));
    const tieneOver = OVER_WORDS.some((w) => new RegExp(`\\b${w}\\b`).test(normalized));
    if (tieneUnder && tieneOver) return { side: '', count: 2 };
    if (tieneUnder) return { side: 'under', count: 1 };
    if (tieneOver) return { side: 'over', count: 1 };
    return { side: '', count: 0 };
  }

  /** Ultimo lado nombrado antes de `target` en orden de documento. */
  function sideBefore(root, target, adapter) {
    let ultimo = '';
    let encontrado = false;
    walk(root, adapter, (node) => {
      if (encontrado) return;
      if (node === target) { encontrado = true; return; }
      if (adapter.children(node).length) return;      // solo hojas
      const detectado = sidesMentioned(adapter.text(node));
      if (detectado.count === 1) ultimo = detectado.side;
    });
    return encontrado ? ultimo : '';
  }

  /**
   * Lado de una cuota, por orden de fiabilidad:
   *   1. su propio texto;
   *   2. un ancestro cercano que nombre UN SOLO lado;
   *   3. el ultimo lado nombrado antes de ella en orden de documento.
   *
   * Nunca se usa un ancestro que nombre los dos lados: ahi la respuesta seria
   * una moneda al aire. El reparto por posicion se decide despues, ya
   * agrupadas las cuotas por su linea.
   */
  function resolveSide(entry, adapter, container) {
    const propio = sidesMentioned(adapter.text(entry.node));
    if (propio.count === 1) return { side: propio.side, from: 'texto propio' };

    for (const ancestro of entry.chain.slice(0, 3)) {
      const propioDelAncestro = sidesMentioned(
        adapter.ownText ? adapter.ownText(ancestro) : '');
      if (propioDelAncestro.count === 1) {
        return { side: propioDelAncestro.side, from: 'ancestro' };
      }
      const completoDelAncestro = sidesMentioned(adapter.text(ancestro));
      if (completoDelAncestro.count === 1) {
        return { side: completoDelAncestro.side, from: 'ancestro' };
      }
    }

    const anterior = sideBefore(container, entry.node, adapter);
    if (anterior) return { side: anterior, from: 'texto anterior' };
    return { side: '', from: '' };
  }

  /**
   * Linea a la que pertenece una cuota: el ancestro mas cercano que contenga
   * exactamente un valor con forma de linea. Si el ancestro contiene varios,
   * ya se ha subido demasiado y se descarta.
   */
  function resolveLine(entry, adapter, allowWholeLines) {
    const propias = linesIn(adapter.text(entry.node), allowWholeLines);
    if (propias.length === 1) return propias[0];
    for (const ancestro of entry.chain) {
      const candidatas = linesIn(adapter.text(ancestro), allowWholeLines);
      if (candidatas.length === 1) return candidatas[0];
      if (candidatas.length > 1) {
        // Varias lineas bajo el mismo ancestro: la buena es la ultima que
        // aparece antes de esta cuota dentro de ese subarbol.
        const anterior = lineBefore(ancestro, entry.node, adapter, allowWholeLines);
        if (anterior !== null) return anterior;
        break;
      }
    }
    return null;
  }

  /** Ultimo valor con forma de linea que aparece antes de `target`. */
  function lineBefore(root, target, adapter, allowWholeLines) {
    let ultima = null;
    let encontrado = false;
    walk(root, adapter, (node) => {
      if (encontrado) return;
      if (node === target) { encontrado = true; return; }
      if (adapter.children(node).length) return;      // solo hojas
      const candidatas = linesIn(adapter.text(node), allowWholeLines);
      if (candidatas.length === 1) ultima = candidatas[0];
    });
    return encontrado ? ultima : null;
  }

  /**
   * Reparto por POSICION, ya con las cuotas agrupadas por su linea.
   *
   * Agrupar por el padre inmediato no servia: cuando cada opcion vive en su
   * propio envoltorio, las dos cuotas no son hermanas. Lo que si las une
   * siempre es pertenecer a la misma linea.
   */
  function assignPositionalSides(sinLado) {
    const porLinea = new Map();
    for (const entrada of sinLado) {
      const clave = entrada.line.toFixed(2);
      if (!porLinea.has(clave)) porLinea.set(clave, []);
      porLinea.get(clave).push(entrada);
    }
    const asignadas = [];
    const rechazadas = [];
    for (const grupo of porLinea.values()) {
      if (grupo.length === 2) {
        // Orden visual habitual: primero OVER, despues UNDER.
        asignadas.push({ ...grupo[0], side: 'over', sideFrom: 'posicion' });
        asignadas.push({ ...grupo[1], side: 'under', sideFrom: 'posicion' });
      } else {
        for (const entrada of grupo) {
          rechazadas.push({ odds: entrada.odds, line: entrada.line,
                            reason: 'no se pudo determinar el lado' });
        }
      }
    }
    return { asignadas, rechazadas };
  }

  /**
   * Extrae las lineas de un contenedor de mercado.
   * Devuelve { lines, options, rejected, sideMarkers }.
   */
  function extractMarketLines(container, adapter, options) {
    const opciones = options || {};
    const adaptador = adapter || DOM_ADAPTER;
    const permitirEnteros = !!opciones.allowWholeLines;
    if (!container) return { lines: [], options: [], rejected: [], sideMarkers: { both: false } };

    const nodosCuota = findOddsNodes(container, adaptador);

    const encontradas = [];
    const sinLado = [];
    const rechazadas = [];
    for (const entry of nodosCuota) {
      const linea = resolveLine(entry, adaptador, permitirEnteros);
      if (linea === null) {
        rechazadas.push({ odds: entry.odds, reason: 'cuota sin linea asociada' });
        continue;
      }
      const { side, from } = resolveSide(entry, adaptador, container);
      if (!side) {
        sinLado.push({ line: linea, odds: entry.odds, node: entry.node });
        continue;
      }
      encontradas.push({ line: linea, side, odds: entry.odds, sideFrom: from });
    }

    // Las que no traian palabra se reparten por posicion dentro de su linea.
    const posicionales = assignPositionalSides(sinLado);
    encontradas.push(...posicionales.asignadas);
    rechazadas.push(...posicionales.rechazadas);

    // Agrupacion por linea: aqui se juntan las dos opciones hermanas.
    const porLinea = new Map();
    for (const opcion of encontradas) {
      const clave = opcion.line.toFixed(2);
      if (!porLinea.has(clave)) {
        porLinea.set(clave, { line: opcion.line, overOdds: null, underOdds: null,
                              sidesFrom: [] });
      }
      const grupo = porLinea.get(clave);
      const campo = opcion.side === 'under' ? 'underOdds' : 'overOdds';
      if (grupo[campo] === null) {
        grupo[campo] = opcion.odds;
        grupo.sidesFrom.push(opcion.sideFrom);
      } else {
        rechazadas.push({ odds: opcion.odds, line: opcion.line,
                          reason: `segunda cuota ${opcion.side} para la misma linea` });
      }
    }

    const lineas = Array.from(porLinea.values()).sort((a, b) => a.line - b.line);
    const conAmbos = lineas.some((l) => l.overOdds !== null && l.underOdds !== null);
    const porTexto = encontradas.some((o) => o.sideFrom !== 'posicion');
    return {
      lines: lineas,
      options: encontradas,
      rejected: rechazadas,
      sideMarkers: { both: conAmbos && porTexto, byPosition: !porTexto && conAmbos },
    };
  }

  return { DOM_ADAPTER, sideFromText, oddsIn, linesIn, findOddsNodes,
           extractMarketLines };
});
