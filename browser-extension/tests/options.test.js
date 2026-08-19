/**
 * Emparejamiento OVER/UNDER por estructura.
 *
 * Caso de aceptacion acordado: un mercado 'Total de puntos - Cuarto 4' que
 * muestra 'Mas de 44.5 @ 1.75' y 'Menos de 44.5 @ 1.90' debe devolver
 * exactamente { line: 44.5, overOdds: 1.75, underOdds: 1.90 }.
 *
 * Como no se conoce el HTML exacto de BetPlay, se cubren las cuatro
 * maquetaciones plausibles: si la casa usa cualquiera de ellas, el resultado
 * es el mismo.
 */
const test = require('node:test');
const assert = require('node:assert');
const { extractMarketLines, sideFromText } = require('../src/lib/options.js');

// ---------------------------------------------------------------- arbol falso
function nodo(texto, hijos) {
  return { texto: texto || '', hijos: hijos || [] };
}
const ADAPTADOR = {
  children: (n) => n.hijos,
  text: (n) => [n.texto, ...n.hijos.map((h) => ADAPTADOR.text(h))].filter(Boolean).join(' '),
  ownText: (n) => n.texto,
};

const ESPERADO = { line: 44.5, overOdds: 1.75, underOdds: 1.90 };

function soloLineas(resultado) {
  return resultado.lines.map((l) => ({ line: l.line, overOdds: l.overOdds, underOdds: l.underOdds }));
}

// ------------------------------------------------------- las cuatro maquetaciones
test('maquetacion A: cada opcion lleva su linea dentro', () => {
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [
      nodo('', [nodo('Más de 44.5'), nodo('1.75')]),
      nodo('', [nodo('Menos de 44.5'), nodo('1.90')]),
    ]),
  ]);
  assert.deepEqual(soloLineas(extractMarketLines(mercado, ADAPTADOR)), [ESPERADO]);
});

test('maquetacion B: la linea se muestra una vez y la comparten las dos opciones', () => {
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [
      nodo('44.5'),
      nodo('', [nodo('Más de'), nodo('1.75')]),
      nodo('', [nodo('Menos de'), nodo('1.90')]),
    ]),
  ]);
  assert.deepEqual(soloLineas(extractMarketLines(mercado, ADAPTADOR)), [ESPERADO]);
});

test('maquetacion C: fila de tabla con cabeceras Mas de / Menos de', () => {
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [nodo('Línea'), nodo('Más de'), nodo('Menos de')]),
    nodo('', [
      nodo('44.5'),
      nodo('', [nodo('Más de'), nodo('1.75')]),
      nodo('', [nodo('Menos de'), nodo('1.90')]),
    ]),
  ]);
  assert.deepEqual(soloLineas(extractMarketLines(mercado, ADAPTADOR)), [ESPERADO]);
});

test('maquetacion D: sin palabras, dos opciones hermanas por posicion', () => {
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [
      nodo('44.5'),
      nodo('', [nodo('1.75')]),
      nodo('', [nodo('1.90')]),
    ]),
  ]);
  const r = extractMarketLines(mercado, ADAPTADOR);
  assert.deepEqual(soloLineas(r), [ESPERADO]);
  // Se avisa de que el lado salio de la posicion, no de una palabra.
  assert.equal(r.sideMarkers.both, false);
  assert.equal(r.sideMarkers.byPosition, true);
});

test('el texto plano en nodos sueltos tambien empareja', () => {
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('Más de 44.5'), nodo('1.75'),
    nodo('Menos de 44.5'), nodo('1.90'),
  ]);
  assert.deepEqual(soloLineas(extractMarketLines(mercado, ADAPTADOR)), [ESPERADO]);
});

// --------------------------------------------------------- varias lineas a la vez
test('varias lineas del mismo mercado no se mezclan entre si', () => {
  const opcion = (lado, linea, cuota) => nodo('', [nodo(`${lado} ${linea}`), nodo(cuota)]);
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [opcion('Más de', '43.5', '1.80'), opcion('Menos de', '43.5', '1.95')]),
    nodo('', [opcion('Más de', '44.5', '1.75'), opcion('Menos de', '44.5', '1.90')]),
    nodo('', [opcion('Más de', '45.5', '1.68'), opcion('Menos de', '45.5', '2.05')]),
  ]);
  assert.deepEqual(soloLineas(extractMarketLines(mercado, ADAPTADOR)), [
    { line: 43.5, overOdds: 1.80, underOdds: 1.95 },
    ESPERADO,
    { line: 45.5, overOdds: 1.68, underOdds: 2.05 },
  ]);
});

// ------------------------------------------------------------- sin contaminacion
test('el marcador y las estadisticas vecinas no entran', () => {
  const mercado = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [nodo('Más de 44.5'), nodo('1.75')]),
    nodo('', [nodo('Menos de 44.5'), nodo('1.90')]),
  ]);
  const pagina = nodo('', [
    nodo('', [nodo('58'), nodo('52')]),              // marcador
    nodo('', [nodo('109'), nodo('24'), nodo('32')]), // estadisticas
    mercado,
  ]);
  // Se extrae del CONTENEDOR del mercado, no de la pagina entera.
  assert.deepEqual(soloLineas(extractMarketLines(mercado, ADAPTADOR)), [ESPERADO]);
  // Y aunque se pasara la pagina entera, los enteros no se toman como lineas.
  const desdeLaPagina = extractMarketLines(pagina, ADAPTADOR);
  assert.deepEqual(soloLineas(desdeLaPagina), [ESPERADO]);
});

test('una cuota sin linea a la que pertenecer se descarta con su motivo', () => {
  const suelto = nodo('', [nodo('Ganador'), nodo('', [nodo('Equipo A'), nodo('1.45')])]);
  const r = extractMarketLines(suelto, ADAPTADOR);
  assert.deepEqual(r.lines, []);
  assert.ok(r.rejected.some((x) => x.reason.includes('sin linea')));
});

test('un handicap con su propia linea no contamina si se aisla su contenedor', () => {
  const totales = nodo('', [
    nodo('Total de puntos - Cuarto 4'),
    nodo('', [nodo('Más de 44.5'), nodo('1.75')]),
    nodo('', [nodo('Menos de 44.5'), nodo('1.90')]),
  ]);
  const handicap = nodo('', [
    nodo('Hándicap - Cuarto 4'),
    nodo('', [nodo('Equipo A -5.5'), nodo('1.85')]),
    nodo('', [nodo('Equipo B +5.5'), nodo('1.95')]),
  ]);
  assert.deepEqual(soloLineas(extractMarketLines(totales, ADAPTADOR)), [ESPERADO]);
  // El handicap no aporta lineas de total: sus numeros no llevan lado
  // Mas de / Menos de, asi que no se emparejan como OVER/UNDER.
  const r = extractMarketLines(handicap, ADAPTADOR);
  assert.ok(r.lines.every((l) => l.overOdds === null || l.underOdds === null) || r.lines.length === 0);
});

// ------------------------------------------------------------------ palabras
test('distingue el lado por la palabra, con "menos" antes que "mas"', () => {
  assert.equal(sideFromText('Menos de 44.5'), 'under');
  assert.equal(sideFromText('Más de 44.5'), 'over');
  assert.equal(sideFromText('UNDER'), 'under');
  assert.equal(sideFromText('Over'), 'over');
  assert.equal(sideFromText('Equipo A'), '');
});

test('contenedor vacio no produce nada', () => {
  assert.deepEqual(extractMarketLines(null, ADAPTADOR).lines, []);
  assert.deepEqual(extractMarketLines(nodo(''), ADAPTADOR).lines, []);
});
