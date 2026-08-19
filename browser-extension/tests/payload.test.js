const test = require('node:test');
const assert = require('node:assert');
const { buildPayload, validatePayload, toWireMarket, eventIdFromUrl,
        payloadSignature, PROTOCOL_VERSION } = require('../src/lib/payload.js');

function payloadValido(extra) {
  return buildPayload({
    marketKey: 'Q3_TOTAL', confidence: 0.95, rawTitle: 'Total de puntos - Cuarto 3',
    eventId: '123456', eventName: 'A vs B', sideMarkers: { both: true },
    lines: [{ line: 43.5, overOdds: 1.80, underOdds: 1.90 }],
    ...extra,
  }).payload;
}

test('traduce las claves internas al vocabulario del dominio Python', () => {
  assert.deepEqual(toWireMarket('GAME_TOTAL'), { marketType: 'GAME_TOTAL', period: null, half: null });
  assert.deepEqual(toWireMarket('Q3_TOTAL'), { marketType: 'QUARTER_TOTAL', period: 3, half: null });
  assert.deepEqual(toWireMarket('SECOND_HALF_TOTAL'), { marketType: 'HALF_TOTAL', period: null, half: 2 });
  assert.equal(toWireMarket('UNKNOWN'), null);
});

test('extrae el identificador del evento de la URL', () => {
  assert.equal(eventIdFromUrl('https://betplay.com.co/apuestas/evento-12345678'), '12345678');
  assert.equal(eventIdFromUrl('https://betplay.com.co/deportes/1234567/algo'), '1234567');
  assert.equal(eventIdFromUrl('no es una url'), null);
});

test('un payload correcto pasa su propia validacion', () => {
  const p = payloadValido();
  assert.equal(p.protocol, PROTOCOL_VERSION);
  assert.equal(validatePayload(p).valid, true);
});

test('rechaza lo que no debe viajar', () => {
  const casos = [
    [{ lines: [] }, 'sin lineas'],
    [{ confidence: 0.5 }, 'confianza'],
    [{ marketKey: 'UNKNOWN' }, 'mercado'],
    [{ lines: [{ line: 43.5 }] }, 'sin lineas'],
  ];
  for (const [extra, esperado] of casos) {
    const { payload, rejected } = buildPayload({
      marketKey: 'Q3_TOTAL', confidence: 0.95,
      lines: [{ line: 43.5, overOdds: 1.8, underOdds: 1.9 }], ...extra });
    assert.equal(payload, null, JSON.stringify(extra));
    assert.ok(rejected.join(' ').includes(esperado), rejected.join(' '));
  }
});

test('la validacion detecta payloads manipulados', () => {
  const casos = {
    'protocolo desconocido': (p) => { p.protocol = 99; },
    'fuente desconocida': (p) => { p.source = 'otra'; },
    'observedAt invalido': (p) => { p.observedAt = 'ayer'; },
    'marketType desconocido': (p) => { p.visibleMarket.marketType = 'CUALQUIERA'; },
    'period invalido': (p) => { p.visibleMarket.period = 9; },
    'confianza insuficiente': (p) => { p.visibleMarket.confidence = 0.2; },
    'linea fuera de rango': (p) => { p.lines[0].line = 5000; },
    'cuota fuera de rango': (p) => { p.lines[0].overOdds = 0.2; },
  };
  for (const [motivo, romper] of Object.entries(casos)) {
    const p = payloadValido();
    romper(p);
    const r = validatePayload(p);
    assert.equal(r.valid, false, motivo);
    assert.ok(r.errors.join(' ').includes(motivo.split(' ')[0]), `${motivo}: ${r.errors}`);
  }
});

test('half debe ser 1 o 2 en un mercado de mitad', () => {
  const p = payloadValido({ marketKey: 'FIRST_HALF_TOTAL' });
  assert.equal(p.visibleMarket.half, 1);
  p.visibleMarket.half = 5;
  assert.equal(validatePayload(p).valid, false);
});

test('una linea puede llevar solo un lado', () => {
  const p = payloadValido({ lines: [{ line: 43.5, overOdds: 1.80, underOdds: null }] });
  assert.equal(validatePayload(p).valid, true);
});

test('la firma cambia cuando cambia una cuota', () => {
  const a = payloadValido();
  const b = payloadValido({ lines: [{ line: 43.5, overOdds: 1.80, underOdds: 1.95 }] });
  assert.notEqual(payloadSignature(a), payloadSignature(b));
  assert.equal(payloadSignature(a), payloadSignature(payloadValido()));
});

test('la firma cambia al cambiar de mercado o de evento', () => {
  const base = payloadValido();
  assert.notEqual(payloadSignature(base), payloadSignature(payloadValido({ marketKey: 'Q4_TOTAL' })));
  assert.notEqual(payloadSignature(base), payloadSignature(payloadValido({ eventId: '999' })));
});

test('se recorta un numero absurdo de lineas', () => {
  const muchas = Array.from({ length: 60 }, (_, i) => ({ line: 20.5 + i, overOdds: 1.9 }));
  assert.equal(buildPayload({ marketKey: 'Q3_TOTAL', confidence: 0.95, lines: muchas }).payload, null);
});
