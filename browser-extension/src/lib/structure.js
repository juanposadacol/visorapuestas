/**
 * Copia SANEADA de la estructura de un trozo del DOM.
 *
 * Para que existe: llevamos tres pruebas reales ajustando el parser a ciegas,
 * adivinando como monta BetPlay sus bloques. Con esto se puede mandar la forma
 * exacta de un mercado o del marcador -- etiquetas, clases, roles, jerarquia y
 * los textos del mercado -- sin mandar NADA de la cuenta.
 *
 * Lo que sale:
 *
 *     MERCADO
 *
 *     section.market
 *       h3.market__title
 *         "Total de puntos - Cuarto 4"
 *       div.market__options
 *         div.option
 *           "Mas de 44.5"
 *           "1.75"
 *         div.option
 *           "Menos de 44.5"
 *           "1.90"
 *
 * Lo que NO sale, por construccion y no por descuido: usuario, saldo, cookies,
 * tokens, identificadores de cuenta, el boleto de apuestas y cualquier atributo
 * que huela a autenticacion. Ante la duda sobre un atributo, se omite.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text,
    typeof require === 'function' ? require('./report.js') : root.VDIAG.report
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { structure: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text, report) {
  'use strict';

  const LIMITES = {
    maxNodes: 220,
    maxDepth: 12,
    maxTextLength: 90,
    maxAttrLength: 60,
    maxClasses: 4,
    maxChars: 12000,
  };

  //: Atributos que NO se copian nunca, aunque sean data-*.
  const SENSIBLE = /token|session|sesion|auth|jwt|cookie|user|usuario|cliente|customer|account|cuenta|saldo|balance|wallet|email|correo|cedula|documento|phone|telefono|csrf|nonce|api-?key|secret|password|contrasena|bearer|signature/i;

  //: Bloques enteros que no se copian: no tienen que ver con el mercado y son
  //: justo donde vive lo privado.
  const BLOQUE_PRIVADO = /bet-?slip|betslip|boleto|carrito|cupon|coupon|mis-?apuestas|my-?bets|account|cuenta|perfil|profile|wallet|saldo|balance|deposit|deposito|withdraw|retir|login|registro|register|chat|soporte/i;

  //: Valores que parecen un identificador opaco (hex largo, base64, uuid).
  const VALOR_OPACO = /^[A-Za-z0-9+/=_-]{20,}$/;

  /** Atributos que si aportan para entender la estructura. */
  const INTERESANTES = ['role', 'aria-label', 'aria-selected', 'aria-expanded',
                        'aria-hidden', 'hidden', 'type'];

  function limpiarValor(valor, limites) {
    const cfg = limites || LIMITES;
    const crudo = String(valor === null || valor === undefined ? '' : valor).trim();
    if (!crudo) return '';
    if (VALOR_OPACO.test(crudo) && !/^\d+([.,]\d+)?$/.test(crudo)) return '[valor opaco]';
    return text.truncate(report.redact(crudo), cfg.maxAttrLength);
  }

  /** ¿Este subarbol es zona privada que no hay que copiar? */
  function esBloquePrivado(node, adapter) {
    const señas = typeof adapter.attrText === 'function' ? adapter.attrText(node) : '';
    return BLOQUE_PRIVADO.test(señas);
  }

  /**
   * Firma de un elemento: etiqueta, clases estables y atributos utiles.
   * No se copian ni el `id` ni los data-* que huelan a cuenta.
   */
  function describeNode(node, adapter, limites) {
    const cfg = limites || LIMITES;
    let etiqueta = 'nodo';
    try {
      etiqueta = String(node.tagName || 'nodo').toLowerCase();
    } catch (error) { /* nodo desmontado */ }

    const partes = [etiqueta];
    try {
      const clases = typeof node.className === 'string'
        ? node.className.split(/\s+/).filter(Boolean)
        : [];
      for (const clase of clases.slice(0, cfg.maxClasses)) {
        if (SENSIBLE.test(clase)) continue;
        partes.push(`.${text.truncate(clase, cfg.maxAttrLength)}`);
      }
    } catch (error) { /* sin clases */ }

    const atributos = [];
    try {
      if (typeof node.getAttribute === 'function') {
        for (const nombre of INTERESANTES) {
          const valor = node.getAttribute(nombre);
          if (valor === null || valor === undefined) continue;
          if (SENSIBLE.test(nombre) || SENSIBLE.test(String(valor))) continue;
          atributos.push(`${nombre}="${limpiarValor(valor, cfg)}"`);
        }
      }
      for (const atributo of Array.from(node.attributes || [])) {
        if (!atributo || typeof atributo.name !== 'string') continue;
        if (!atributo.name.startsWith('data-')) continue;
        if (SENSIBLE.test(atributo.name) || SENSIBLE.test(String(atributo.value))) continue;
        atributos.push(`${atributo.name}="${limpiarValor(atributo.value, cfg)}"`);
        if (atributos.length > 6) break;
      }
    } catch (error) { /* nodo desmontado a mitad */ }

    return partes.join('') + (atributos.length ? `[${atributos.join(' ')}]` : '');
  }

  /**
   * Vuelca la estructura de un subarbol como texto indentado.
   *
   * Los textos van entre comillas y en su propia linea, que es lo que permite
   * ver de un vistazo si la etiqueta y la cuota son nodos distintos o el mismo
   * -- exactamente la duda que hizo que el UNDER se perdiera.
   */
  function serializeSubtree(node, adapter, options) {
    const cfg = { ...LIMITES, ...(options || {}) };
    if (!node) return '(nada que copiar)';

    const lineas = [];
    let nodos = 0;
    let recortado = false;

    const visitar = (actual, profundidad) => {
      if (nodos >= cfg.maxNodes) { recortado = true; return; }
      if (profundidad > cfg.maxDepth) { recortado = true; return; }
      if (esBloquePrivado(actual, adapter)) {
        lineas.push(`${'  '.repeat(profundidad)}[bloque privado omitido]`);
        return;
      }
      nodos += 1;
      lineas.push(`${'  '.repeat(profundidad)}${describeNode(actual, adapter, cfg)}`);

      const propio = typeof adapter.ownText === 'function' ? adapter.ownText(actual) : '';
      if (propio) {
        lineas.push(`${'  '.repeat(profundidad + 1)}"${
          text.truncate(report.redact(propio), cfg.maxTextLength)}"`);
      }
      for (const hijo of adapter.children(actual)) visitar(hijo, profundidad + 1);
    };

    try {
      visitar(node, 0);
    } catch (error) {
      lineas.push(`[el arbol cambio mientras se copiaba: ${error.message}]`);
    }
    if (recortado) lineas.push(`[recortado: mas de ${cfg.maxNodes} nodos]`);

    const salida = lineas.join('\n');
    return salida.length > cfg.maxChars
      ? `${salida.slice(0, cfg.maxChars)}\n[recortado por tamano]`
      : salida;
  }

  /** Informe listo para pegar en una conversacion. */
  function buildStructureReport(titulo, node, adapter, meta, options) {
    const cabecera = [titulo];
    for (const [clave, valor] of Object.entries(meta || {})) {
      if (valor === null || valor === undefined || valor === '') continue;
      cabecera.push(`${clave}: ${report.redact(String(valor))}`);
    }
    cabecera.push('');
    cabecera.push(serializeSubtree(node, adapter, options));
    cabecera.push('');
    cabecera.push('(estructura saneada: sin usuario, saldo, cookies, tokens ni boleto)');
    return cabecera.join('\n');
  }

  return { LIMITES, SENSIBLE, BLOQUE_PRIVADO, limpiarValor, esBloquePrivado,
           describeNode, serializeSubtree, buildStructureReport };
});
