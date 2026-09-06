/**
 * La vista TODO de BetPlay, montada como fixture y leida con el adaptador real.
 *
 * Cubre lo que fallo en las pruebas manuales, en el mismo orden en que fallo:
 *
 *   1. el UNDER se perdia y solo llegaba el OVER;
 *   2. numeros enteros del marcador y de las estadisticas (24, 32, 109) se
 *      colaban como lineas de apuestas;
 *   3. "Total de puntos - Prorroga incluida" quedaba en DESCONOCIDO (0.50)
 *      aunque estuviera dentro de la seccion PARTIDO;
 *   4. el total POR EQUIPO y el handicap contaminaban el total del partido.
 */
const test = require('node:test');
const assert = require('node:assert');
const dom = require('../src/lib/dom.js');
const scanLib = require('../src/lib/scan.js');
const marketsLib = require('../src/lib/markets.js');
const visibility = require('../src/lib/visibility.js');
const { createDocument, el } = require('./fake_dom.js');

const A = dom.createAdapter();
const DEPS = { identify: marketsLib.identifyMarket, sectionOf: marketsLib.sectionKey };

/** Una opcion: la etiqueta con su linea, y la cuota en un nodo aparte. */
function opcion(doc, etiqueta, cuota) {
  return el(doc, 'div', { class: 'option' }, [
    el(doc, 'span', { class: 'option__label' }, [etiqueta]),
    el(doc, 'span', { class: 'option__odds' }, [cuota]),
  ]);
}

/** Un mercado de total con una o varias lineas. */
function mercadoTotal(doc, titulo, filas) {
  const opciones = [];
  for (const [linea, over, under] of filas) {
    opciones.push(opcion(doc, `Más de ${linea}`, over));
    opciones.push(opcion(doc, `Menos de ${linea}`, under));
  }
  return el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', { class: 'market__title' }, [titulo]),
    el(doc, 'div', { class: 'market__options' }, opciones),
  ]);
}

/** Una seccion de la vista TODO, con su cabecera y sus mercados. */
function seccion(doc, etiqueta, mercados) {
  return el(doc, 'section', { class: 'markets-group' }, [
    el(doc, 'h2', { class: 'markets-group__title' }, [etiqueta]),
    ...mercados,
  ]);
}

function escanear(body) {
  const registros = scanLib.scanMarkets(body, A, DEPS);
  return new Map(registros.map((r) => [r.key, r]));
}

// ------------------------------------------------------------------- OVER/UNDER

test('G. Q4 con 44.5: llegan OVER 1.75 y UNDER 1.90', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoTotal(doc, 'Total de puntos - Cuarto 4',
                                    [['44.5', '1.75', '1.90']]));
  const registro = escanear(doc.body).get('Q4_TOTAL');
  assert.ok(registro, 'el mercado se identifica');
  assert.equal(registro.lines.length, 1);
  assert.equal(registro.lines[0].line, 44.5);
  assert.equal(registro.lines[0].overOdds, 1.75);
  assert.equal(registro.lines[0].underOdds, 1.90,
               'el UNDER es el dato central: no puede volver a perderse');
  assert.equal(registro.sideMarkers.both, true,
               'los lados vienen de "Mas de"/"Menos de", no de la posicion');
});

test('H. varias lineas del mismo mercado, cada una con sus dos cuotas', () => {
  const doc = createDocument();
  doc.body.appendChild(mercadoTotal(doc, 'Total de puntos - Cuarto 4', [
    ['43.5', '1.60', '2.30'],
    ['44.5', '1.75', '1.90'],
    ['45.5', '1.95', '1.80'],
  ]));
  const registro = escanear(doc.body).get('Q4_TOTAL');
  assert.deepEqual(
    registro.lines.map((l) => [l.line, l.overOdds, l.underOdds]),
    [[43.5, 1.6, 2.3], [44.5, 1.75, 1.9], [45.5, 1.95, 1.8]]);
});

test('si solo hay una de las dos cuotas, se dice: el otro lado queda en null', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'section', { class: 'market' }, [
    el(doc, 'h3', {}, ['Total de puntos - Cuarto 4']),
    el(doc, 'div', { class: 'market__options' }, [opcion(doc, 'Más de 44.5', '1.75')]),
  ]));
  const registro = escanear(doc.body).get('Q4_TOTAL');
  assert.equal(registro.lines[0].overOdds, 1.75);
  assert.equal(registro.lines[0].underOdds, null,
               'preferimos UNDER desconocido a una cuota inventada');
});

// -------------------------------------------------------------- enteros fuera

test('L. un 109 del marcador NO se convierte en linea', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', {}, [
    el(doc, 'div', { class: 'scoreboard' }, [
      el(doc, 'span', {}, ['109']), el(doc, 'span', {}, ['98']),
    ]),
    mercadoTotal(doc, 'Total de puntos - Cuarto 4', [['44.5', '1.75', '1.90']]),
  ]));
  const registro = escanear(doc.body).get('Q4_TOTAL');
  assert.deepEqual(registro.lines.map((l) => l.line), [44.5],
                   'solo la linea de verdad, que va en .5');
});

