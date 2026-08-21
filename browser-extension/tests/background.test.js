/**
 * El service worker, ejecutado de verdad contra un `chrome` y un `fetch` de
 * mentira.
 *
 * Existe por un fallo REAL: `Invoke-RestMethod http://127.0.0.1:8765/health`
 * devolvia `status: ok` y al mismo tiempo el popup decia
 *
 *     APP LOCAL
 *     DESCONECTADA
 *
 * porque el sondeo de salud colgaba del camino del payload:
 *
 *     async function procesar(payload) {
 *       if (!payload) return;          // <-- aqui moria el sondeo
 *       ...
 *     }
 *
 * Sin mercado reconocido no habia payload, sin payload no habia sondeo, y sin
 * sondeo el enlace se quedaba DESCONECTADO para siempre. Estas pruebas fijan
 * que los dos ejes son independientes.
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const RAIZ = path.join(__dirname, '..');
const LIBS = ['dom', 'errors', 'text', 'markets', 'lines', 'dedupe', 'visibility',
              'options', 'scan', 'report', 'scoreboard', 'gamestate', 'structure', 'payload',
              'bridge_client'];

/** Payload valido minimo, del mismo tipo que construye el content script. */
function payloadValido(linea = 44.5) {
  return {
    protocol: 1,
    source: 'betplay',
    observedAt: new Date().toISOString(),
    event: { id: '123456789', name: 'Aces vs Dream' },
    visibleMarket: { marketType: 'QUARTER_TOTAL', period: 4, half: null,
                     confidence: 0.95, rawTitle: 'Total de puntos - Cuarto 4',
                     sidesConfirmed: true },
    lines: [{ line: linea, overOdds: 1.75, underOdds: 1.9 }],
    gameState: null,
  };
}

/**
 * Monta el service worker en un contexto aislado y devuelve el mando:
 * enviar mensajes, decidir que contesta /health y leer el estado del puente.
 */
function montarWorker(opciones) {
  const cfg = { appViva: true, ...(opciones || {}) };
  const peticiones = [];
  const oyentes = [];

  // Reloj gobernado por la prueba: el reintento del puente usa espera
  // creciente, y no se va a dormir de verdad varios segundos por test.
  let reloj = 1700000000000;
  class DateFalso extends Date {
    constructor(...args) { super(...(args.length ? args : [reloj])); }
    static now() { return reloj; }
  }

  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    AbortController,
    Date: DateFalso,
    JSON,
    Math,
    Number,
    Promise,
    Error,
    importScripts: () => {},
    fetch: async (url, opts) => {
      peticiones.push({ url, method: (opts && opts.method) || 'GET',
                         body: opts && opts.body ? JSON.parse(opts.body) : null });
      if (!cfg.appViva) throw new Error('Failed to fetch');
      if (String(url).endsWith('/health')) {
        return { ok: true, status: 200,
                 json: async () => ({ status: 'ok', app: 'VisorApuestas',
                                      version: '1.1.0', protocol: 1 }) };
      }
      return { ok: true, status: 204, json: async () => ({}) };
    },
    chrome: {
      runtime: { onMessage: { addListener: (fn) => oyentes.push(fn) } },
      storage: { local: { get: (_valores, cb) => cb({ bridgePort: 8765 }),
                          set: () => {} } },
    },
  };
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  // Las librerias se cargan desde Node y se cuelgan del `self` del sandbox,
  // que es exactamente donde las deja `importScripts` en el navegador.
  sandbox.VDIAG = {};
  for (const nombre of LIBS) {
    sandbox.VDIAG[nombre === 'bridge_client' ? 'bridgeClient' : nombre] =
      require(path.join(RAIZ, 'src', 'lib', `${nombre}.js`));
  }

  vm.runInContext(fs.readFileSync(path.join(RAIZ, 'src', 'background.js'), 'utf8'),
                  sandbox, { filename: 'background.js' });

  async function enviar(mensaje) {
    let respuesta = null;
    for (const oyente of oyentes) oyente(mensaje, {}, (r) => { respuesta = r; });
    // Los manejadores lanzan trabajo asincrono (el sondeo): se deja correr.
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    return respuesta;
  }

  async function puente() {
    return (await enviar({ type: 'VDIAG_BRIDGE_STATE' })).bridge;
  }

  return {
    enviar,
    puente,
    avanzar: (ms) => { reloj += ms; },
    ahora: () => reloj,
    peticiones,
    salud: () => peticiones.filter((p) => p.url.endsWith('/health')).length,
    envios: () => peticiones.filter((p) => p.url.includes('/v1/browser-state')).length,
    apagarApp: () => { cfg.appViva = false; },
    encenderApp: () => { cfg.appViva = true; },
  };
}

test('O. aplicacion disponible y payload null: CONNECTED, mercado NONE', async () => {
  const w = montarWorker({ appViva: true });
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: null,
                   rejected: ['no hay mercado visible identificado'] });
  const puente = await w.puente();

  assert.equal(puente.link, 'CONNECTED', 'el enlace no depende de que haya mercado');
  assert.equal(puente.market, 'NONE');
  assert.equal(puente.appVersion, '1.1.0');
  assert.ok(w.salud() >= 1, 'se comprobo /health aunque no hubiera payload');
  assert.equal(w.envios(), 0, 'sin mercado no se envia nada');
  assert.deepEqual(puente.marketRejected, ['no hay mercado visible identificado']);
});

