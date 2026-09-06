const test = require('node:test');
const assert = require('node:assert');
const { decideSend, retryDelay, nextLinkState, LINK } = require('../src/lib/bridge_client.js');
const bridge = require('../src/lib/bridge_client.js');
const { buildPayload, payloadSignature } = require('../src/lib/payload.js');

function payload(cuota) {
  return buildPayload({
    marketKey: 'Q4_TOTAL', confidence: 0.95, rawTitle: 'Total de puntos - Cuarto 4',
    eventId: '9876543', sideMarkers: { both: true },
    lines: [{ line: 44.5, overOdds: 1.75, underOdds: cuota || 1.90 }],
  }).payload;
}

test('sin payload no se envia nada', () => {
  assert.deepEqual(decideSend({ payload: null, now: 0 }), { send: false, reason: 'nothing' });
});

test('el primer payload se envia', () => {
  const r = decideSend({ payload: payload(), lastSignature: null, lastSentAt: null, now: 1000 });
  assert.equal(r.send, true);
  assert.equal(r.reason, 'change');
});

test('un cambio de cuota se envia en cuanto pasa el intervalo minimo', () => {
  const anterior = payloadSignature(payload(1.90));
  const r = decideSend({ payload: payload(2.05), lastSignature: anterior,
                         lastSentAt: 1000, now: 1300 });
  assert.equal(r.send, true);
  assert.equal(r.reason, 'change');
});

test('no se envian cien paquetes por segundo', () => {
  const anterior = payloadSignature(payload(1.90));
  const r = decideSend({ payload: payload(2.05), lastSignature: anterior,
                         lastSentAt: 1000, now: 1100 });
  assert.equal(r.send, false);
  assert.equal(r.reason, 'throttled');
});

test('sin cambios se manda un latido cada segundo', () => {
  const firma = payloadSignature(payload());
  const pronto = decideSend({ payload: payload(), lastSignature: firma,
                              lastSentAt: 1000, now: 1500 });
  assert.equal(pronto.send, false);
  const toca = decideSend({ payload: payload(), lastSignature: firma,
                            lastSentAt: 1000, now: 2100 });
  assert.equal(toca.send, true);
  assert.equal(toca.reason, 'heartbeat');
});

test('el latido distingue "no cambio nada" de "se corto la conexion"', () => {
  // Dos ciclos sin cambios producen dos latidos separados en el tiempo.
  const firma = payloadSignature(payload());
  const primero = decideSend({ payload: payload(), lastSignature: firma,
                               lastSentAt: 1000, now: 2000 });
  const segundo = decideSend({ payload: payload(), lastSignature: firma,
                               lastSentAt: 2000, now: 3000 });
  assert.ok(primero.send && segundo.send);
});

test('el ritmo es configurable', () => {
  const anterior = payloadSignature(payload(1.90));
  const r = decideSend({ payload: payload(2.05), lastSignature: anterior,
                         lastSentAt: 1000, now: 1100 }, { minIntervalMs: 50 });
  assert.equal(r.send, true);
});

test('el reintento crece pero se acota', () => {
  assert.deepEqual([0, 1, 2, 3, 10].map((i) => retryDelay(i)),
                   [2000, 4000, 8000, 15000, 15000]);
  assert.equal(retryDelay(-5), 2000);
});

test('el estado del enlace se deriva del resultado', () => {
  const conectado = nextLinkState(null, 'ok');
  assert.equal(conectado.state, LINK.CONNECTED);
  assert.equal(conectado.attempt, 0);

  const fallo = nextLinkState(conectado, 'no se pudo conectar');
  assert.equal(fallo.state, LINK.DISCONNECTED);
  assert.equal(fallo.attempt, 1);
  assert.equal(fallo.error, 'no se pudo conectar');

  const otroFallo = nextLinkState(fallo, 'sigue sin responder');
  assert.equal(otroFallo.attempt, 2);          // el reintento se va espaciando

  const recuperado = nextLinkState(otroFallo, 'ok');
  assert.equal(recuperado.state, LINK.CONNECTED);
  assert.equal(recuperado.attempt, 0);         // y se reinicia al reconectar
  assert.equal(recuperado.error, '');
});

test('recuperacion automatica sin tener que recargar la pagina', () => {
  // La aplicacion estaba cerrada durante varios intentos...
  let estado = nextLinkState(null, 'fallo');
  for (let i = 0; i < 5; i += 1) estado = nextLinkState(estado, 'fallo');
  assert.equal(estado.state, LINK.DISCONNECTED);
  assert.ok(retryDelay(estado.attempt) <= 15000);
  // ...y en cuanto responde, se vuelve a enviar sin intervencion.
  estado = nextLinkState(estado, 'ok');
  assert.equal(estado.state, LINK.CONNECTED);
});