test('los enteros nunca son lineas de total por defecto', () => {
  const lines = require('../src/lib/lines.js');
  for (const entero of [24, 32, 109, 132]) {
    assert.equal(lines.isStrictLineShaped(entero, 0, false), false, String(entero));
  }
  for (const media of [43.5, 44.5, 163.5]) {
    assert.equal(lines.isStrictLineShaped(media, 1, false), true, String(media));
  }
  // Un .0 escrito con decimal tampoco: BetPlay ofrece los totales en .5.
  assert.equal(lines.isStrictLineShaped(44.0, 1, false), false);
});

// ------------------------------------------------- clasificacion contextual

test('I. GAME_TOTAL se identifica por SECCION + titulo, sin decir "Partido"', () => {
  const doc = createDocument();
  doc.body.appendChild(seccion(doc, 'PARTIDO', [
    mercadoTotal(doc, 'Total de puntos - Prórroga incluida', [['163.5', '1.66', '2.15']]),
  ]));
  const registro = escanear(doc.body).get('GAME_TOTAL');
  assert.ok(registro, 'ya no se queda en DESCONOCIDO');
  assert.ok(registro.confidence >= 0.9, `confianza ${registro.confidence}`);
  assert.equal(registro.lines[0].line, 163.5);
});

test('un total sin periodo dentro de SECOND HALF es el total de la 2.a mitad', () => {
  const doc = createDocument();
  doc.body.appendChild(seccion(doc, 'Second Half', [
    mercadoTotal(doc, 'Total de puntos', [['84.5', '1.85', '1.95']]),
  ]));
  const mercados = escanear(doc.body);
  const registro = mercados.get('SECOND_HALF_TOTAL');
  assert.ok(registro, `claves vistas: ${[...mercados.keys()].join(', ')}`);
  assert.ok(registro.confidence >= 0.9);
  assert.equal(registro.sectionKey, 'SECOND_HALF_TOTAL');
});

test('una cabecera de seccion no se confunde con un titulo de mercado', () => {
  assert.equal(marketsLib.sectionKey('Partido'), 'GAME_TOTAL');
  assert.equal(marketsLib.sectionKey('Cuarto 4'), 'Q4_TOTAL');
  assert.equal(marketsLib.sectionKey('Total de puntos - Cuarto 4'), null,
               'esto es un mercado, no una seccion');
  assert.equal(marketsLib.sectionKey('Hándicap'), null);
  assert.equal(marketsLib.sectionKey('Total equipo local'), null);
});

test('el titulo manda sobre la seccion cuando dicen cosas distintas', () => {
  const r = marketsLib.identifyMarket('Total de puntos - Cuarto 4',
                                      { sectionKey: 'GAME_TOTAL' });
  assert.equal(r.key, 'Q4_TOTAL', 'el titulo es el nombre propio del mercado');
  assert.ok(r.reasons.some((m) => /aviso: la seccion dice/.test(m)),
            'pero el desacuerdo queda anotado');
});

// -------------------------------------------------------- mercados que NO son

test('J. el total POR EQUIPO no contamina el total del partido', () => {
  const doc = createDocument();
  doc.body.appendChild(seccion(doc, 'PARTIDO', [
    mercadoTotal(doc, 'Total de puntos - Prórroga incluida', [['163.5', '1.66', '2.15']]),
    mercadoTotal(doc, 'Total de puntos equipo local', [['82.5', '1.90', '1.90']]),
  ]));
  const mercados = escanear(doc.body);
  assert.deepEqual(mercados.get('GAME_TOTAL').lines.map((l) => l.line), [163.5]);
  assert.ok(!mercados.has('SECOND_HALF_TOTAL'));
  const porEquipo = marketsLib.identifyMarket('Total de puntos equipo local',
                                              { sectionKey: 'GAME_TOTAL' });
  assert.equal(porEquipo.key, 'UNKNOWN');
  assert.ok(porEquipo.reasons.some((m) => /total por equipo/.test(m)));
});

test('K. el handicap no entra como total', () => {
  const doc = createDocument();
  doc.body.appendChild(seccion(doc, 'PARTIDO', [
    mercadoTotal(doc, 'Total de puntos - Prórroga incluida', [['163.5', '1.66', '2.15']]),
    mercadoTotal(doc, 'Hándicap - Prórroga incluida', [['-5.5', '1.90', '1.90']]),
  ]));
  const mercados = escanear(doc.body);
  assert.deepEqual(mercados.get('GAME_TOTAL').lines.map((l) => l.line), [163.5],
                   'la linea del handicap no se cuela en el total del partido');
  assert.equal(marketsLib.identifyMarket('Hándicap - Prórroga incluida').key, 'UNKNOWN');
});

