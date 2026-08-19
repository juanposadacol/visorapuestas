const test = require('node:test');
const assert = require('node:assert');
const { pickInnermost, wouldInvadeAnotherMarket, preferReading } = require('../src/lib/scan.js');

// Arbol de juguete: cada nodo conoce a sus hijos, y `contains` los recorre.
function nodo(nombre, hijos = []) { return { nombre, hijos }; }
function contains(a, b) {
  if (a === b) return false;
  const pila = [...a.hijos];
  while (pila.length) {
    const actual = pila.pop();
    if (actual === b) return true;
    pila.push(...actual.hijos);
  }
  return false;
}

test('se queda con la cabecera mas interna', () => {
  const titulo = nodo('h3');
  const tarjeta = nodo('div.card', [titulo]);
  const candidatos = [{ element: tarjeta }, { element: titulo }];
  const elegidos = pickInnermost(candidatos, contains);
  assert.equal(elegidos.length, 1);
  assert.equal(elegidos[0].element, titulo);
});

test('conserva cabeceras hermanas de mercados distintos', () => {
  const a = nodo('h3-partido');
  const b = nodo('h3-q3');
  const elegidos = pickInnermost([{ element: a }, { element: b }], contains);
  assert.equal(elegidos.length, 2);
});

test('un solo candidato se conserva', () => {
  const a = nodo('h3');
  assert.equal(pickInnermost([{ element: a }], contains).length, 1);
  assert.equal(pickInnermost([], contains).length, 0);
});

test('detecta cuando subir invadiria otro mercado', () => {
  const tituloA = nodo('h3-partido');
  const tituloB = nodo('h3-q3');
  const seccionA = nodo('section-a', [tituloA]);
  const seccionB = nodo('section-b', [tituloB]);
  const contenedorComun = nodo('main', [seccionA, seccionB]);
  const cabeceras = [{ element: tituloA }, { element: tituloB }];
  const cabeceraA = cabeceras[0];

  // subir hasta la seccion propia es seguro
  assert.equal(wouldInvadeAnotherMarket(seccionA, cabeceraA, cabeceras, contains), false);
  // subir hasta el contenedor comun ya abarca el mercado vecino
  assert.equal(wouldInvadeAnotherMarket(contenedorComun, cabeceraA, cabeceras, contains), true);
});

test('entre dos lecturas del mismo mercado gana la que trae mas lineas', () => {
  const pobre = { lines: [1], isVisible: true };
  const rica = { lines: [1, 2, 3], isVisible: false };
  assert.equal(preferReading(pobre, rica), rica);
  assert.equal(preferReading(rica, pobre), rica);
});

test('con el mismo numero de lineas gana la visible', () => {
  const oculta = { lines: [1, 2], isVisible: false };
  const visible = { lines: [1, 2], isVisible: true };
  assert.equal(preferReading(oculta, visible), visible);
  assert.equal(preferReading(visible, oculta), visible);
});

test('sin lectura previa se acepta la primera', () => {
  const lectura = { lines: [], isVisible: false };
  assert.equal(preferReading(null, lectura), lectura);
});
