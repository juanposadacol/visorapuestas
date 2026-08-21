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

test('el marcador y los parciales en vivo forman parte de la firma', () => {
  const team = (q3, total) => ({
    name: 'Baréin', total, periods: { Q1: 21, Q2: 25, Q3: q3, Q4: 0 },
  });
  const a = payloadValido({ gameState: {
    scoreA: 65, scoreB: 47, teamA: team(19, 65),
    teamB: { name: 'Arabia Saudí', total: 47,
      periods: { Q1: 26, Q2: 18, Q3: 3, Q4: 0 } },
  } });
  const b = payloadValido({ gameState: {
    scoreA: 67, scoreB: 47, teamA: team(21, 67),
    teamB: { name: 'Arabia Saudí', total: 47,
      periods: { Q1: 26, Q2: 18, Q3: 3, Q4: 0 } },
  } });
  assert.equal(validatePayload(a).valid, true);
  assert.notEqual(payloadSignature(a), payloadSignature(b));
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

// ------------------------------------------------ el evento, con hash routing
//
// BetPlay enruta con almohadilla:  .../apuestas#event/live/123456789
// Mirar solo `pathname` devolvia "/apuestas" para TODOS los partidos, asi que
// al cambiar de evento nada se enteraba y se podian mezclar dos partidos.

const payloadLib = require('../src/lib/payload.js');

test('R. el identificador se saca del hash de Angular', () => {
  const ids = [
    ['https://betplay.com.co/apuestas#event/live/123456789', '123456789'],
    ['https://betplay.com.co/apuestas#/event/live/987654321/markets', '987654321'],
    ['https://betplay.com.co/apuestas#evento/live/555444333', '555444333'],
    ['https://betplay.com.co/apuestas#event/live/123456789?tab=todo', '123456789'],
    ['https://betplay.com.co/apuestas#event/live/12345', '12345'],
  ];
  for (const [url, esperado] of ids) {
    assert.equal(payloadLib.eventIdFromUrl(url), esperado, url);
  }
});

test('R. dos partidos distintos dan identificadores distintos', () => {
  const a = payloadLib.eventIdFromUrl('https://betplay.com.co/apuestas#event/live/111111111');
  const b = payloadLib.eventIdFromUrl('https://betplay.com.co/apuestas#event/live/222222222');
  assert.notEqual(a, b, 'esto es lo que evita mezclar dos partidos');
});

test('sin numero en el hash se usa la ruta del hash, no el pathname', () => {
  assert.equal(payloadLib.eventIdFromUrl('https://betplay.com.co/apuestas#sports/basketball'),
               'sports/basketball');
  assert.equal(payloadLib.eventIdFromUrl('https://betplay.com.co/apuestas'), '/apuestas');
  assert.equal(payloadLib.eventIdFromUrl(''), null);
});

test('S. si cambia el mercado pero no el partido, la firma cambia y el evento no', () => {
  const url = 'https://betplay.com.co/apuestas#event/live/123456789';
  const comun = { confidence: 0.95, eventId: payloadLib.eventIdFromUrl(url),
                  sideMarkers: { both: true } };
  const q4 = payloadLib.buildPayload({ ...comun, marketKey: 'Q4_TOTAL',
    rawTitle: 'Total de puntos - Cuarto 4',
    lines: [{ line: 44.5, overOdds: 1.75, underOdds: 1.9 }] }).payload;
  const partido = payloadLib.buildPayload({ ...comun, marketKey: 'GAME_TOTAL',
    rawTitle: 'Total de puntos - Prorroga incluida',
    lines: [{ line: 163.5, overOdds: 1.66, underOdds: 2.15 }] }).payload;

  assert.equal(q4.event.id, partido.event.id, 'mismo partido');
  assert.notEqual(payloadLib.payloadSignature(q4), payloadLib.payloadSignature(partido),
                  'pero distinta firma: hay que reenviar');
});

test('T. la firma incluye el partido, asi que cambiar de evento fuerza reenvio', () => {
  const construir = (eventId) => payloadLib.buildPayload({
    marketKey: 'Q4_TOTAL', confidence: 0.95, eventId,
    rawTitle: 'Total de puntos - Cuarto 4', sideMarkers: { both: true },
    lines: [{ line: 44.5, overOdds: 1.75, underOdds: 1.9 }],
  }).payload;
  assert.notEqual(payloadLib.payloadSignature(construir('111111111')),
                  payloadLib.payloadSignature(construir('222222222')));
});
