const test = require('node:test');
const assert = require('node:assert');
const text = require('../src/lib/text.js');

test('quita tildes y unifica mayusculas y espacios', () => {
  assert.equal(text.normalize('  1.ª  MITAD  '), '1.a mitad');
  assert.equal(text.normalize('Más de'), 'mas de');
  assert.equal(text.normalize(null), '');
});

test('normaliza los ordinales que usan las casas', () => {
  assert.equal(text.normalizeOrdinals('3.er Cuarto'), '3 cuarto');
  assert.equal(text.normalizeOrdinals('1.ª mitad'), '1 mitad');
  assert.equal(text.normalizeOrdinals('2º periodo'), '2 periodo');
  assert.equal(text.normalizeOrdinals('1er cuarto'), '1 cuarto');
  assert.equal(text.normalizeOrdinals('4to cuarto'), '4 cuarto');
});

test('reconoce ordinales escritos con palabra', () => {
  assert.equal(text.normalizeOrdinals('primer cuarto'), '1 cuarto');
  assert.equal(text.normalizeOrdinals('segunda mitad'), '2 mitad');
  assert.equal(text.normalizeOrdinals('tercer periodo'), '3 periodo');
});

test('distingue el ordinal "cuarto" del sustantivo "cuarto"', () => {
  assert.equal(text.normalizeOrdinals('cuarto cuarto'), '4 cuarto');
  // "cuarto" solo sigue siendo el sustantivo, no se convierte en 4
  assert.equal(text.normalizeOrdinals('total de puntos del cuarto'), 'total de puntos del cuarto');
});

test('convierte numeros con coma decimal', () => {
  assert.equal(text.toNumber('1,85'), 1.85);
  assert.equal(text.toNumber('140.5'), 140.5);
  assert.equal(text.toNumber('abc'), null);
  assert.equal(text.toNumber(''), null);
});

test('cuenta los decimales tal y como venian escritos', () => {
  assert.equal(text.decimalsOf('1.80'), 2);
  assert.equal(text.decimalsOf('40.5'), 1);
  assert.equal(text.decimalsOf('153'), 0);
});

test('recorta textos largos para el informe', () => {
  assert.equal(text.truncate('hola   mundo'), 'hola mundo');
  assert.equal(text.truncate('a'.repeat(200), 10).length, 10);
});
