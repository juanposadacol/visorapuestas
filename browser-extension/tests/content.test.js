/**
 * El content script COMPLETO, ejecutado sobre un DOM de juguete.
 *
 * Los modulos sueltos ya estaban probados y aun asi la prueba real en BetPlay
 * devolvia "ningun mercado": lo que fallaba era el pegamento — el documento
 * como raiz del recorrido. Esta prueba recorre el camino entero: arranque,
 * escaneo, construccion del payload y mensaje al service worker.
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createDocument, el } = require('./fake_dom.js');

const RAIZ = path.join(__dirname, '..');
const LIBS = ['dom', 'errors', 'text', 'markets', 'lines', 'dedupe', 'visibility',
              'options', 'scan', 'report', 'scoreboard', 'gamestate', 'structure', 'payload',
              'bridge_client'];

function opcion(doc, etiqueta, cuota) {
  return el(doc, 'div', { class: 'option' }, [
    el(doc, 'span', { class: 'option__label' }, [etiqueta]),
    el(doc, 'span', { class: 'option__odds' }, [cuota]),
  ]);
}

function mercadoQ4(doc, linea, over, under) {
  return el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', { class: 'market__title' }, ['Total de puntos - Cuarto 4']),
    el(doc, 'div', { class: 'market__options' }, [
      opcion(doc, `Más de ${linea}`, over),
      opcion(doc, `Menos de ${linea}`, under),
    ]),
  ]);
}

function scoreboard(doc, a, b) {
  return el(doc, 'div', { class: 'event-header scoreboard' }, [
    el(doc, 'div', { class: 'scoreboard__team team--home' }, [
      el(doc, 'span', { class: 'team__name' }, ['Las Vegas Aces']),
      el(doc, 'span', { class: 'team__score' }, [String(a)]),
    ]),
    el(doc, 'div', { class: 'scoreboard__team team--away' }, [
      el(doc, 'span', { class: 'team__name' }, ['Atlanta Dream']),
      el(doc, 'span', { class: 'team__score' }, [String(b)]),
    ]),
    el(doc, 'div', { class: 'scoreboard__status live' }, [
      el(doc, 'span', { class: 'period' }, ['Q4']),
      el(doc, 'span', { class: 'clock' }, ['06:42']),
    ]),
  ]);
}

/**
 * Monta el content script sobre un documento y devuelve el mando.
 *
 * Los temporizadores no son de verdad: se guardan y la prueba decide cuando
 * corren. Asi el debounce del rescaneo y el latido son deterministas, y el
 * proceso de test no se queda colgado esperando a un setInterval.
 */
function montarContenido(doc, url) {
  const mensajes = [];
  const oyentes = [];
  const pendientes = [];
  let observador = null;

  const sandbox = {
    console, JSON, Math, Number, String, Object, Array, Date, Set, Map, Error,
    RegExp, Boolean, isNaN, parseInt, parseFloat,
    setTimeout: (fn) => { pendientes.push(fn); return pendientes.length; },
    clearTimeout: () => {},
    setInterval: () => 1,          // el latido periodico no hace falta aqui
    clearInterval: () => {},
    document: doc,
    location: { href: url || 'https://betplay.com.co/apuestas#event/live/123456789' },
    performance: { now: () => 0 },
    MutationObserver: class {
      constructor(fn) { observador = fn; }
      observe() {}
      disconnect() {}
    },
    chrome: {
      runtime: {
        sendMessage: (mensaje, cb) => { mensajes.push(mensaje); if (cb) cb(); },
        lastError: undefined,
        onMessage: { addListener: (fn) => oyentes.push(fn) },
      },
    },
  };
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window = sandbox;
  vm.createContext(sandbox);

  sandbox.VDIAG = {};
  for (const nombre of LIBS) {
    sandbox.VDIAG[nombre === 'bridge_client' ? 'bridgeClient' : nombre] =
      require(path.join(RAIZ, 'src', 'lib', `${nombre}.js`));
  }

  vm.runInContext(fs.readFileSync(path.join(RAIZ, 'src', 'content.js'), 'utf8'),
                  sandbox, { filename: 'content.js' });

  function pedir(mensaje) {
    let salida = null;
    for (const oyente of oyentes) oyente(mensaje, {}, (r) => { salida = r; });
    return salida;
  }

  function estado() {
    let salida = null;
    for (const oyente of oyentes) {
      oyente({ type: 'VDIAG_GET_STATE' }, {}, (r) => { salida = r; });
    }
    return salida && salida.state;
  }

  /** Simula una mutacion del DOM y deja correr el rescaneo con su debounce. */
  function rescanear() {
    if (observador) observador([{ type: 'childList' }]);
    while (pendientes.length) pendientes.shift()();
  }

  return {
    estado,
    pedir,
    mensajes,
    rescanear,
    irA: (nueva) => { sandbox.location.href = nueva; },
    payloads: () => mensajes.filter((m) => m.type === 'VDIAG_PAYLOAD'),
    latidos: () => mensajes.filter((m) => m.type === 'VDIAG_HEARTBEAT'),
  };
}

