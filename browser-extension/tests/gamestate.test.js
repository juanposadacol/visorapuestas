/**
 * Descubrimiento del marcador, el cuarto y el reloj en el DOM.
 *
 * Lo importante no es acertar siempre, sino NO acertar por casualidad: ante la
 * duda, no se devuelve nada y la aplicacion usara el OCR.
 */
const test = require('node:test');
const assert = require('node:assert');
const { extractGameState, findClockCandidates, findScoreCandidates,
        findPeriodCandidates, clockValidator, scoreValidator,
        periodValidator, pickBest } = require('../src/lib/gamestate.js');

function nodo(texto, hijos) { return { texto: texto || '', hijos: hijos || [] }; }
const A = {
  children: (n) => n.hijos,
  text: (n) => [n.texto, ...n.hijos.map((h) => A.text(h))].filter(Boolean).join(' '),
  ownText: (n) => n.texto,
};

/** Cabecera tipica de un partido en vivo. */
function cabecera() {
  return nodo('', [
    nodo('', [nodo('Equipo A'), nodo('58')]),
    nodo('', [nodo('Equipo B'), nodo('52')]),
    nodo('', [nodo('Q3'), nodo('06:24')]),
  ]);
}

test('encuentra el reloj, el cuarto y el marcador de una cabecera tipica', () => {
  const r = extractGameState(cabecera(), A);
  assert.deepEqual(r.gameState, { clock: '06:24', period: 3, scoreA: 58, scoreB: 52 });
});

test('un numero suelto no se toma por marcador', () => {
  const solo = nodo('', [nodo('Rebotes'), nodo('42')]);
  const r = extractGameState(solo, A);
  assert.equal(r.gameState, null);
});

test('el reloj exige forma MM:SS y minutos verosimiles', () => {
  assert.equal(findClockCandidates(nodo('', [nodo('06:24')]), A).length, 1);
  assert.equal(findClockCandidates(nodo('', [nodo('6:99')]), A).length, 0);
  assert.equal(findClockCandidates(nodo('', [nodo('45:00')]), A).length, 0);
  assert.equal(findClockCandidates(nodo('', [nodo('abc')]), A).length, 0);
});

test('el cuarto se reconoce en varias formas', () => {
  for (const etiqueta of ['Q3', '3Q', 'Cuarto 3', '3er cuarto']) {
    const encontrados = findPeriodCandidates(nodo('', [nodo(etiqueta)]), A);
    assert.equal(encontrados.length, 1, etiqueta);
    assert.equal(encontrados[0].value, 3, etiqueta);
  }
});

test('el marcador exige una pareja de numeros cercanos', () => {
  const juntos = nodo('', [nodo('', [nodo('58'), nodo('52')])]);
  assert.ok(findScoreCandidates(juntos, A).length >= 1);
  const lejos = nodo('', [
    nodo('', [nodo('', [nodo('', [nodo('', [nodo('58')])])])]),
    nodo('', [nodo('', [nodo('', [nodo('', [nodo('52')])])])]),
  ]);
  assert.equal(findScoreCandidates(lejos, A).length, 0);
});

// ------------------------------------------------------------- validaciones
test('el marcador no baja', () => {
  const anterior = { scoreA: 58, scoreB: 52 };
  assert.ok(scoreValidator({ value: { scoreA: 60, scoreB: 52 } }, anterior));
  assert.ok(!scoreValidator({ value: { scoreA: 12, scoreB: 52 } }, anterior));
});

test('el reloj baja, o sube solo al empezar un cuarto', () => {
  const anterior = { seconds: 384 };
  assert.ok(clockValidator({ seconds: 380 }, anterior));
  assert.ok(clockValidator({ seconds: 384 }, anterior));      // parado
  assert.ok(!clockValidator({ seconds: 500 }, anterior));     // salto raro
  assert.ok(clockValidator({ seconds: 600 }, anterior));      // cuarto nuevo
});

test('el cuarto no retrocede ni se sale de rango', () => {
  assert.ok(periodValidator({ value: 4 }, 3));
  assert.ok(!periodValidator({ value: 2 }, 3));
  assert.ok(!periodValidator({ value: 7 }, null));
});

// ---------------------------------------------------------------- ambiguedad
test('ante dos candidatos igual de plausibles no se elige ninguno', () => {
  const r = pickBest([
    { value: 3, confidence: 0.8, raw: 'Q3' },
    { value: 4, confidence: 0.8, raw: 'Q4' },
  ], null, () => true);
  assert.equal(r.value, null);
  assert.equal(r.reason, 'candidatos ambiguos');
  assert.deepEqual(r.ambiguous, ['Q3', 'Q4']);
});

test('dos candidatos que dicen lo MISMO no son ambiguos', () => {
  const r = pickBest([
    { value: 3, confidence: 0.8, raw: 'Q3' },
    { value: 3, confidence: 0.8, raw: 'Cuarto 3' },
  ], null, () => true);
  assert.equal(r.value, 3);
});

test('dos relojes distintos en la pagina no producen reloj', () => {
  const dosRelojes = nodo('', [
    nodo('', [nodo('06:24')]),
    nodo('', [nodo('03:11')]),
  ]);
  const r = extractGameState(dosRelojes, A);
  assert.equal(r.gameState, null);
  assert.equal(r.diagnostics.clock.reason, 'candidatos ambiguos');
});

// ------------------------------------------------------------------ memoria
test('la memoria del ciclo anterior impide aceptar un retroceso', () => {
  const primero = extractGameState(cabecera(), A);
  assert.equal(primero.gameState.scoreA, 58);

  // Un fotograma degradado muestra un marcador imposible.
  const degradado = nodo('', [
    nodo('', [nodo('Equipo A'), nodo('5')]),
    nodo('', [nodo('Equipo B'), nodo('52')]),
    nodo('', [nodo('Q3'), nodo('06:20')]),
  ]);
  const segundo = extractGameState(degradado, A, primero.memory);
  assert.equal(segundo.gameState.scoreA, undefined);   // no se acepta el retroceso
  assert.equal(segundo.gameState.clock, '06:20');      // el reloj si avanza bien
});

test('sin nada reconocible no se inventa un estado', () => {
  const r = extractGameState(nodo('', [nodo('Mis apuestas'), nodo('Retirar')]), A);
  assert.equal(r.gameState, null);
  assert.equal(r.diagnostics.score.reason, 'sin candidatos');
});

test('un estado parcial se envia solo con lo que se sabe', () => {
  const soloReloj = nodo('', [nodo('06:24')]);
  const r = extractGameState(soloReloj, A);
  assert.deepEqual(r.gameState, { clock: '06:24' });
});
