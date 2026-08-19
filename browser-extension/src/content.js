/**
 * Content script de DIAGNOSTICO. Solo observa.
 *
 * Este script NO modifica la pagina, NO hace clic en nada, NO envia datos a
 * ningun sitio y NO lee credenciales ni almacenamiento. Su unica funcion es
 * responder a una pregunta con evidencia:
 *
 *   "Si me quedo mirando el Q3, ¿siguen existiendo en el DOM los mercados de
 *    Partido y de las mitades, y siguen actualizandose sus cuotas?"
 *
 * La navegacion entre pestanas la hace el usuario a mano.
 */
(function () {
  'use strict';

  const { text, markets, lines: linesLib, dedupe, visibility,
          scan: scanLib, options: optionsLib, payload: payloadLib } = globalThis.VDIAG;

  //: Un rescaneo completo es caro: las mutaciones se agrupan en ventanas.
  const RESCAN_DEBOUNCE_MS = 400;
  //: Tope del historial en memoria de la sesion.
  const HISTORY_LIMIT = 600;
  //: Profundidad maxima al subir buscando el contenedor de un mercado.
  const MAX_CLIMB = 8;

  const state = {
    startedAt: Date.now(),
    lastScanAt: null,
    scanCount: 0,
    lastScanMs: 0,
    visibleMarket: null,
    markets: new Map(),     // key -> registro del mercado
    history: [],
    environment: null,
    errors: [],
  };

  // ---------------------------------------------------------------- utilidades

  function now() { return Date.now(); }

  function pushHistory(type, detail) {
    state.history.push({ ts: now(), type, ...detail });
    if (state.history.length > HISTORY_LIMIT) {
      state.history.splice(0, state.history.length - HISTORY_LIMIT);
    }
  }

  /**
   * Texto de un subarbol respetando la separacion entre celdas.
   *
   * NO se usa innerText a proposito: innerText devuelve cadena vacia para los
   * elementos ocultos, y precisamente los mercados ocultos son el objeto de
   * este diagnostico. textContent si los lee, pero pega todo junto, asi que se
   * recorren los nodos de texto y se unen con salto de linea.
   */
  function extractText(element) {
    if (!element) return '';
    const partes = [];
    const walker = element.ownerDocument.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const valor = (node.nodeValue || '').trim();
      if (valor) partes.push(valor);
      node = walker.nextNode();
    }
    return partes.join('\n');
  }

  /** Hechos de visibilidad medidos sobre el DOM real. */
  function measureVisibility(element) {
    const doc = element.ownerDocument;
    if (!doc || !doc.contains(element)) {
      return visibility.classifyVisibility({ detached: true });
    }
    const estilo = doc.defaultView.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const alto = doc.defaultView.innerHeight || 0;
    const ancho = doc.defaultView.innerWidth || 0;

    // display:none en un ANCESTRO no aparece en el estilo calculado del hijo;
    // lo que si delata es que no genere ningun rectangulo.
    const sinRectangulos = element.getClientRects().length === 0;
    const displayNone = estilo.display === 'none' || (sinRectangulos && estilo.display !== 'contents');

    return visibility.classifyVisibility({
      displayNone,
      visibilityHidden: estilo.visibility === 'hidden' || estilo.visibility === 'collapse',
      opacityZero: Number(estilo.opacity) === 0,
      hiddenAttr: element.hasAttribute('hidden'),
      ariaHidden: element.getAttribute('aria-hidden') === 'true',
      zeroArea: rect.width === 0 && rect.height === 0 && !sinRectangulos,
      inViewport: rect.bottom > 0 && rect.right > 0 && rect.top < alto && rect.left < ancho,
      detached: false,
    });
  }

  //: Clases generadas por frameworks: sirven para el informe, no como selector.
  const GENERATED_CLASS = /^(css-[a-z0-9]{4,}|sc-[a-zA-Z0-9]{5,}|jss\d+|[a-z]+_[a-zA-Z0-9]{5,}|_[a-zA-Z0-9]{6,})$/;

  function isGeneratedClass(nombre) {
    return GENERATED_CLASS.test(nombre);
  }

  /**
   * Selector aproximado, priorizando lo semanticamente estable.
   * Devuelve tambien si parece fragil, para no construir sobre arena.
   */
  function approximateSelector(element) {
    const partes = [];
    let fragil = false;
    let node = element;
    for (let i = 0; i < 4 && node && node.nodeType === 1; i += 1) {
      let pieza = node.tagName.toLowerCase();
      const datos = Array.from(node.attributes || [])
        .filter((a) => a.name.startsWith('data-') && a.value && a.value.length < 40);
      if (node.id && !isGeneratedClass(node.id)) {
        pieza += `#${node.id}`;
      } else if (datos.length) {
        pieza += `[${datos[0].name}="${datos[0].value}"]`;
      } else if (node.getAttribute && node.getAttribute('aria-label')) {
        pieza += `[aria-label="${text.truncate(node.getAttribute('aria-label'), 30)}"]`;
      } else if (node.getAttribute && node.getAttribute('role')) {
        pieza += `[role="${node.getAttribute('role')}"]`;
      } else {
        const clases = Array.from(node.classList || []);
        const estables = clases.filter((c) => !isGeneratedClass(c));
        if (estables.length) pieza += `.${estables[0]}`;
        else if (clases.length) { pieza += `.${clases[0]}`; fragil = true; }
      }
      partes.unshift(pieza);
      node = node.parentElement;
    }
    return { selector: partes.join(' > '), fragile: fragil };
  }

  /** Ficha de depuracion de un elemento. */
  function describeElement(element) {
    const rect = element.getBoundingClientRect();
    const { selector, fragile } = approximateSelector(element);
    const cadena = [];
    let node = element.parentElement;
    for (let i = 0; i < 4 && node; i += 1) {
      cadena.push(node.tagName.toLowerCase() +
        (node.getAttribute('role') ? `[role=${node.getAttribute('role')}]` : ''));
      node = node.parentElement;
    }
    return {
      tagName: element.tagName.toLowerCase(),
      id: element.id || null,
      className: typeof element.className === 'string' ? text.truncate(element.className, 90) : null,
      ariaLabel: element.getAttribute('aria-label'),
      role: element.getAttribute('role'),
      dataAttributes: Object.fromEntries(
        Array.from(element.attributes || [])
          .filter((a) => a.name.startsWith('data-'))
          .slice(0, 6)
          .map((a) => [a.name, text.truncate(a.value, 40)])),
      rect: { x: Math.round(rect.x), y: Math.round(rect.y),
              w: Math.round(rect.width), h: Math.round(rect.height) },
      selector,
      selectorFragile: fragile,
      parentChain: cadena,
    };
  }

  /**
   * Adaptador del DOM para el escaneo estructural.
   *
   * `text` usa textContent y NO innerText: innerText devuelve cadena vacia en
   * los elementos ocultos, y aqui hay que poder leerlos.
   */
  const DOM_ADAPTER = {
    children: (node) => Array.from(node.children || []),
    text: (node) => extractText(node),
    ownText: (node) => Array.from(node.childNodes || [])
      .filter((n) => n.nodeType === 3)
      .map((n) => (n.nodeValue || '').trim())
      .filter(Boolean)
      .join(' '),
  };

  // ------------------------------------------------------- recorrido del DOM

  /** Documento principal, shadow roots abiertos e iframes del mismo origen. */
  function collectRoots() {
    const roots = [{ root: document, kind: 'document', label: 'principal' }];
    const shadow = [];
    const frames = [];

    const walker = document.createTreeWalker(document, NodeFilter.SHOW_ELEMENT);
    let node = walker.nextNode();
    while (node) {
      if (node.shadowRoot) {
        shadow.push({ host: node.tagName.toLowerCase(), mode: 'open' });
        roots.push({ root: node.shadowRoot, kind: 'shadow-root',
                     label: node.tagName.toLowerCase() });
      }
      if (node.tagName === 'IFRAME') {
        let accesible = false;
        let doc = null;
        try {
          doc = node.contentDocument;
          accesible = !!doc;
        } catch (error) {
          accesible = false;   // otro origen: el navegador lo impide, y esta bien
        }
        frames.push({ src: text.truncate(node.getAttribute('src') || '(sin src)', 120),
                      sameOrigin: accesible });
        if (accesible && doc) {
          roots.push({ root: doc, kind: 'iframe', label: node.getAttribute('src') || 'iframe' });
        }
      }
      node = walker.nextNode();
    }
    return { roots, shadow, frames };
  }

  /** Pistas sobre como esta construida la pagina (sin tocar el mundo de la pagina). */
  function detectEnvironment(shadow, frames) {
    const pistas = [];
    const html = document.documentElement;
    if (document.querySelector('[ng-version]')) pistas.push('Angular (ng-version)');
    if (document.querySelector('[_nghost], [_ngcontent]')) pistas.push('Angular (view encapsulation)');
    if (document.querySelector('[data-v-app], [data-v-]')) pistas.push('Vue (data-v-*)');
    if (document.querySelector('[data-reactroot], #root, #__next')) pistas.push('React o Next (contenedor tipico)');
    if (document.querySelector('[data-virtualized], .ReactVirtualized__Grid, [data-testid*="virtual"]')) {
      pistas.push('posible virtualizacion de listas');
    }
    if (shadow.length) pistas.push(`${shadow.length} shadow root(s) abiertos`);
    const cerrados = frames.filter((f) => !f.sameOrigin).length;
    if (cerrados) pistas.push(`${cerrados} iframe(s) de otro origen (no accesibles)`);

    return {
      url: location.href,
      title: text.truncate(document.title, 120),
      lang: html.getAttribute('lang'),
      hints: pistas,
      shadowRoots: shadow,
      frames,
      // Nota honesta: desde el mundo aislado de una extension no se pueden ver
      // las propiedades que el JS de la pagina cuelga de los nodos, asi que la
      // deteccion se basa solo en atributos reales del DOM.
      note: 'Deteccion basada solo en atributos del DOM; el mundo aislado de la extension no ve las variables internas de la pagina.',
    };
  }

  // ------------------------------------------------------------------ escaneo

  function scan() {
    const inicio = performance.now();
    const { roots, shadow, frames } = collectRoots();
    state.environment = detectEnvironment(shadow, frames);

    const encontrados = new Map();
    let cabecerasTotales = 0;

    for (const { root, kind, label } of roots) {
      let registros = [];
      try {
        registros = scanLib.scanMarkets(root, DOM_ADAPTER, { identify: markets.identifyMarket });
      } catch (error) {
        state.errors.push({ ts: now(), message: `escaneo: ${error.message}` });
        continue;
      }
      cabecerasTotales += registros.length;

      for (const registro of registros) {
        const visible = measureVisibility(registro.container);
        const clave = registro.key;

        const record = {
          key: clave,
          candidate: registro.candidate,
          confidence: registro.confidence,
          headerText: text.truncate(registro.headerText, 120),
          normalized: markets.identifyMarket(registro.headerText).normalized,
          reasons: registro.reasons,
          rootKind: kind,
          rootLabel: label,
          existsInDom: visible.existsInDom,
          isVisible: visible.isVisible,
          inViewport: visible.inViewport,
          visibilityReasons: visible.reasons,
          // Las lineas salen del emparejamiento POR ESTRUCTURA: cada opcion
          // se ata a su linea por el arbol, no por el orden del texto.
          lines: registro.lines,
          strictLines: registro.lines,
          rejectedNumbers: (registro.rejected || []).slice(0, 12),
          sideMarkers: registro.sideMarkers,
          rawCandidates: (registro.lines || []).length + (registro.rejected || []).length,
          rawLineCount: (registro.lines || []).length,
          duplicates: 0,
          unassigned: (registro.rejected || []).length,
          debug: describeElement(registro.container),
          headerDebug: describeElement(registro.container),
        };

        const previo = encontrados.get(clave);
        const elegido = scanLib.preferReading(previo, record);
        elegido.occurrences = (previo ? previo.occurrences : 0) + 1;
        encontrados.set(clave, elegido);
      }
    }

    mergeIntoState(encontrados);
    state.payload = buildVisiblePayload();
    state.lastScanAt = now();
    state.scanCount += 1;
    state.lastScanMs = performance.now() - inicio;
    state.headerCount = cabecerasTotales;
  }

  /** Funde el resultado del escaneo con lo que ya se sabia, generando historial. */
  function mergeIntoState(encontrados) {
    const visto = now();

    // Mercado visible: manda la confianza, no el orden de aparicion. Si no,
    // la pestana "Cuarto 3" (0.55) le gana al titulo "Total de puntos -
    // Cuarto 3" (0.95) y el panel acaba diciendo DESCONOCIDO.
    const elegido = scanLib.chooseVisibleMarket(Array.from(encontrados.values()),
                                                markets.CONFIDENCE_THRESHOLD);
    const nuevoVisible = elegido ? elegido.key : null;
    if (nuevoVisible && nuevoVisible !== state.visibleMarket) {
      pushHistory('marketVisibleChanged', { from: state.visibleMarket, to: nuevoVisible });
      state.visibleMarket = nuevoVisible;
    }

    for (const [clave, registro] of encontrados) {
      const previo = state.markets.get(clave);
      if (!previo) {
        pushHistory('marketAppeared', { market: clave, lines: registro.lines.length });
        state.markets.set(clave, {
          ...registro,
          firstSeenAt: visto,
          lastSeenAt: visto,
          lastMutationAt: visto,
          lastLinesChangeAt: registro.lines.length ? visto : null,
        });
        continue;
      }

      const diff = dedupe.diffLines(previo.lines, registro.lines);
      if (diff.hasChanges) {
        pushHistory('linesChanged', {
          market: clave,
          visible: registro.isVisible,
          added: diff.added.map((l) => l.line),
          removed: diff.removed.map((l) => l.line),
          changed: diff.changed.map((c) => ({
            line: c.line,
            from: [c.from.overOdds, c.from.underOdds],
            to: [c.to.overOdds, c.to.underOdds],
          })),
        });
      }
      if (previo.isVisible !== registro.isVisible) {
        pushHistory('visibilityChanged', {
          market: clave, isVisible: registro.isVisible,
          reasons: registro.visibilityReasons,
        });
      }

      state.markets.set(clave, {
        ...registro,
        firstSeenAt: previo.firstSeenAt,
        lastSeenAt: visto,
        lastMutationAt: diff.hasChanges ? visto : previo.lastMutationAt,
        lastLinesChangeAt: diff.hasChanges ? visto : previo.lastLinesChangeAt,
      });
    }

    // Mercados que estaban y ya no aparecen: se conservan marcados como ausentes.
    for (const [clave, previo] of state.markets) {
      if (encontrados.has(clave)) continue;
      if (previo.existsInDom) {
        pushHistory('marketDisappeared', { market: clave, lastLines: previo.lines.length });
      }
      state.markets.set(clave, { ...previo, existsInDom: false, isVisible: false });
    }
  }

  /**
   * Payload del mercado VISIBLE, listo para enviarse a la aplicacion.
   * Devuelve null (con su motivo) si no hay confianza suficiente.
   */
  function buildVisiblePayload() {
    const clave = state.visibleMarket;
    if (!clave) return { payload: null, rejected: ['no hay mercado visible identificado'] };
    const registro = state.markets.get(clave);
    if (!registro) return { payload: null, rejected: ['el mercado visible no tiene registro'] };
    return payloadLib.buildPayload({
      marketKey: registro.key,
      confidence: registro.confidence,
      rawTitle: registro.headerText,
      eventId: payloadLib.eventIdFromUrl(location.href),
      eventName: eventName(),
      lines: registro.strictLines || registro.lines,
      sideMarkers: registro.sideMarkers,
      observedAt: registro.lastSeenAt || now(),
    });
  }

  /** Nombre del evento, sin arrastrar datos de la cuenta. */
  function eventName() {
    const titulo = (document.title || '').split('|')[0].trim();
    return titulo ? text.truncate(titulo, 120) : null;
  }

  // ------------------------------------------------------- observer y arranque

  let pendiente = null;
  let mutacionesDesdeElUltimoEscaneo = 0;

  function programarEscaneo() {
    if (pendiente) return;
    pendiente = setTimeout(() => {
      pendiente = null;
      try {
        scan();
      } catch (error) {
        state.errors.push({ ts: now(), message: String(error && error.message || error) });
      }
      mutacionesDesdeElUltimoEscaneo = 0;
    }, RESCAN_DEBOUNCE_MS);
  }

  const observer = new MutationObserver((mutaciones) => {
    mutacionesDesdeElUltimoEscaneo += mutaciones.length;
    programarEscaneo();
  });

  function arrancar() {
    try {
      scan();
    } catch (error) {
      state.errors.push({ ts: now(), message: String(error && error.message || error) });
    }
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'hidden', 'aria-hidden', 'aria-selected', 'data-state'],
    });
    pushHistory('observerStarted', {});
  }

  // ------------------------------------------------------------- mensajeria

  function snapshot() {
    return {
      url: location.href,
      startedAt: state.startedAt,
      lastScanAt: state.lastScanAt,
      scanCount: state.scanCount,
      lastScanMs: Math.round(state.lastScanMs),
      headerCount: state.headerCount || 0,
      pendingMutations: mutacionesDesdeElUltimoEscaneo,
      visibleMarket: state.visibleMarket,
      environment: state.environment,
      markets: Array.from(state.markets.values())
        .sort((a, b) => markets.sortKey(a.key) - markets.sortKey(b.key)),
      history: state.history.slice(-200),
      errors: state.errors.slice(-20),
      payload: state.payload ? state.payload.payload : null,
      payloadRejected: state.payload ? state.payload.rejected : ['todavia sin escaneo'],
    };
  }

  chrome.runtime.onMessage.addListener((mensaje, sender, sendResponse) => {
    if (!mensaje || mensaje.type !== 'VDIAG_GET_STATE') return undefined;
    try {
      sendResponse({ ok: true, state: snapshot() });
    } catch (error) {
      sendResponse({ ok: false, error: String(error && error.message || error) });
    }
    return true;
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arrancar, { once: true });
  } else {
    arrancar();
  }
})();
