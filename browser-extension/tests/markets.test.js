const test = require('node:test');
const assert = require('node:assert');
const { identifyMarket, KEYS, sortKey } = require('../src/lib/markets.js');

test('reconoce los cuartos en las variantes habituales', () => {
  for (const etiqueta of ['3.er Cuarto - Total de puntos', 'Q3 Total de puntos',
                          'Total de puntos - 3er cuarto', 'Cuarto 3 - Total de puntos']) {
    const r = identifyMarket(etiqueta);
    assert.equal(r.key, KEYS.Q3, `fallo con ${etiqueta}`);
    assert.ok(r.confidence >= 0.7);
  }
});

test('reconoce las mitades', () => {
  assert.equal(identifyMarket('1ª mitad - Total de puntos').key, KEYS.H1);
  assert.equal(identifyMarket('Total de puntos - 2ª mitad').key, KEYS.H2);
  assert.equal(identifyMarket('Segunda mitad - Total de puntos').key, KEYS.H2);
  assert.equal(identifyMarket('1er tiempo - Total de puntos').key, KEYS.H1);
});

test('reconoce el mercado de partido cuando es explicito', () => {
  const r = identifyMarket('Partido - Total de puntos');
  assert.equal(r.key, KEYS.GAME);
  assert.ok(r.confidence >= 0.7);
});

test('"Total de puntos" a secas NO se clasifica en silencio', () => {
  const r = identifyMarket('Total de puntos');
  assert.equal(r.key, KEYS.UNKNOWN);
  assert.equal(r.candidate, KEYS.GAME);      // queda la sospecha registrada
  assert.ok(r.confidence < 0.7);
});

test('un periodo sin "total" no basta: podria ser otro mercado', () => {
  const r = identifyMarket('3er cuarto - Handicap');
  assert.equal(r.key, KEYS.UNKNOWN);
  assert.equal(r.candidate, KEYS.Q3);
  assert.ok(r.reasons.some((x) => x.includes('cuarto 3 indicado')));
});

test('"Descanso" queda como ambiguo', () => {
  const r = identifyMarket('Descanso');
  assert.equal(r.key, KEYS.UNKNOWN);
  assert.equal(r.candidate, KEYS.H1);
  assert.ok(r.reasons.some((x) => x.includes('ambiguo')));
});

test('texto irrelevante no produce candidato', () => {
  const r = identifyMarket('Mis apuestas');
  assert.equal(r.key, KEYS.UNKNOWN);
  assert.equal(r.candidate, null);
  assert.equal(identifyMarket('').key, KEYS.UNKNOWN);
});

test('no confunde una mitad con un cuarto', () => {
  assert.equal(identifyMarket('1ª mitad - Total de puntos').key, KEYS.H1);
  assert.equal(identifyMarket('1er cuarto - Total de puntos').key, KEYS.Q1);
});

test('orden de presentacion estable', () => {
  const claves = [KEYS.Q3, KEYS.GAME, KEYS.H2, KEYS.Q1, KEYS.H1];
  claves.sort((a, b) => sortKey(a) - sortKey(b));
  assert.deepEqual(claves, [KEYS.GAME, KEYS.H1, KEYS.H2, KEYS.Q1, KEYS.Q3]);
});