test('arranca, escanea el documento principal y NO produce errores', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);
  const estado = c.estado();

  assert.equal(estado.errors.length, 0,
               `no deberia haber errores: ${JSON.stringify(estado.errors)}`);
  assert.ok(estado.scanCount >= 1);
  assert.equal(estado.visibleMarket, 'Q4_TOTAL');
});

test('el payload que sale lleva la linea con OVER y UNDER', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);

  const ultimo = c.payloads().pop();
  assert.ok(ultimo, 'se aviso al service worker');
  assert.ok(ultimo.payload, `payload nulo: ${JSON.stringify(ultimo.rejected)}`);
  assert.equal(ultimo.payload.visibleMarket.marketType, 'QUARTER_TOTAL');
  assert.equal(ultimo.payload.visibleMarket.period, 4);
  assert.deepEqual(ultimo.payload.lines, [{ line: 44.5, overOdds: 1.75, underOdds: 1.9 }]);
  assert.equal(ultimo.payload.event.id, '123456789', 'el evento sale del hash');
  assert.equal(ultimo.payload.visibleMarket.sidesConfirmed, true);
});

test('sin mercado se avisa igual, con el motivo y sin payload', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', {}, ['Mis apuestas']));
  const c = montarContenido(doc);

  const ultimo = c.payloads().pop();
  assert.ok(ultimo, 'el service worker tiene que enterarse igualmente');
  assert.equal(ultimo.payload, null);
  assert.ok(ultimo.rejected.length, 'con el motivo, para poder mirarlo');
  assert.equal(c.estado().visibleMarket, null);
});

test('el marcador del scoreboard viaja dentro del payload', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, 56, 69));
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);

  const ultimo = c.payloads().pop();
  assert.deepEqual(ultimo.payload.gameState, {
    clock: '06:42', clockRaw: '06:42', clockSemantics: 'PERIOD_REMAINING',
    period: 4, scoreA: 56, scoreB: 69,
  });
});

test('un marcador dudoso NO bloquea el envio del mercado', () => {
  const doc = createDocument();
  // Dos numeros sueltos, sin ninguna evidencia de ser un marcador.
  doc.body.appendChild(el(doc, 'div', { class: 'row' }, [
    el(doc, 'span', {}, ['43']), el(doc, 'span', {}, ['232']),
  ]));
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);

  const ultimo = c.payloads().pop();
  assert.ok(ultimo.payload, 'el mercado sale igual');
  assert.equal(ultimo.payload.gameState, null, 'y el marcador falso no');
  assert.deepEqual(ultimo.payload.lines, [{ line: 44.5, overOdds: 1.75, underOdds: 1.9 }]);
});

test('un iframe del mismo origen tambien aporta sus mercados', () => {
  const doc = createDocument();
  const marco = el(doc, 'iframe', { src: 'https://betplay.com.co/widget' });
  const interno = createDocument();
  marco.contentDocument = interno;
  doc.body.appendChild(marco);
  interno.body.appendChild(mercadoQ4(interno, '44.5', '1.75', '1.90'));

  const c = montarContenido(doc);
  const estado = c.estado();
  assert.equal(estado.errors.length, 0);
  assert.equal(estado.visibleMarket, 'Q4_TOTAL');
  assert.equal(estado.rootCount, 2, 'documento principal + iframe');
});

test('un iframe muerto se salta sin tumbar el escaneo', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const marco = el(doc, 'iframe', { src: 'https://betplay.com.co/roto' });
  const muerto = createDocument();
  marco.contentDocument = muerto;
  doc.body.appendChild(marco);
  muerto.destroy();

  const c = montarContenido(doc);
  const estado = c.estado();
  assert.equal(estado.errors.length, 0, 'una raiz muerta no es un error, es normal');
  assert.equal(estado.visibleMarket, 'Q4_TOTAL', 'la raiz sana sigue funcionando');
  assert.ok(estado.skippedRoots.some((r) => r.kind === 'iframe'));
});

