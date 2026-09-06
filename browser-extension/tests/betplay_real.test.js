/**
 * Casos tomados de la prueba REAL sobre BetPlay en vivo.
 *
 * Los textos y los numeros de este fichero no son inventados: salen del
 * diagnostico ejecutado sobre un partido, incluidos los fallos que hubo.
 */
const test = require('node:test');
const assert = require('node:assert');
const { identifyMarket, KEYS, CONFIDENCE_THRESHOLD } = require('../src/lib/markets.js');
const { parseLinesStrict, parseLines } = require('../src/lib/lines.js');
const { dedupeLines } = require('../src/lib/dedupe.js');
const { chooseVisibleMarket } = require('../src/lib/scan.js');
const { buildPayload, validatePayload } = require('../src/lib/payload.js');

// ------------------------------------------------- titulos reales de BetPlay
const TITULOS_Q3 = [
  'Total de puntos - Cuarto 3',
  'Total de puntos - 3er cuarto',
  '3° Cuarto - Total de puntos',
  '3º Cuarto - Total de puntos',
  'Q3 Total de puntos',
  'TOTAL DE PUNTOS - CUARTO 3',
  'Total de Puntos  -  Cuarto  3',
];

test('los titulos reales del Q3 se reconocen con confianza suficiente', () => {
  for (const titulo of TITULOS_Q3) {
    const r = identifyMarket(titulo);
    assert.equal(r.key, KEYS.Q3, `fallo con ${JSON.stringify(titulo)}`);
    assert.ok(r.confidence >= CONFIDENCE_THRESHOLD,
              `confianza baja en ${JSON.stringify(titulo)}: ${r.confidence}`);
  }
});

test('el mismo patron vale para los otros cuartos y para partido y mitades', () => {
  assert.equal(identifyMarket('Total de puntos - Cuarto 1').key, KEYS.Q1);
  assert.equal(identifyMarket('Total de puntos - Cuarto 2').key, KEYS.Q2);
  assert.equal(identifyMarket('Total de puntos - Cuarto 4').key, KEYS.Q4);
  assert.equal(identifyMarket('Total de puntos - Partido').key, KEYS.GAME);
  assert.equal(identifyMarket('Total de puntos - 1ª mitad').key, KEYS.H1);
  assert.equal(identifyMarket('Total de puntos - 2ª mitad').key, KEYS.H2);
});

test('la pestana suelta NO alcanza la confianza del titulo del mercado', () => {
  // Este era el fallo real: "Cuarto 3" ganaba y el panel decia DESCONOCIDO.
  const pestana = identifyMarket('Cuarto 3');
  const titulo = identifyMarket('Total de puntos - Cuarto 3');
  assert.equal(pestana.key, KEYS.UNKNOWN);
  assert.equal(pestana.candidate, KEYS.Q3);
  assert.ok(titulo.confidence > pestana.confidence);
});

test('entre la pestana y el titulo, el mercado visible es el titulo', () => {
  const registros = [
    { key: KEYS.UNKNOWN, candidate: KEYS.Q3, confidence: 0.55, isVisible: true,
      existsInDom: true, lines: [{ line: 43.5 }] },
    { key: KEYS.Q3, confidence: 0.95, isVisible: true,
      existsInDom: true, lines: [{ line: 43.5 }, { line: 44.5 }] },
  ];
  const elegido = chooseVisibleMarket(registros, CONFIDENCE_THRESHOLD);
  assert.equal(elegido.key, KEYS.Q3);
  assert.equal(elegido.confidence, 0.95);
});

test('sin ningun candidato fiable no se elige mercado visible', () => {
  const registros = [
    { key: KEYS.UNKNOWN, confidence: 0.55, isVisible: true, existsInDom: true,
      lines: [{ line: 43.5 }] },
  ];
  assert.equal(chooseVisibleMarket(registros, CONFIDENCE_THRESHOLD), null);
});

// ------------------------------------- numeros que contaminaban las lineas
test('los numeros sueltos del marcador ya no se convierten en lineas', () => {
  // 24, 32 y 109 salian del marcador y de las estadisticas de la pagina.
  const r = parseLinesStrict('24\n32\n109\n58\n52');
  assert.equal(r.lines.length, 0);
  assert.equal(r.rejected.length, 5);
  assert.ok(r.rejected.every((x) => x.reason.includes('entero')));
});

