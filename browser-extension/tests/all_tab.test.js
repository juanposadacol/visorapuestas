/**
 * Pestana TODO: varios mercados de totales a la vez, sin contaminarse.
 *
 * Condicion de aceptacion acordada: en la vista que lo muestra todo hay que
 * poder aislar GAME_TOTAL, HALF_TOTAL y Qx_TOTAL simultaneamente por sus
 * contenedores, sin que se cuelen totales por equipo, handicaps, el marcador
 * ni otros numeros de la pagina.
 */
const test = require('node:test');
const assert = require('node:assert');
const { scanMarkets, chooseVisibleMarket } = require('../src/lib/scan.js');
const { identifyMarket, KEYS, CONFIDENCE_THRESHOLD } = require('../src/lib/markets.js');
const { buildPayload, validatePayload } = require('../src/lib/payload.js');

function nodo(texto, hijos) {
  return { texto: texto || '', hijos: hijos || [] };
}
const ADAPTADOR = {
  children: (n) => n.hijos,
  text: (n) => [n.texto, ...n.hijos.map((h) => ADAPTADOR.text(h))].filter(Boolean).join(' '),
  ownText: (n) => n.texto,
};

/** Un mercado de totales con sus lineas, como los pinta la casa. */
function mercadoTotales(titulo, filas) {
  return nodo('', [
    nodo(titulo),
    nodo('', filas.map(([linea, over, under]) => nodo('', [
      nodo('', [nodo(`Más de ${linea}`), nodo(over)]),
      nodo('', [nodo(`Menos de ${linea}`), nodo(under)]),
    ]))),
  ]);
}

/** La pagina completa de la pestana TODO, con todo el ruido de alrededor. */
function pestanaTodo() {
  return nodo('', [
    // marcador y estadisticas
    nodo('', [nodo('Equipo A'), nodo('58'), nodo('Equipo B'), nodo('52')]),
    nodo('', [nodo('Rebotes'), nodo('24'), nodo('Asistencias'), nodo('32'),
              nodo('Puntos totales'), nodo('109')]),
    // otros mercados con numeros
    nodo('', [nodo('Ganador del partido'),
              nodo('', [nodo('Equipo A'), nodo('1.45')]),
              nodo('', [nodo('Equipo B'), nodo('2.60')])]),
    nodo('', [nodo('Hándicap - Cuarto 4'),
              nodo('', [nodo('Equipo A -5.5'), nodo('1.85')]),
              nodo('', [nodo('Equipo B +5.5'), nodo('1.95')])]),
    nodo('', [nodo('Total de puntos - Equipo A'),
              nodo('', [nodo('Más de 92.5'), nodo('1.88')]),
              nodo('', [nodo('Menos de 92.5'), nodo('1.92')])]),
    // los tres mercados de totales que si nos interesan
    mercadoTotales('Total de puntos - Partido',
                   [['176.5', '1.85', '1.95'], ['178.5', '1.90', '1.90']]),
    mercadoTotales('Total de puntos - 1ª mitad', [['88.5', '1.80', '2.00']]),
    mercadoTotales('Total de puntos - Cuarto 4', [['44.5', '1.75', '1.90']]),
  ]);
}

function porClave(registros) {
  return Object.fromEntries(registros.map((r) => [r.key, r]));
}

test('aisla los tres mercados de totales simultaneamente', () => {
  const registros = scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket });
  const utiles = registros.filter((r) => r.key !== KEYS.UNKNOWN);
  const claves = utiles.map((r) => r.key).sort();
  assert.deepEqual(claves, [KEYS.GAME, KEYS.H1, KEYS.Q4].sort());
});