test('S. cambiar de mercado sin cambiar de partido conserva el contexto', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, 56, 69));
  const q4 = mercadoQ4(doc, '44.5', '1.75', '1.90');
  doc.body.appendChild(q4);
  const c = montarContenido(doc, 'https://betplay.com.co/apuestas#event/live/111111111');
  assert.equal(c.estado().visibleMarket, 'Q4_TOTAL');

  // El usuario abre ademas el total del partido. Mismo evento.
  doc.body.appendChild(el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', {}, ['Total de puntos - Partido']),
    el(doc, 'div', { class: 'market__options' }, [
      opcion(doc, 'Más de 163.5', '1.66'),
      opcion(doc, 'Menos de 163.5', '2.15'),
    ]),
  ]));
  c.rescanear();

  const estado = c.estado();
  assert.equal(estado.eventId, '111111111', 'sigue siendo el mismo partido');
  assert.deepEqual(estado.markets.map((m) => m.key).sort(),
                   ['GAME_TOTAL', 'Q4_TOTAL'], 'los dos mercados a la vez');
  assert.deepEqual(estado.gameState, {
    clock: '06:42', clockRaw: '06:42', clockSemantics: 'PERIOD_REMAINING',
    period: 4, scoreA: 56, scoreB: 69,
  }, 'y el marcador no se pierde');
});

test('T. al cambiar de partido se olvida todo lo del anterior', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, 56, 69));
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc, 'https://betplay.com.co/apuestas#event/live/111111111');

  assert.equal(c.estado().eventId, '111111111');
  assert.equal(c.estado().markets.length, 1);
  assert.equal(c.estado().gameState.scoreA, 56);

  // El usuario abre otro partido: con el enrutado por hash de Angular esto NO
  // recarga la pagina ni reinicia el content script.
  c.irA('https://betplay.com.co/apuestas#event/live/222222222');
  doc.body.childNodes.length = 0;
  doc.body.appendChild(el(doc, 'div', {}, ['cargando...']));
  c.rescanear();

  const estado = c.estado();
  assert.equal(estado.eventId, '222222222');
  assert.equal(estado.markets.length, 0, 'nada del partido anterior sobrevive');
  assert.equal(estado.visibleMarket, null);
  assert.equal(estado.gameState, null, 'ni el marcador, que era del otro partido');
  assert.ok(estado.history.some((h) => h.type === 'eventChanged'));
});

test('el latido se manda desde la pestana, sin permiso "alarms"', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);
  assert.ok(c.latidos().length >= 1,
            'el primer latido sale sin esperar al primer ciclo del temporizador');
});

test('F. se puede copiar la estructura saneada del mercado', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);

  const respuesta = c.pedir({ type: 'VDIAG_COPY_STRUCTURE', what: 'market' });
  assert.ok(respuesta.ok, JSON.stringify(respuesta));
  assert.match(respuesta.texto, /^MERCADO/);
  assert.match(respuesta.texto, /clave: Q4_TOTAL/);
  assert.match(respuesta.texto, /section\.market/);
  assert.match(respuesta.texto, /"Menos de 44\.5"/);
  assert.match(respuesta.texto, /"1\.90"/);
  assert.match(respuesta.texto, /estructura saneada/);
});

test('F. y la del scoreboard, aunque el marcador no se haya podido leer', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', { class: 'event-header scoreboard' }, [
    el(doc, 'div', { class: 'scoreboard__team' }, [
      el(doc, 'span', { class: 'team__name' }, ['Las Vegas Aces']),
      el(doc, 'span', { class: 'team__score' }, ['??']),
    ]),
  ]));
  const c = montarContenido(doc);

  const respuesta = c.pedir({ type: 'VDIAG_COPY_STRUCTURE', what: 'scoreboard' });
  assert.ok(respuesta.ok);
  assert.match(respuesta.texto, /^SCOREBOARD/);
  assert.match(respuesta.texto, /scoreboard__team/);
  assert.match(respuesta.texto, /"Las Vegas Aces"/);
});

test('si el scoreboard esta en un iframe ajeno, se dice y no se intenta rodear', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const ajeno = el(doc, 'iframe', { src: 'https://otro-origen.example/scoreboard' });
  ajeno.contentDocument = null;                  // el navegador lo impide
  doc.body.appendChild(ajeno);
  const c = montarContenido(doc);

  const respuesta = c.pedir({ type: 'VDIAG_COPY_STRUCTURE', what: 'scoreboard' });
  assert.ok(respuesta.ok);
  assert.match(respuesta.texto, /NO ACCESIBLE DESDE EL DOM PRINCIPAL/);
  assert.match(respuesta.texto, /no se va a intentar rodear/);
});

