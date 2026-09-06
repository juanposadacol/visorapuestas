const test = require('node:test');
const assert = require('node:assert');
const { classifyVisibility, describe } = require('../src/lib/visibility.js');

test('nodo presente y visible', () => {
  const r = classifyVisibility({ inViewport: true });
  assert.equal(r.existsInDom, true);
  assert.equal(r.isVisible, true);
  assert.equal(describe(r), 'VISIBLE');
});

test('existir y estar oculto son cosas distintas', () => {
  for (const causa of ['displayNone', 'visibilityHidden', 'hiddenAttr', 'ariaHidden',
                       'opacityZero', 'zeroArea']) {
    const r = classifyVisibility({ [causa]: true, inViewport: true });
    assert.equal(r.existsInDom, true, `${causa} no deberia borrar el nodo`);
    assert.equal(r.isVisible, false, `${causa} deberia ocultarlo`);
    assert.ok(r.reasons.length > 0);
  }
});

test('un nodo desprendido del documento no existe', () => {
  const r = classifyVisibility({ detached: true });
  assert.equal(r.existsInDom, false);
  assert.equal(describe(r), 'NO EXISTE EN DOM');
});

test('fuera del viewport NO es estar oculto', () => {
  const r = classifyVisibility({ inViewport: false });
  assert.equal(r.isVisible, true);
  assert.equal(r.inViewport, false);
  assert.equal(describe(r), 'VISIBLE (fuera del viewport)');
});

test('se acumulan todas las causas de ocultacion', () => {
  const r = classifyVisibility({ displayNone: true, ariaHidden: true, inViewport: true });
  assert.equal(r.reasons.length, 2);
  assert.ok(describe(r).startsWith('OCULTO ('));
});

test('sin datos no se afirma nada raro', () => {
  const r = classifyVisibility(null);
  assert.equal(r.existsInDom, true);
  assert.equal(r.isVisible, true);
});