test('cada mercado se queda solo con SUS lineas', () => {
  const mapa = porClave(scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket }));

  assert.deepEqual(
    mapa[KEYS.GAME].lines.map((l) => [l.line, l.overOdds, l.underOdds]),
    [[176.5, 1.85, 1.95], [178.5, 1.90, 1.90]]);

  assert.deepEqual(
    mapa[KEYS.H1].lines.map((l) => [l.line, l.overOdds, l.underOdds]),
    [[88.5, 1.80, 2.00]]);

  // El caso de aceptacion exacto.
  assert.deepEqual(
    mapa[KEYS.Q4].lines.map((l) => [l.line, l.overOdds, l.underOdds]),
    [[44.5, 1.75, 1.90]]);
});

test('el cuarto 4 devuelve exactamente lo acordado', () => {
  const mapa = porClave(scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket }));
  const linea = mapa[KEYS.Q4].lines[0];
  assert.equal(linea.line, 44.5);
  assert.equal(linea.overOdds, 1.75);
  assert.equal(linea.underOdds, 1.90);
});

test('ninguna linea de un mercado aparece en otro', () => {
  const mapa = porClave(scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket }));
  const valores = (clave) => new Set(mapa[clave].lines.map((l) => l.line));
  const juego = valores(KEYS.GAME);
  const mitad = valores(KEYS.H1);
  const cuarto = valores(KEYS.Q4);
  for (const [a, b] of [[juego, mitad], [juego, cuarto], [mitad, cuarto]]) {
    for (const valor of a) assert.ok(!b.has(valor), `${valor} aparece en dos mercados`);
  }
});

test('el total por equipo no se cuela como mercado de totales', () => {
  const registros = scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket });
  for (const registro of registros) {
    if (registro.key === KEYS.UNKNOWN) continue;
    assert.ok(!registro.lines.some((l) => l.line === 92.5),
              `la linea 92.5 del total por equipo se colo en ${registro.key}`);
  }
});

test('el handicap y el ganador no aportan lineas', () => {
  const registros = scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket });
  const utiles = registros.filter((r) => r.key !== KEYS.UNKNOWN);
  const todas = utiles.flatMap((r) => r.lines.map((l) => l.line));
  assert.ok(!todas.includes(5.5), 'la linea del handicap se colo');
  assert.ok(!todas.some((l) => [1.45, 2.60].includes(l)), 'una cuota del ganador se colo');
});

test('el marcador y las estadisticas no producen lineas', () => {
  const registros = scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket });
  const todas = registros.flatMap((r) => r.lines.map((l) => l.line));
  for (const ruido of [58, 52, 24, 32, 109]) {
    assert.ok(!todas.includes(ruido), `${ruido} acabo tomado por una linea`);
  }
});

test('de la pestana TODO sale un payload valido para cada mercado', () => {
  const registros = scanMarkets(pestanaTodo(), ADAPTADOR, { identify: identifyMarket });
  const utiles = registros.filter((r) => r.key !== KEYS.UNKNOWN);
  assert.equal(utiles.length, 3);
  for (const registro of utiles) {
    const { payload, rejected } = buildPayload({
      marketKey: registro.key,
      confidence: registro.confidence,
      rawTitle: registro.headerText,
      eventId: '9876543',
      lines: registro.lines,
      sideMarkers: registro.sideMarkers,
    });
    assert.deepEqual(rejected, [], registro.key);
    assert.equal(validatePayload(payload).valid, true, registro.key);
  }
});

test('con un solo mercado a la vista, ese es el visible', () => {
  const soloQ4 = nodo('', [
    nodo('', [nodo('58'), nodo('52')]),
    mercadoTotales('Total de puntos - Cuarto 4', [['44.5', '1.75', '1.90']]),
  ]);
  const registros = scanMarkets(soloQ4, ADAPTADOR, { identify: identifyMarket })
    .map((r) => ({ ...r, isVisible: true, existsInDom: true }));
  const elegido = chooseVisibleMarket(registros, CONFIDENCE_THRESHOLD);
  assert.equal(elegido.key, KEYS.Q4);
  assert.equal(elegido.lines[0].underOdds, 1.90);
});