test('el modo diagnostico si los sigue mostrando como candidatos', () => {
  // En diagnostico interesa ver lo que hay; lo estricto es solo para enviar.
  assert.ok(parseLines('24\n32\n109').lines.length > 0);
});

test('una linea sin ninguna cuota no se envia', () => {
  const r = parseLinesStrict('Más de 43.5');
  assert.equal(r.lines.length, 0);
  assert.ok(r.rejected.some((x) => x.reason.includes('sin ninguna cuota')));
});

test('las lineas reales del mercado si pasan el filtro estricto', () => {
  const texto = ['Más de 43.5', '1.80', 'Menos de 43.5', '1.90',
                 'Más de 44.5', '1.95', 'Menos de 44.5', '1.72'].join('\n');
  const r = parseLinesStrict(texto);
  const fundidas = dedupeLines(r.lines).lines;
  assert.equal(fundidas.length, 2);
  assert.deepEqual(fundidas.map((l) => [l.line, l.overOdds, l.underOdds]),
                   [[43.5, 1.80, 1.90], [44.5, 1.95, 1.72]]);
  assert.equal(r.sideMarkers.both, true);
});

test('los movimientos de cuota observados en vivo se leen bien', () => {
  // Observado realmente: 184.5 pasando de 1.81 a 2.07 y 188.5 de 2.23 a 2.48.
  for (const [linea, over] of [[184.5, 1.81], [184.5, 2.07], [188.5, 2.23], [188.5, 2.48]]) {
    const r = parseLinesStrict(`Más de ${linea}\n${over.toFixed(2)}`);
    assert.equal(r.lines.length, 1);
    assert.equal(r.lines[0].line, linea);
    assert.equal(r.lines[0].overOdds, over);
  }
});

test('un total con decimal distinto de .5 se rechaza por defecto', () => {
  assert.equal(parseLinesStrict('Más de 43.4\n1.80').lines.length, 0);
});

test('los enteros se aceptan solo si se pide explicitamente', () => {
  assert.equal(parseLinesStrict('Más de 43\n1.80').lines.length, 0);
  assert.equal(parseLinesStrict('Más de 43\n1.80', { allowWholeLines: true }).lines.length, 1);
});

// --------------------------------------------------- payload de extremo a extremo
test('del titulo real al payload validado', () => {
  const texto = ['Más de 43.5', '1.80', 'Menos de 43.5', '1.90'].join('\n');
  const estricta = parseLinesStrict(texto);
  const identificado = identifyMarket('Total de puntos - Cuarto 3');
  const { payload, rejected } = buildPayload({
    marketKey: identificado.key,
    confidence: identificado.confidence,
    rawTitle: 'Total de puntos - Cuarto 3',
    eventId: '9876543',
    eventName: 'Equipo A vs Equipo B',
    lines: dedupeLines(estricta.lines).lines,
    sideMarkers: estricta.sideMarkers,
  });

  assert.deepEqual(rejected, []);
  assert.equal(payload.visibleMarket.marketType, 'QUARTER_TOTAL');
  assert.equal(payload.visibleMarket.period, 3);
  assert.equal(payload.visibleMarket.half, null);
  assert.equal(payload.visibleMarket.sidesConfirmed, true);
  assert.deepEqual(payload.lines, [{ line: 43.5, overOdds: 1.80, underOdds: 1.90 }]);
  assert.equal(validatePayload(payload).valid, true);
});

test('el mercado dudoso no llega a construir payload', () => {
  const identificado = identifyMarket('Cuarto 3');
  const { payload, rejected } = buildPayload({
    marketKey: identificado.key,
    confidence: identificado.confidence,
    lines: [{ line: 43.5, overOdds: 1.80, underOdds: 1.90 }],
  });
  assert.equal(payload, null);
  assert.ok(rejected.length);
});

test('sin marcadores de lado se avisa en el propio payload', () => {
  const { payload } = buildPayload({
    marketKey: 'Q3_TOTAL', confidence: 0.95,
    lines: [{ line: 43.5, overOdds: 1.80, underOdds: 1.90 }],
    sideMarkers: { over: false, under: false, both: false },
  });
  assert.equal(payload.visibleMarket.sidesConfirmed, false);
  assert.equal(validatePayload(payload).valid, true);   // se envia, pero avisado
});
