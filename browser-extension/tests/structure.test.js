/**
 * Copia saneada de la estructura del DOM.
 *
 * Dos cosas que probar, y la segunda importa mas que la primera:
 *
 *   1. que la estructura que sale sea util para ajustar el parser;
 *   2. que NO salga nada de la cuenta. Este informe esta pensado para
 *      copiarse y pegarse en una conversacion, asi que lo que se cuela aqui
 *      se cuela de verdad.
 */
const test = require('node:test');
const assert = require('node:assert');
const dom = require('../src/lib/dom.js');
const structure = require('../src/lib/structure.js');
const gs = require('../src/lib/gamestate.js');
const { createDocument, el } = require('./fake_dom.js');

const A = dom.createAdapter();

function mercado(doc) {
  return el(doc, 'section', { class: 'market', 'data-market-id': 'total-q4' }, [
    el(doc, 'h3', { class: 'market__title' }, ['Total de puntos - Cuarto 4']),
    el(doc, 'div', { class: 'market__options', role: 'group' }, [
      el(doc, 'div', { class: 'option' }, [
        el(doc, 'span', { class: 'option__label' }, ['Más de 44.5']),
        el(doc, 'span', { class: 'option__odds' }, ['1.75']),
      ]),
      el(doc, 'div', { class: 'option' }, [
        el(doc, 'span', { class: 'option__label' }, ['Menos de 44.5']),
        el(doc, 'span', { class: 'option__odds' }, ['1.90']),
      ]),
    ]),
  ]);
}

test('la estructura conserva jerarquia, clases y textos del mercado', () => {
  const doc = createDocument();
  const nodo = mercado(doc);
  doc.body.appendChild(nodo);
  const salida = structure.serializeSubtree(nodo, A);

  assert.match(salida, /section\.market/);
  assert.match(salida, /h3\.market__title/);
  assert.match(salida, /"Total de puntos - Cuarto 4"/);
  assert.match(salida, /"Más de 44\.5"/);
  assert.match(salida, /"1\.90"/);
  assert.match(salida, /role="group"/);
  assert.match(salida, /data-market-id="total-q4"/);

  // La indentacion es lo que deja ver si etiqueta y cuota son nodos distintos,
  // que es justo la duda que hizo que el UNDER se perdiera.
  assert.match(salida, /\n {2}div\.market__options/);
});

test('NO se copia el correo, el saldo ni los tokens', () => {
  const doc = createDocument();
  const nodo = el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', {}, ['Total de puntos - Cuarto 4']),
    el(doc, 'span', { 'data-user-email': 'juan@example.com' }, ['juan@example.com']),
    el(doc, 'span', {}, ['saldo: 120.000']),
    el(doc, 'span', { 'data-session-token': 'abcdef1234567890abcdef' }, ['ok']),
    el(doc, 'span', { 'data-id': 'aG9sYU11bmRvMTIzNDU2Nzg5MA' }, ['ok']),
  ]);
  doc.body.appendChild(nodo);
  const salida = structure.serializeSubtree(nodo, A);

  assert.ok(!salida.includes('juan@example.com'), 'el correo no puede salir');
  assert.ok(!salida.includes('120.000'), 'el saldo no puede salir');
  assert.ok(!salida.includes('abcdef1234567890abcdef'), 'el token no puede salir');
  assert.ok(!salida.includes('data-user-email'), 'ni el nombre del atributo');
  assert.match(salida, /\[valor opaco\]/, 'un identificador largo se sustituye');
  assert.match(salida, /correo oculto/, 'el texto se enmascara, no se borra en silencio');
});

test('los bloques privados se omiten enteros', () => {
  const doc = createDocument();
  const nodo = el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', {}, ['Total de puntos - Cuarto 4']),
    el(doc, 'div', { class: 'betslip' }, [
      el(doc, 'span', {}, ['Mi apuesta']),
      el(doc, 'span', {}, ['50.000']),
    ]),
  ]);
  doc.body.appendChild(nodo);
  const salida = structure.serializeSubtree(nodo, A);
  assert.match(salida, /\[bloque privado omitido\]/);
  assert.ok(!salida.includes('Mi apuesta'));
});

test('el volcado tiene tope: ni un arbol enorme lo desborda', () => {
  const doc = createDocument();
  const raiz = el(doc, 'div', { class: 'grande' }, []);
  for (let i = 0; i < 500; i += 1) raiz.appendChild(el(doc, 'span', {}, [`n${i}`]));
  doc.body.appendChild(raiz);
  const salida = structure.serializeSubtree(raiz, A, { maxNodes: 50 });
  assert.match(salida, /\[recortado: mas de 50 nodos\]/);
});

test('la profundidad tambien tiene tope', () => {
  const doc = createDocument();
  let actual = el(doc, 'div', { class: 'hondo' }, []);
  const raiz = actual;
  for (let i = 0; i < 40; i += 1) {
    const hijo = el(doc, 'div', {}, []);
    actual.appendChild(hijo);
    actual = hijo;
  }
  doc.body.appendChild(raiz);
  const salida = structure.serializeSubtree(raiz, A, { maxDepth: 5 });
  assert.match(salida, /\[recortado/);
});

test('un nodo nulo no revienta', () => {
  assert.equal(structure.serializeSubtree(null, A), '(nada que copiar)');
});

test('el informe lleva cabecera, datos y el aviso de saneado', () => {
  const doc = createDocument();
  const nodo = mercado(doc);
  doc.body.appendChild(nodo);
  const informe = structure.buildStructureReport('MERCADO', nodo, A, {
    clave: 'Q4_TOTAL', confianza: 0.95, seccion: 'Cuarto 4',
  });
  assert.match(informe, /^MERCADO/);
  assert.match(informe, /clave: Q4_TOTAL/);
  assert.match(informe, /seccion: Cuarto 4/);
  assert.match(informe, /estructura saneada/);
});

test('el scoreboard se localiza aunque no se sepa leer el marcador', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', { class: 'event-header scoreboard' }, [
    el(doc, 'div', { class: 'scoreboard__team' }, [
      el(doc, 'span', { class: 'team__name' }, ['Las Vegas Aces']),
      el(doc, 'span', { class: 'team__score' }, ['?']),
    ]),
  ]));
  const [contenedor] = gs.findScoreboardContainers(doc.body, A);
  assert.ok(contenedor, 'se encuentra el bloque que se declara marcador');

  const informe = structure.buildStructureReport('SCOREBOARD', contenedor, A,
                                                 { marcador: 'no leido' });
  assert.match(informe, /scoreboard__team/);
  assert.match(informe, /"Las Vegas Aces"/);
  assert.match(informe, /marcador: no leido/);
});
