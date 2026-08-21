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
          scan: scanLib, options: optionsLib, payload: payloadLib,
          gamestate: gamestateLib, dom, errors: erroresLib,
          structure: structureLib } = globalThis.VDIAG;

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
    gameState: null,        // marcador, cuarto y reloj si el DOM los da
    gameDiagnostics: null,
    gameMemory: null,
    //: Partido al que pertenece todo lo de arriba. Si cambia, se olvida todo.
    eventId: undefined,
    history: [],
    environment: null,
    //: Errores agrupados por causa y raiz, nunca una linea por ocurrencia.
    errorLog: erroresLib.createErrorLog(),
    //: Una raiz que falla sin parar descansa un rato; las sanas siguen.
    breaker: erroresLib.createCircuitBreaker(),
    skippedRoots: [],
    //: Medida del coste del escaneo. Sin esto, "va lento" es una impresion.
    scanMsTotal: 0,
    scanMsMax: 0,
  };

  /** Anota un error agrupandolo. Devuelve la entrada, ya con su cuenta. */
  function anotarError(detalle) {
    return state.errorLog.record({ ...detalle, now: now() });
  }

  function mensajeDe(error) {
    return String((error && error.message) || error || 'error sin mensaje');
  }

  // ---------------------------------------------------------------- utilidades

  function now() { return Date.now(); }

  function pushHistory(type, detail) {
    state.history.push({ ts: now(), type, ...detail });
    if (state.history.length > HISTORY_LIMIT) {
      state.history.splice(0, state.history.length - HISTORY_LIMIT);
    }
  }

  // La lectura de texto vive en `lib/dom.js`: alli se resuelve el documento
  // segun el TIPO de raiz (Document, Element, ShadowRoot, iframe) en vez de
  // dar por hecho que existe `ownerDocument`, que para un Document es null.
  const extractText = dom.extractText;

  /**
   * Hechos de visibilidad medidos sobre el DOM real.
   *
   * Se pregunta por `isConnected` y no por `document.contains(element)`: los
   * nodos que viven dentro de un shadow root NO estan en `document.contains`,
   * y darlos por desmontados hacia desaparecer mercados perfectamente vivos.
   */
  function measureVisibility(element) {
    const doc = dom.documentForNode(element);
    const vista = doc && doc.defaultView;
    if (!doc || !vista || element.isConnected === false) {
      return visibility.classifyVisibility({ detached: true });
    }
    const estilo = vista.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    const alto = vista.innerHeight || 0;
    const ancho = vista.innerWidth || 0;

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

  /** describeElement protegido: un nodo que se desmonto no rompe el escaneo. */
  function describirConCuidado(element, rootKind, rootLabel) {
    try {
      return describeElement(element);
    } catch (error) {
      anotarError({ stage: 'describe', rootKind, rootLabel, message: mensajeDe(error) });
      return { tagName: '?', selector: '(no se pudo describir)', parentChain: [] };
    }
  }

  /**
   * Adaptador del DOM para el escaneo estructural.
   *
   * `text` usa textContent y NO innerText: innerText devuelve cadena vacia en
   * los elementos ocultos, y aqui hay que poder leerlos.
   */
  const DOM_ADAPTER = dom.createAdapter();

  // ------------------------------------------------------- recorrido del DOM

  //: Tope de raices que se recorren en un escaneo. BetPlay tiene una decena
  //: larga entre shadow roots e iframes; el tope solo evita que una pagina
  //: patologica bloquee la pestana.
  const MAX_ROOTS = 60;

  /** Clave estable de una raiz, para el cortacircuitos y el diagnostico. */
  function rootKey(entrada) {
    return `${entrada.kind}:${entrada.label}#${entrada.index}`;
  }

  /**
   * Documento principal, shadow roots abiertos e iframes del mismo origen.
   *
   * Se descubre en anchura y ENTRANDO en cada raiz encontrada, porque BetPlay
   * anida: hay shadow roots dentro de shadow roots e iframes colgando de un
   * componente. Cada paso esta protegido: una raiz que se desmonta a mitad del
   * descubrimiento se salta, y las demas se recogen igual.
   */
  function collectRoots() {
    const roots = [];
    const shadow = [];
    const frames = [];
    const pendientes = [{ root: document, kind: 'document', label: 'principal' }];
    const vistos = new Set();

    while (pendientes.length && roots.length < MAX_ROOTS) {
      const entrada = pendientes.shift();
      if (vistos.has(entrada.root)) continue;
      vistos.add(entrada.root);
      if (!dom.isUsableRoot(entrada.root)) {
        // La raiz murio entre que se descubrio y que toco recorrerla. Es
        // normal en una pagina viva: se anota y se sigue.
        state.skippedRoots.push({ kind: entrada.kind, label: entrada.label,
                                  reason: 'raiz sin documento vivo' });
        continue;
      }
      entrada.index = roots.length;
      entrada.key = rootKey(entrada);
      roots.push(entrada);

      const doc = dom.documentForNode(entrada.root);
      let walker = null;
      try {
        walker = doc.createTreeWalker(entrada.root, dom.showElementFor(doc));
      } catch (error) {
        anotarError({ stage: 'roots', rootKind: entrada.kind,
                      rootLabel: entrada.label, message: mensajeDe(error) });
        continue;
      }

      let node = null;
      try { node = walker.nextNode(); } catch (error) { node = null; }
      while (node) {
        try {
          if (node.shadowRoot) {
            shadow.push({ host: node.tagName.toLowerCase(), mode: 'open' });
            pendientes.push({ root: node.shadowRoot, kind: 'shadow-root',
                              label: node.tagName.toLowerCase() });
          }
          if (node.tagName === 'IFRAME') {
            let interno = null;
            try {
              interno = node.contentDocument;      // null si es de otro origen
            } catch (error) {
              interno = null;   // el navegador lo impide, y esta bien que lo haga
            }
            frames.push({
              src: text.truncate(node.getAttribute('src') || '(sin src)', 120),
              sameOrigin: !!interno,
            });
            if (interno) {
              pendientes.push({ root: interno, kind: 'iframe',
                                label: node.getAttribute('src') || 'iframe' });
            }
          }
        } catch (error) {
          // Un nodo concreto que desaparecio: no corta el descubrimiento.
          anotarError({ stage: 'roots', rootKind: entrada.kind,
                        rootLabel: entrada.label, message: mensajeDe(error) });
        }
        try { node = walker.nextNode(); } catch (error) { node = null; }
      }
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

  /**
   * Si cambio el partido, se tira TODO lo que se sabia del anterior.
   *
   * Sin esto, al pasar de un evento a otro quedaban en memoria los mercados y
   * el marcador del partido viejo, y durante unos segundos la aplicacion podia
   * mezclar dos partidos distintos. La URL de BetPlay usa enrutado por hash,
   * asi que el cambio de evento no recarga la pagina ni el content script.
   */
  function comprobarCambioDeEvento() {
    const actual = payloadLib.eventIdFromUrl(location.href);
    if (state.eventId === undefined) {
      state.eventId = actual;
      return;
    }
    if (actual === state.eventId) return;

    pushHistory('eventChanged', { from: state.eventId, to: actual });
    state.eventId = actual;
    state.markets.clear();
    state.visibleMarket = null;
    state.gameState = null;
    state.gameMemory = null;
    state.gameDiagnostics = null;
    state.payload = null;
  }

  function scan() {
    const inicio = performance.now();
    comprobarCambioDeEvento();
    state.skippedRoots = [];
    const { roots, shadow, frames } = collectRoots();
    state.environment = detectEnvironment(shadow, frames);

    const encontrados = new Map();
    let cabecerasTotales = 0;
    let raicesRecorridas = 0;

    for (const entrada of roots) {
      const { root, kind, label, key } = entrada;
      // Una raiz que ya fallo varias veces seguidas descansa un rato. Las
      // demas siguen recorriendose con normalidad.
      if (state.breaker.shouldSkip(key, now())) {
        state.skippedRoots.push({ kind, label, reason: 'ROOT_UNSTABLE' });
        continue;
      }
      if (!dom.isUsableRoot(root)) {
        state.skippedRoots.push({ kind, label, reason: 'raiz sin documento vivo' });
        continue;
      }

      let registros = [];
      try {
        registros = scanLib.scanMarkets(root, DOM_ADAPTER, {
          identify: markets.identifyMarket,
          sectionOf: markets.sectionKey,
        });
        state.breaker.success(key);
        raicesRecorridas += 1;
      } catch (error) {
        // Una raiz rota NO tumba el escaneo global: se anota agrupado y se
        // sigue con las demas.
        anotarError({ stage: 'scan', rootKind: kind, rootLabel: label,
                      message: mensajeDe(error) });
        state.breaker.failure(key, now());
        continue;
      }
      cabecerasTotales += registros.length;

      for (const registro of registros) {
        let visible;
        try {
          visible = measureVisibility(registro.container);
        } catch (error) {
          anotarError({ stage: 'visibility', rootKind: kind, rootLabel: label,
                        message: mensajeDe(error) });
          continue;
        }
        const clave = registro.key;

        const record = {
          key: clave,
          candidate: registro.candidate,
          confidence: registro.confidence,
          headerText: text.truncate(registro.headerText, 120),
          normalized: markets.identifyMarket(registro.headerText).normalized,
          reasons: registro.reasons,
          sectionKey: registro.sectionKey,
          sectionLabel: registro.sectionLabel,
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
          debug: describirConCuidado(registro.container, kind, label),
          headerDebug: describirConCuidado(registro.container, kind, label),
          // El nodo se guarda para poder copiar su estructura, pero NUNCA
          // viaja en el snapshot: un nodo del DOM no se puede serializar.
          container: registro.container,
        };

        const previo = encontrados.get(clave);
        const elegido = scanLib.preferReading(previo, record);
        elegido.occurrences = (previo ? previo.occurrences : 0) + 1;
        encontrados.set(clave, elegido);
      }
    }

    // Marcador, cuarto y reloj desde el DOM, si es que estan. Si no hay
    // confianza suficiente, no se envia nada y la aplicacion usara OCR.
    //
    // Se miran TODAS las raices vivas, no solo `document.body`: en BetPlay la
    // cabecera del evento puede estar dentro de un shadow root o de un iframe
    // del mismo origen, y buscarla solo en el documento principal era quedarse
    // ciego justo donde estan los datos.
    try {
      const raices = roots
        .filter((entrada) => dom.isUsableRoot(entrada.root))
        .map((entrada) => entrada.kind === 'document'
          ? (entrada.root.body || entrada.root.documentElement)
          : entrada.root)
        .filter(Boolean);
      const descubierto = gamestateLib.extractGameStateFromRoots(
        raices, DOM_ADAPTER, state.gameMemory);
      state.gameState = descubierto.gameState;
      state.gameDiagnostics = descubierto.diagnostics;
      state.gameMemory = descubierto.memory;
      state.scoreboardNode = (descubierto.nodes && descubierto.nodes.score) ||
        buscarScoreboard(raices);
    } catch (error) {
      anotarError({ stage: 'gamestate', message: mensajeDe(error) });
    }

    mergeIntoState(encontrados);
    state.payload = buildVisiblePayload();
    // El envio lo decide el service worker: aqui solo se le entrega lo ultimo,
    // haya mercado o no. Si la aplicacion esta cerrada, el no envia nada.
    enviarAlPuente(state.payload);
    state.lastScanAt = now();
    state.scanCount += 1;
    state.lastScanMs = performance.now() - inicio;
    state.scanMsTotal += state.lastScanMs;
    state.scanMsMax = Math.max(state.scanMsMax, state.lastScanMs);
    state.headerCount = cabecerasTotales;
    state.rootCount = roots.length;
    state.rootsScanned = raicesRecorridas;
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
    if (nuevoVisible !== state.visibleMarket) {
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
    const registro = clave ? state.markets.get(clave) : null;
    return payloadLib.buildPayload({
      marketKey: registro ? registro.key : null,
      confidence: registro ? registro.confidence : 0,
      rawTitle: registro ? registro.headerText : '',
      eventId: state.eventId,
      eventName: eventName(),
      lines: registro && registro.existsInDom
        ? (registro.strictLines || registro.lines) : [],
      sideMarkers: registro ? registro.sideMarkers : null,
      observedAt: registro && registro.lastSeenAt ? registro.lastSeenAt : now(),
      gameState: state.gameState || null,
    });
  }

  /**
   * Contenedor del marcador aunque no se haya podido LEER el marcador.
   *
   * Si no sabemos interpretarlo, al menos podemos copiar como esta montado y
   * ajustar el lector contra HTML de verdad en lugar de a ciegas.
   */
  function buscarScoreboard(raices) {
    for (const raiz of raices || []) {
      try {
        const encontrados = gamestateLib.findScoreboardContainers(raiz, DOM_ADAPTER);
        if (encontrados.length) return encontrados[0];
      } catch (error) {
        anotarError({ stage: 'scoreboard', message: mensajeDe(error) });
      }
    }
    return null;
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
        anotarError({ stage: 'scan', message: mensajeDe(error) });
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
      anotarError({ stage: 'scan', message: mensajeDe(error) });
    }
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'hidden', 'aria-hidden', 'aria-selected', 'data-state'],
    });
    pushHistory('observerStarted', {});
    arrancarLatido();
  }

  /** Envia un mensaje al service worker sin lanzar nunca si no responde. */
  function avisarAlPuente(mensaje) {
    try {
      chrome.runtime.sendMessage(mensaje, () => {
        // Leer lastError evita el aviso "Unchecked runtime.lastError" cuando
        // el service worker esta dormido. No es un fallo que deba salir.
        void chrome.runtime.lastError;
      });
    } catch (error) {
      // La extension se recargo: la pagina seguira funcionando igualmente.
    }
  }

  /**
   * Entrega al service worker lo ultimo que se vio.
   *
   * Se manda TAMBIEN cuando no hay mercado, con el motivo: sin mercado el
   * puente tiene que poder seguir comprobando /health. Antes, si no habia
   * payload el service worker no hacia nada y el enlace se quedaba
   * DESCONECTADO para siempre aunque la aplicacion estuviera abierta.
   */
  function enviarAlPuente(resultado) {
    avisarAlPuente({
      type: 'VDIAG_PAYLOAD',
      payload: (resultado && resultado.payload) || null,
      rejected: (resultado && resultado.rejected) || [],
      underReview: !!(state.gameDiagnostics && state.gameDiagnostics.underReview),
    });
  }

  //: Latido de la pestana. En Manifest V3 el service worker se duerme, asi que
  //: el temporizador vive aqui: cada mensaje lo despierta y le da ocasion de
  //: reconectar. Con esto no hace falta el permiso "alarms".
  const HEARTBEAT_MS = 5000;
  let latido = null;

  function arrancarLatido() {
    if (latido) return;
    latido = setInterval(() => {
      avisarAlPuente({ type: 'VDIAG_HEARTBEAT' });
    }, HEARTBEAT_MS);
    avisarAlPuente({ type: 'VDIAG_HEARTBEAT' });   // sin esperar al primer ciclo
  }

  // ------------------------------------------------------------- mensajeria

  function snapshot() {
    return {
      url: location.href,
      startedAt: state.startedAt,
      lastScanAt: state.lastScanAt,
      scanCount: state.scanCount,
      lastScanMs: Math.round(state.lastScanMs),
      avgScanMs: state.scanCount
        ? Math.round(state.scanMsTotal / state.scanCount) : 0,
      maxScanMs: Math.round(state.scanMsMax),
      scansPerMinute: state.scanCount && state.lastScanAt
        ? Number((state.scanCount / Math.max(1, (state.lastScanAt - state.startedAt) / 60000))
            .toFixed(1))
        : 0,
      headerCount: state.headerCount || 0,
      pendingMutations: mutacionesDesdeElUltimoEscaneo,
      eventId: state.eventId === undefined ? null : state.eventId,
      visibleMarket: state.visibleMarket,
      environment: state.environment,
      // `container` se quita a proposito: es un nodo del DOM y `sendResponse`
      // no puede serializarlo.
      markets: Array.from(state.markets.values())
        .sort((a, b) => markets.sortKey(a.key) - markets.sortKey(b.key))
        .map(({ container, ...resto }) => resto),
      history: state.history.slice(-200),
      // Errores AGRUPADOS: una entrada por causa y raiz, con su cuenta. Antes
      // se enviaba una linea por ocurrencia y el popup mostraba la misma
      // frase cuarenta veces seguidas.
      errors: state.errorLog.list().slice(0, 12),
      activeErrors: state.errorLog.active(now()).length,
      skippedRoots: state.skippedRoots.slice(0, 12),
      unstableRoots: state.breaker.unstable(now()),
      rootCount: state.rootCount || 0,
      rootsScanned: state.rootsScanned || 0,
      gameState: state.gameState,
      gameDiagnostics: state.gameDiagnostics,
      payload: state.payload ? state.payload.payload : null,
      payloadRejected: state.payload ? state.payload.rejected : ['todavia sin escaneo'],
    };
  }

  /**
   * Estructura saneada de un trozo del DOM, para poder ajustar el lector
   * contra HTML real en vez de adivinando.
   */
  function copiarEstructura(que) {
    if (que === 'scoreboard') {
      if (!state.scoreboardNode) {
        const marcosAjenos = ((state.environment || {}).frames || [])
          .filter((f) => !f.sameOrigin).length;
        return marcosAjenos
          ? 'SCOREBOARD NO ACCESIBLE DESDE EL DOM PRINCIPAL\n\n' +
            `Hay ${marcosAjenos} iframe(s) de otro origen. El navegador impide leer su ` +
            'contenido, y esta bien que lo impida: no se va a intentar rodear.'
          : 'No se ha encontrado ningun bloque que se declare marcador en el DOM accesible.';
      }
      return structureLib.buildStructureReport('SCOREBOARD', state.scoreboardNode,
        DOM_ADAPTER, {
          marcador: state.gameState && state.gameState.scoreA !== undefined
            ? `${state.gameState.scoreA}-${state.gameState.scoreB}` : 'no leido',
          estado: state.gameDiagnostics && state.gameDiagnostics.score
            ? state.gameDiagnostics.score.status : '--',
        });
    }

    const registro = state.markets.get(state.visibleMarket) || mercadoConMasLineas();
    if (!registro || !registro.container) {
      return 'Todavia no hay ningun mercado reconocido del que copiar la estructura.';
    }
    return structureLib.buildStructureReport('MERCADO', registro.container, DOM_ADAPTER, {
      clave: registro.key,
      confianza: registro.confidence,
      seccion: registro.sectionLabel,
      titulo: registro.headerText,
      lineas: (registro.lines || [])
        .map((l) => `${l.line}: over ${l.overOdds ?? '--'} / under ${l.underOdds ?? '--'}`)
        .join(' | '),
    });
  }

  function mercadoConMasLineas() {
    let mejor = null;
    for (const registro of state.markets.values()) {
      if (!registro.existsInDom) continue;
      if (!mejor || (registro.lines || []).length > (mejor.lines || []).length) mejor = registro;
    }
    return mejor;
  }

  chrome.runtime.onMessage.addListener((mensaje, sender, sendResponse) => {
    if (!mensaje) return undefined;

    if (mensaje.type === 'VDIAG_GET_STATE') {
      try {
        sendResponse({ ok: true, state: snapshot() });
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message || error) });
      }
      return true;
    }

    if (mensaje.type === 'VDIAG_COPY_STRUCTURE') {
      try {
        sendResponse({ ok: true, texto: copiarEstructura(mensaje.what) });
      } catch (error) {
        sendResponse({ ok: false, error: String(error && error.message || error) });
      }
      return true;
    }

    return undefined;
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arrancar, { once: true });
  } else {
    arrancar();
  }
})();