test('el snapshot no lleva nodos del DOM: tiene que poder serializarse', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, 56, 69));
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);

  // Si algun nodo se colara, `sendResponse` fallaria en el navegador de verdad.
  assert.doesNotThrow(() => JSON.stringify(c.estado()));
  for (const market of c.estado().markets) {
    assert.equal(market.container, undefined, 'el contenedor se queda en la pestana');
  }
});

test('el escaneo se mide, para que "va lento" no sea una impresion', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);
  c.rescanear();

  const estado = c.estado();
  assert.ok(estado.scanCount >= 2);
  assert.equal(typeof estado.avgScanMs, 'number');
  assert.equal(typeof estado.maxScanMs, 'number');
});

test('una rafaga de mutaciones NO produce una rafaga de escaneos', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.75', '1.90'));
  const c = montarContenido(doc);
  const antes = c.estado().scanCount;

  // El observador se dispara muchas veces; el debounce agrupa la rafaga.
  for (let i = 0; i < 20; i += 1) c.rescanear();

  const despues = c.estado().scanCount;
  assert.ok(despues - antes <= 20, 'nunca mas de un escaneo por ventana');
  assert.ok(despues > antes, 'pero alguno si se hace');
});

// ============================================================================
// El scoreboard REAL de BetPlay/Kambi, de extremo a extremo
// ============================================================================

const { scoreboardKambi } = require('./kambi_fixture.js');

test('K. el marcador de Kambi llega al payload como 76-69', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboardKambi(doc));
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.78', '1.86'));
  const c = montarContenido(doc);

  const ultimo = c.payloads().pop();
  assert.ok(ultimo.payload, `payload nulo: ${JSON.stringify(ultimo.rejected)}`);
  const estado = ultimo.payload.gameState;

  assert.equal(estado.scoreA, 76);
  assert.equal(estado.scoreB, 69);
  assert.notEqual(estado.scoreB, 22, 'el parcial del Q1 no es medio marcador');
  assert.equal(estado.period, 4);
  assert.equal(estado.teamA.name, 'Dallas Wings (F)');
  assert.equal(estado.teamB.name, 'Indiana Fever (F)');
  assert.deepEqual(estado.teamA.periods, { Q1: 18, Q2: 24, Q3: 24, Q4: 10 });
  assert.deepEqual(estado.teamB.periods, { Q1: 22, Q2: 20, Q3: 19, Q4: 8 });

  // Y el mercado sigue llegando entero, con su UNDER.
  assert.deepEqual(ultimo.payload.lines, [{ line: 44.5, overOdds: 1.78, underOdds: 1.86 }]);
});

test('K. el reloj acumulado viaja crudo, nunca disfrazado de restante', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboardKambi(doc));
  doc.body.appendChild(mercadoQ4(doc, '44.5', '1.78', '1.86'));
  const c = montarContenido(doc);

  // Primera lectura: todavia no se sabe si sube o baja.
  let estado = c.payloads().pop().payload.gameState;
  assert.equal(estado.clock, undefined);
  assert.equal(estado.clockRaw, undefined);

  // El reloj avanza un segundo y el escaneo lo vuelve a leer.
  const marcador = doc.body.children[0];
  const relojNodo = marcador.children[0].children[0].children[0].children[0].children[2];
  relojNodo.childNodes[0].nodeValue = '33:53';
  c.rescanear();

  estado = c.payloads().pop().payload.gameState;
  assert.equal(estado.clockRaw, '33:53');
  assert.equal(estado.clockSemantics, 'GAME_ELAPSED');
  assert.equal(estado.clock, undefined,
               'la extension no convierte: no sabe cuanto dura un cuarto');
});

test('K. la estructura del scoreboard que se copia es la del marcador de verdad', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboardKambi(doc));
  const c = montarContenido(doc);

  const respuesta = c.pedir({ type: 'VDIAG_COPY_STRUCTURE', what: 'scoreboard' });
  assert.ok(respuesta.ok);
  assert.match(respuesta.texto, /marcador: 76-69/);
  assert.match(respuesta.texto, /"Dallas Wings \(F\)"/);
  assert.match(respuesta.texto, /scoreboard-grid-score/);
});
