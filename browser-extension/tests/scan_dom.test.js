/**
 * Escaneo COMPLETO sobre un DOM (de juguete, pero recorrido con el mismo
 * adaptador que usa la extension en BetPlay).
 *
 * Las pruebas de `scan.test.js` trabajan sobre arboles abstractos; estas
 * cierran el hueco que dejo pasar el fallo real: el camino Document ->
 * adaptador -> TreeWalker -> mercados. Si `extractText` vuelve a romperse con
 * alguna clase de raiz, aqui se ve inmediatamente.
 */
const test = require('node:test');
const assert = require('node:assert');
const dom = require('../src/lib/dom.js');
const scanLib = require('../src/lib/scan.js');
const marketsLib = require('../src/lib/markets.js');
const { createDocument, el, iframe } = require('./fake_dom.js');

const adapter = dom.createAdapter();
const deps = { identify: marketsLib.identifyMarket };

/** Un bloque de mercado como los de BetPlay: titulo + opciones. */
function bloqueTotal(doc, titulo, linea, over, under) {
  return el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', {}, [titulo]),
    el(doc, 'div', { class: 'options' }, [
      el(doc, 'div', { class: 'option' }, [
        el(doc, 'span', {}, [`Más de ${linea}`]),
        el(doc, 'span', {}, [over]),
      ]),
      el(doc, 'div', { class: 'option' }, [
        el(doc, 'span', {}, [`Menos de ${linea}`]),
        el(doc, 'span', {}, [under]),
      ]),
    ]),
  ]);
}

test('el DOCUMENTO principal se escanea sin lanzar y entrega el mercado', () => {
  const doc = createDocument();
  doc.body.appendChild(bloqueTotal(doc, 'Total de puntos - Cuarto 4', '44.5', '1.75', '1.90'));

  const registros = scanLib.scanMarkets(doc, adapter, deps);
  assert.equal(registros.length, 1);
  assert.equal(registros[0].key, 'Q4_TOTAL');
  assert.deepEqual(registros[0].lines.map((l) => [l.line, l.overOdds, l.underOdds]),
                   [[44.5, 1.75, 1.9]]);
});

test('un SHADOW ROOT se escanea igual que el documento', () => {
  const doc = createDocument();
  const host = el(doc, 'bp-market-widget');
  doc.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'open' });
  shadow.appendChild(bloqueTotal(doc, 'Total de puntos - Cuarto 3', '43.5', '1.80', '2.00'));

  const registros = scanLib.scanMarkets(shadow, adapter, deps);
  assert.equal(registros.length, 1);
  assert.equal(registros[0].key, 'Q3_TOTAL');
  assert.equal(registros[0].lines[0].underOdds, 2.0);
});

test('un IFRAME del mismo origen se escanea con su propio documento', () => {
  const doc = createDocument();
  const { frame, doc: interno } = iframe(doc, 'https://betplay.com.co/live/widget');
  doc.body.appendChild(frame);
  interno.body.appendChild(
    bloqueTotal(interno, 'Total de puntos - Partido', '163.5', '1.66', '2.15'));

  const registros = scanLib.scanMarkets(interno, adapter, deps);
  assert.equal(registros.length, 1);
  assert.equal(registros[0].key, 'GAME_TOTAL');
  assert.equal(registros[0].lines[0].line, 163.5);
});

test('J. una raiz rota no impide escanear la raiz sana', () => {
  const doc = createDocument();
  doc.body.appendChild(bloqueTotal(doc, 'Total de puntos - Cuarto 4', '44.5', '1.75', '1.90'));

  const { frame, doc: muerto } = iframe(doc, 'https://betplay.com.co/roto');
  doc.body.appendChild(frame);
  muerto.destroy();                       // el iframe se desmonto

  // Este es el bucle real del content script, en pequeno.
  const raices = [
    { root: muerto, kind: 'iframe', label: 'roto' },
    { root: doc, kind: 'document', label: 'principal' },
  ];
  const encontrados = [];
  const omitidas = [];
  for (const { root, kind } of raices) {
    if (!dom.isUsableRoot(root)) { omitidas.push(kind); continue; }
    encontrados.push(...scanLib.scanMarkets(root, adapter, deps));
  }
  assert.deepEqual(omitidas, ['iframe']);
  assert.equal(encontrados.length, 1, 'la raiz sana entrego su mercado');
  assert.equal(encontrados[0].key, 'Q4_TOTAL');
});

test('I. si el arbol se reemplaza a mitad del escaneo, el mercado sigue saliendo', () => {
  const doc = createDocument();
  doc.body.appendChild(bloqueTotal(doc, 'Total de puntos - Cuarto 4', '44.5', '1.75', '1.90'));
  doc.breakWalkerAt = 2;                  // el walker revienta en cada lectura

  const registros = scanLib.scanMarkets(doc, adapter, deps);
  assert.equal(registros.length, 1);
  assert.equal(registros[0].key, 'Q4_TOTAL');
  assert.equal(registros[0].lines[0].underOdds, 1.9,
               'el recorrido de reserva leyo el arbol entero');
});

test('la pestana TODO con tres bloques abiertos entrega los tres mercados', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', { class: 'all' }, [
    el(doc, 'section', { class: 'grupo' }, [
      el(doc, 'h2', {}, ['Partido']),
      bloqueTotal(doc, 'Total de puntos - Partido', '163.5', '1.66', '2.15'),
    ]),
    el(doc, 'section', { class: 'grupo' }, [
      el(doc, 'h2', {}, ['Segunda mitad']),
      bloqueTotal(doc, 'Total de puntos - 2ª mitad', '84.5', '1.85', '1.95'),
    ]),
    el(doc, 'section', { class: 'grupo' }, [
      el(doc, 'h2', {}, ['Cuarto 4']),
      bloqueTotal(doc, 'Total de puntos - Cuarto 4', '44.5', '1.75', '1.90'),
    ]),
  ]));

  const registros = scanLib.scanMarkets(doc, adapter, deps);
  const porClave = new Map(registros.map((r) => [r.key, r]));
  assert.ok(porClave.has('GAME_TOTAL'), 'total del partido');
  assert.ok(porClave.has('SECOND_HALF_TOTAL'), 'total de la segunda mitad');
  assert.ok(porClave.has('Q4_TOTAL'), 'total del cuarto 4');
  // Cada mercado con SUS lineas: ninguno arrastra las del vecino.
  assert.deepEqual(porClave.get('GAME_TOTAL').lines.map((l) => l.line), [163.5]);
  assert.deepEqual(porClave.get('SECOND_HALF_TOTAL').lines.map((l) => l.line), [84.5]);
  assert.deepEqual(porClave.get('Q4_TOTAL').lines.map((l) => l.line), [44.5]);
});