test('P. aplicacion no disponible y payload null: DISCONNECTED', async () => {
  const w = montarWorker({ appViva: false });
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: null, rejected: [] });
  const puente = await w.puente();

  assert.equal(puente.link, 'DISCONNECTED');
  assert.equal(puente.market, 'NONE');
});

test('Q. si la aplicacion aparece despues, el enlace se recupera solo', async () => {
  const w = montarWorker({ appViva: false });
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: null, rejected: [] });
  assert.equal((await w.puente()).link, 'DISCONNECTED');

  // El usuario abre VisorApuestas; la pestana de BetPlay NO se recarga.
  w.encenderApp();
  // El latido del content script despierta al service worker. El primero cae
  // dentro de la espera del reintento; unos segundos despues, ya no.
  await w.enviar({ type: 'VDIAG_HEARTBEAT' });
  assert.equal((await w.puente()).link, 'DISCONNECTED', 'aun no toca reintentar');

  w.avanzar(6000);
  await w.enviar({ type: 'VDIAG_HEARTBEAT' });

  assert.equal((await w.puente()).link, 'CONNECTED',
               'reconecta sin recargar BetPlay y sin mercado todavia');
});

test('el latido mantiene el enlace aunque no llegue ningun payload', async () => {
  const w = montarWorker({ appViva: true });
  await w.enviar({ type: 'VDIAG_HEARTBEAT' });
  const puente = await w.puente();
  assert.equal(puente.link, 'CONNECTED');
  assert.equal(puente.market, 'NONE');
  assert.equal(puente.hasPayload, false);
});

test('con aplicacion viva y mercado valido se envia y el mercado es VALID', async () => {
  const w = montarWorker({ appViva: true });
  await w.enviar({ type: 'VDIAG_HEARTBEAT' });         // enlace ya establecido
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: payloadValido(), rejected: [] });

  const puente = await w.puente();
  assert.equal(puente.link, 'CONNECTED');
  assert.equal(puente.market, 'VALID');
  assert.equal(w.envios(), 1);
  assert.equal(puente.sent, 1);
  assert.ok(puente.lastSentAt > 0);
});

test('un payload solo de gameState se valida y llega al mismo puente', async () => {
  const w = montarWorker({ appViva: true });
  const parcial = payloadValido();
  parcial.visibleMarket = null;
  parcial.lines = [];
  parcial.gameState = { scoreA: 89, scoreB: 66, period: 4 };
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: parcial, rejected: [] });

  const puente = await w.puente();
  assert.equal(puente.market, 'STATE_ONLY');
  assert.equal(puente.hasGameState, true);
  assert.equal(w.envios(), 1);
  const enviado = w.peticiones.find((p) => p.url.includes('/v1/browser-state'));
  assert.equal(enviado.body.gameState.scoreA, 89);
  assert.deepEqual(enviado.body.lines, []);
});

test('mercado detectado sin lineas se envia como NO_LINES', async () => {
  const w = montarWorker({ appViva: true });
  const parcial = payloadValido();
  parcial.lines = [];
  parcial.gameState = { scoreA: 91, scoreB: 66, period: 4 };
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: parcial,
                   rejected: ['sin lineas actuales'] });
  const puente = await w.puente();
  assert.equal(puente.market, 'NO_LINES');
  assert.equal(puente.currentLines, 0);
  assert.equal(w.envios(), 1);
});

test('un payload que no cumple el contrato es REJECTED y no se envia', async () => {
  const w = montarWorker({ appViva: true });
  const malo = payloadValido();
  malo.visibleMarket.confidence = 0.5;                // por debajo del minimo
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: malo, rejected: [] });

  const puente = await w.puente();
  assert.equal(puente.link, 'CONNECTED', 'el enlace sigue bien: el problema son los datos');
  assert.equal(puente.market, 'REJECTED');
  assert.equal(w.envios(), 0);
});

test('una lectura en revision se marca UNDER_REVIEW sin tocar el enlace', async () => {
  const w = montarWorker({ appViva: true });
  await w.enviar({ type: 'VDIAG_PAYLOAD', payload: null, rejected: [], underReview: true });
  const puente = await w.puente();
  assert.equal(puente.link, 'CONNECTED');
  assert.equal(puente.market, 'UNDER_REVIEW');
});

test('si la aplicacion se cierra estando conectados, se acaba notando', async () => {
  const w = montarWorker({ appViva: true });
  await w.enviar({ type: 'VDIAG_HEARTBEAT' });
  assert.equal((await w.puente()).link, 'CONNECTED');

  w.apagarApp();
  // Estando conectados no se sondea en cada latido: hace falta que pase el
  // intervalo de comprobacion.
  w.avanzar(6000);
  await w.enviar({ type: 'VDIAG_HEARTBEAT' });
  assert.equal((await w.puente()).link, 'DISCONNECTED',
               'la aplicacion cerrada se nota aunque no haya nada que enviar');
});