// --------------------------------------------------- los dos ejes, separados

test('el sondeo NO depende de que haya payload', () => {
  const desconectado = { state: bridge.LINK.DISCONNECTED, attempt: 0, error: '' };
  // No se le pasa payload por ningun lado: la decision no lo necesita.
  assert.equal(bridge.shouldProbe({ link: desconectado, now: 1000, nextProbeAt: 0 }), true);
  assert.equal(bridge.shouldProbe({ link: desconectado, now: 1000, nextProbeAt: 5000 }), false,
               'todavia dentro de la espera del reintento');
});

test('estando conectados se vuelve a comprobar cada cierto tiempo', () => {
  const conectado = { state: bridge.LINK.CONNECTED, attempt: 0, error: '' };
  assert.equal(bridge.shouldProbe({ link: conectado, now: 10000, lastOkAt: 9000 }), false);
  assert.equal(bridge.shouldProbe({ link: conectado, now: 15000, lastOkAt: 9000 }), true);
});

test('no se lanzan dos sondeos a la vez', () => {
  const desconectado = { state: bridge.LINK.DISCONNECTED, attempt: 0, error: '' };
  assert.equal(bridge.shouldProbe(
    { link: desconectado, now: 1000, nextProbeAt: 0, probeInFlight: true }), false);
});

test('CONNECTING mientras se comprueba, sin parpadear si ya estaba conectado', () => {
  const nada = bridge.nextLinkState(null, 'probing');
  assert.equal(nada.state, bridge.LINK.CONNECTING);

  const conectado = { state: bridge.LINK.CONNECTED, attempt: 0, error: '' };
  assert.equal(bridge.nextLinkState(conectado, 'probing').state, bridge.LINK.CONNECTED);
});

test('la espera crece mientras sigue fallando, tambien desde CONNECTING', () => {
  let link = bridge.nextLinkState(null, 'probing');
  link = bridge.nextLinkState(link, 'aplicacion no disponible');
  assert.equal(link.attempt, 1);
  link = bridge.nextLinkState(bridge.nextLinkState(link, 'probing'), 'no disponible');
  assert.equal(link.attempt, 2, 'pasar por CONNECTING no reinicia la cuenta');
});

test('conectado pero sin confirmar hace demasiado: STALE', () => {
  const conectado = { state: bridge.LINK.CONNECTED, attempt: 0, error: '' };
  assert.equal(bridge.linkStateFor(conectado, 1000, 5000), bridge.LINK.CONNECTED);
  assert.equal(bridge.linkStateFor(conectado, 1000, 60000), bridge.LINK.STALE);
  const caido = { state: bridge.LINK.DISCONNECTED, attempt: 3, error: 'x' };
  assert.equal(bridge.linkStateFor(caido, 1000, 60000), bridge.LINK.DISCONNECTED,
               'lo que esta caido no se disfraza de STALE');
});

test('el estado del mercado habla solo de los datos', () => {
  assert.equal(bridge.marketState({ payload: null }), bridge.MARKET.NONE);
  assert.equal(bridge.marketState({ payload: {} }), bridge.MARKET.NONE);
  assert.equal(bridge.marketState({ payload: {
    visibleMarket: { marketType: 'GAME_TOTAL' }, lines: [], gameState: null,
  }}), bridge.MARKET.NO_LINES);
  assert.equal(bridge.marketState({ payload: {
    visibleMarket: null, lines: [], gameState: { scoreA: 89, scoreB: 66 },
  }}), bridge.MARKET.STATE_ONLY);
  assert.equal(bridge.marketState({ payload: {
    visibleMarket: { marketType: 'GAME_TOTAL' }, lines: [{ line: 195.5 }],
  }}), bridge.MARKET.VALID);
  assert.equal(bridge.marketState({ payload: {}, validation: { valid: false } }),
               bridge.MARKET.REJECTED);
  assert.equal(bridge.marketState({ payload: {}, underReview: true }),
               bridge.MARKET.UNDER_REVIEW);
  assert.equal(bridge.marketState({ payload: null, underReview: true }),
               bridge.MARKET.UNDER_REVIEW,
               'una lectura dudosa sin publicar tampoco es "no hay nada"');
});