test('Kambi real: cada li de subcategoria limita fisicamente GAME_TOTAL', () => {
  const doc = createDocument();
  const submercado = (clase, titulo, opciones) => el(doc, 'li', {
    class: `KambiBC-bet-offer-subcategory ${clase}`,
  }, [el(doc, 'div', { class: 'KambiBC-bet-offer-subcategory__container' }, [
    el(doc, 'h3', {}, [titulo]),
    el(doc, 'div', { class: 'KambiBC-bet-offer-subcategory__outcomes-list' }, opciones),
  ])]);

  const totales = [];
  for (const [linea, over, under] of [
    ['195.5', '1.67', '2.00'],
    ['196.5', '1.87', '1.82'],
    ['197.5', '2.06', '1.62'],
  ]) {
    totales.push(opcion(doc, `Más de ${linea}`, over));
    totales.push(opcion(doc, `Menos de ${linea}`, under));
  }

  doc.body.appendChild(el(doc, 'section', { class: 'markets-group' }, [
    el(doc, 'h2', {}, ['PARTIDO']),
    el(doc, 'ul', { class: 'KambiBC-bet-offer-category__subcategories' }, [
      submercado('KambiBC-bet-offer-subcategory--overunder',
                 'Total de puntos - Prórroga incluida', totales),
      submercado('KambiBC-bet-offer-subcategory--handicap',
                 'Hándicap de Puntos - Prórroga incluida', [
                   opcion(doc, 'Alemania -31.5', '2.12'),
                   opcion(doc, 'Alemania -30.5', '1.90'),
                   opcion(doc, 'Alemania -29.5', '1.67'),
                   opcion(doc, 'República Checa +31.5', '1.60'),
                   opcion(doc, 'República Checa +30.5', '1.81'),
                   opcion(doc, 'República Checa +29.5', '2.02'),
                 ]),
      submercado('winner', 'Ganador del cuarto', [opcion(doc, 'Alemania', '1.40')]),
      submercado('margin', 'Margen de victoria', [opcion(doc, '26-30', '3.50')]),
      submercado('unsupported', 'Mercado especial no soportado', [
        opcion(doc, 'Más de 88.5', '1.75'),
      ]),
    ]),
  ]));

  const registro = escanear(doc.body).get('GAME_TOTAL');
  assert.ok(registro, 'se reconoce el total del partido');
  assert.deepEqual(registro.lines.map((l) => [l.line, l.overOdds, l.underOdds]), [
    [195.5, 1.67, 2.00],
    [196.5, 1.87, 1.82],
    [197.5, 2.06, 1.62],
  ]);
  for (const imposible of [29.5, 30.5, 31.5, 88.5]) {
    assert.ok(!registro.lines.some((linea) => linea.line === imposible),
              `${imposible} pertenece a otra oferta y no puede cruzar el li`);
  }
  assert.match(String(registro.container.className), /bet-offer-subcategory/);
  assert.equal(registro.container.tagName, 'LI', 'la frontera es la oferta, no su container interno');
  assert.ok(!/category__subcategories/.test(String(registro.container.className)),
            'el contenedor nunca sube al ul de ofertas hermanas');
});

// ------------------------------------------------------------- la vista TODO

test('M. TODO con PARTIDO, SECOND HALF y Q4 abiertos: los tres a la vez', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', { class: 'all-markets' }, [
    seccion(doc, 'PARTIDO', [
      mercadoTotal(doc, 'Total de puntos - Prórroga incluida', [['163.5', '1.66', '2.15']]),
    ]),
    seccion(doc, 'Second Half', [
      mercadoTotal(doc, 'Total de puntos', [['84.5', '1.85', '1.95']]),
    ]),
    seccion(doc, 'Cuarto 4', [
      mercadoTotal(doc, 'Total de puntos - Cuarto 4', [['44.5', '1.75', '1.90']]),
    ]),
  ]));
  const mercados = escanear(doc.body);

  assert.deepEqual([...mercados.keys()].sort(),
                   ['GAME_TOTAL', 'Q4_TOTAL', 'SECOND_HALF_TOTAL']);
  // Cada uno con SUS lineas: la frontera entre mercados aguanta.
  assert.deepEqual(mercados.get('GAME_TOTAL').lines.map((l) => l.line), [163.5]);
  assert.deepEqual(mercados.get('SECOND_HALF_TOTAL').lines.map((l) => l.line), [84.5]);
  assert.deepEqual(mercados.get('Q4_TOTAL').lines.map((l) => l.line), [44.5]);
  // Y con sus dos cuotas cada una.
  assert.equal(mercados.get('Q4_TOTAL').lines[0].underOdds, 1.90);
  assert.equal(mercados.get('GAME_TOTAL').lines[0].underOdds, 2.15);
});

test('N. un mercado fuera del viewport sigue estando visible y observable', () => {
  const fuera = visibility.classifyVisibility({
    displayNone: false, visibilityHidden: false, opacityZero: false,
    hiddenAttr: false, ariaHidden: false, zeroArea: false,
    inViewport: false, detached: false,
  });
  assert.equal(fuera.existsInDom, true);
  assert.equal(fuera.isVisible, true, 'estar abajo en la pagina no es estar oculto');
  assert.equal(fuera.inViewport, false);

  const oculto = visibility.classifyVisibility({ displayNone: true });
  assert.equal(oculto.isVisible, false);
});
