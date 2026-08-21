/**
 * Lectura estructural del marcador, con la maquetacion REAL de BetPlay/Kambi.
 *
 * Origen: una prueba real en Edge devolvio
 *
 *     SCOREBOARD
 *     marcador: 76-22
 *     estado: CONFIRMED
 *
 * cuando el marcador de verdad era 76-69. El 22 era el parcial del PRIMER
 * cuarto del segundo equipo. La heuristica general emparejaba numeros
 * consecutivos en orden de documento, y el unico par que cruza las dos filas
 * es justamente (total del primero, parcial del segundo); el par correcto,
 * (76, 69), ni siquiera llegaba a generarse porque no son consecutivos.
 *
 * Kambi distingue las dos cosas en la propia pagina:
 *
 *     KambiBC-scoreboard-grid-item    celda generica -> PARCIAL
 *     KambiBC-scoreboard-grid-score   celda marcada  -> TOTAL
 */
const test = require('node:test');
const assert = require('node:assert');
const dom = require('../src/lib/dom.js');
const sb = require('../src/lib/scoreboard.js');
const { createDocument, el } = require('./fake_dom.js');
const { filaKambi, scoreboardKambi } = require('./kambi_fixture.js');

const A = dom.createAdapter();

function conScoreboard(opciones) {
  const doc = createDocument();
  doc.body.appendChild(scoreboardKambi(doc, opciones));
  return doc.body;
}

// ------------------------------------------------------------ el caso real

test('el marcador REAL de Kambi se lee 76-69, no 76-22', () => {
  const r = sb.readScoreboard(conScoreboard(), A);
  assert.equal(r.found, true);
  assert.deepEqual(r.score, { scoreA: 76, scoreB: 69 });
  assert.deepEqual(r.teams, ['Dallas Wings (F)', 'Indiana Fever (F)']);
});

test('los parciales NO son candidatos a marcador', () => {
  const r = sb.readScoreboard(conScoreboard(), A);
  assert.deepEqual(r.rows[0].partials, [18, 24, 24, 10]);
  assert.deepEqual(r.rows[1].partials, [22, 20, 19, 8]);
  assert.equal(r.rows[0].total, 76);
  assert.equal(r.rows[1].total, 69);
  // 22 es el Q1 del segundo equipo y jamas puede ser la mitad del marcador.
  assert.notEqual(r.score.scoreB, 22);
});

test('grid-score gana a grid-item aunque la celda lleve las dos clases', () => {
  const doc = createDocument();
  const total = el(doc, 'span', {
    class: 'KambiBC-scoreboard-grid-score KambiBC-scoreboard-grid-item', role: 'griditem',
  }, ['76']);
  const parcial = el(doc, 'span', {
    class: 'KambiBC-scoreboard-grid-item', role: 'griditem',
  }, ['18']);
  doc.body.appendChild(el(doc, 'div', {}, [total, parcial]));

  assert.equal(sb.isTotalCell(total, A), true);
  assert.equal(sb.isPartialCell(total, A), false, 'el total NO cuenta como parcial');
  assert.equal(sb.isTotalCell(parcial, A), false);
  assert.equal(sb.isPartialCell(parcial, A), true);
});

test('el cuarto sale del bloque de reloj, no de las cabeceras de columna', () => {
  const r = sb.readScoreboard(conScoreboard(), A);
  assert.equal(r.period, 4);
  assert.ok(r.reasons.some((m) => /bloque de reloj/.test(m)));
});

test('el reloj se lee crudo, sin interpretarlo aqui', () => {
  const r = sb.readScoreboard(conScoreboard(), A);
  assert.deepEqual(r.clock, { raw: '33:52', seconds: 33 * 60 + 52 });
});

test('la suma de los parciales refuerza la lectura', () => {
  const r = sb.readScoreboard(conScoreboard(), A);
  assert.deepEqual(r.warnings, []);
  assert.ok(r.reasons.some((m) => /Dallas Wings \(F\): los parciales suman el total/.test(m)));
});

// ------------------------------------------------- lo que NO puede pasar

test('sin celda de total marcada NO se adivina: se cede a la heuristica', () => {
  const raiz = conScoreboard({ claseTotal: 'KambiBC-scoreboard-grid-item' });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, false);
  assert.match(r.reasons.join(' '), /sin marcador estructural reconocible/);
});

test('si solo un equipo tiene total, no se inventa el otro', () => {
  const raiz = conScoreboard({ totalB: null });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, false);
});

test('dos filas con el mismo nombre no son un marcador', () => {
  const raiz = conScoreboard({ equipoB: 'Dallas Wings (F)' });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, false);
  assert.match(r.reasons.join(' '), /mismo equipo/);
});

test('dos marcadores a la vez son una ambiguedad, no una eleccion', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboardKambi(doc));
  doc.body.appendChild(scoreboardKambi(doc, {
    equipoA: 'Seattle Storm (F)', totalA: 51,
    equipoB: 'Chicago Sky (F)', totalB: 47,
  }));
  const r = sb.readScoreboard(doc.body, A);
  assert.equal(r.found, false);
  assert.match(r.reasons.join(' '), /2 marcadores estructurales/);
});

test('los dos totales tienen que ser del MISMO marcador', () => {
  // Dos eventos distintos, cada uno con una sola fila: ninguno es legible.
  const doc = createDocument();
  const uno = el(doc, 'section', { class: 'KambiBC-scoreboard-container-template' }, [
    filaKambi(doc, 'Dallas Wings (F)', [18, 24, 24, 10], 76),
  ]);
  const otro = el(doc, 'section', { class: 'KambiBC-scoreboard-container-template' }, [
    filaKambi(doc, 'Indiana Fever (F)', [22, 20, 19, 8], 69),
  ]);
  doc.body.appendChild(el(doc, 'div', {}, [uno, otro]));
  assert.equal(sb.readScoreboard(doc.body, A).found, false);
});

// -------------------------------------------------------------- variantes

test('la prorroga anade columnas y no rompe la lectura', () => {
  const raiz = conScoreboard({
    periodo: 'Q5',
    parcialesA: [18, 24, 24, 10, 9], totalA: 85,
    parcialesB: [22, 20, 19, 8, 7], totalB: 76,
  });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, true);
  assert.deepEqual(r.score, { scoreA: 85, scoreB: 76 });
  assert.equal(r.period, 5, 'OT1 es el periodo 5, no un cuarto invalido');
  assert.deepEqual(r.warnings, [], 'los parciales con prorroga siguen sumando');
});

test('un cuarto a medias, con columnas vacias, se lee igual', () => {
  const raiz = conScoreboard({
    periodo: 'Q2', parcialesA: [18], totalA: 18, parcialesB: [22], totalB: 22,
  });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, true);
  assert.deepEqual(r.score, { scoreA: 18, scoreB: 22 });
});

test('si los parciales no cuadran, se avisa pero manda la celda del total', () => {
  const raiz = conScoreboard({ parcialesA: [18, 24], totalA: 76 });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, true);
  assert.equal(r.score.scoreA, 76, 'la clase del total es la evidencia buena');
  assert.match(r.warnings.join(' '), /suman 42 y el total dice 76/);
});

test('sin bloque de reloj, el marcador se lee igual y el cuarto queda en null', () => {
  const raiz = conScoreboard({ periodo: null, reloj: null });
  const r = sb.readScoreboard(raiz, A);
  assert.equal(r.found, true);
  assert.deepEqual(r.score, { scoreA: 76, scoreB: 69 });
  assert.equal(r.period, null);
  assert.equal(r.clock, null);
});

test('dos cuartos distintos en el bloque de reloj es ambiguedad', () => {
  const doc = createDocument();
  const marcador = scoreboardKambi(doc);
  const cabecera = marcador.childNodes[0].childNodes[0].childNodes[0].childNodes[0];
  cabecera.appendChild(el(doc, 'span', {}, ['Q2']));
  const r = sb.readScoreboard(doc.body.appendChild(marcador) && doc.body, A);
  assert.equal(r.period, null);
  assert.match(r.reasons.join(' '), /cuarto ambiguo/);
});

test('un nombre de equipo no puede ser un texto de mercado', () => {
  assert.equal(sb.looksLikeTeamName('Dallas Wings (F)'), true);
  assert.equal(sb.looksLikeTeamName('Indiana Fever (F)'), true);
  assert.equal(sb.looksLikeTeamName('76'), false);
  assert.equal(sb.looksLikeTeamName('Total de puntos'), false);
  assert.equal(sb.looksLikeTeamName('33:52'), false);
});

test('un nombre repetido en la misma fila sigue siendo UN equipo', () => {
  // Las casas repiten el nombre para movil y escritorio dentro del mismo bloque.
  const doc = createDocument();
  const fila = filaKambi(doc, 'Dallas Wings (F)', [18, 24, 24, 10], 76);
  fila.appendChild(el(doc, 'span', { class: 'KambiBC-scoreboard-team-label--mobile' },
                      ['Dallas Wings (F)']));
  const otra = filaKambi(doc, 'Indiana Fever (F)', [22, 20, 19, 8], 69);
  doc.body.appendChild(el(doc, 'section', {
    class: 'KambiBC-scoreboard-container-template' }, [fila, otra]));

  const r = sb.readScoreboard(doc.body, A);
  assert.equal(r.found, true);
  assert.deepEqual(r.score, { scoreA: 76, scoreB: 69 });
});

test('un contenedor desmesurado no dispara el coste de la busqueda', () => {
  const doc = createDocument();
  const enorme = el(doc, 'section', { class: 'KambiBC-scoreboard-container-template' }, [
    filaKambi(doc, 'Dallas Wings (F)', [18, 24, 24, 10], 76),
    filaKambi(doc, 'Indiana Fever (F)', [22, 20, 19, 8], 69),
  ]);
  for (let i = 0; i < sb.MAX_SCOREBOARD_NODES + 50; i += 1) {
    enorme.appendChild(el(doc, 'div', {}, [`relleno ${i}`]));
  }
  doc.body.appendChild(enorme);

  const inicio = Date.now();
  const r = sb.readScoreboard(doc.body, A);
  assert.ok(Date.now() - inicio < 2000, 'la busqueda tiene tope');
  // Las dos filas van primero, asi que se leen antes de agotar el tope.
  assert.equal(r.found, true);
  assert.deepEqual(r.score, { scoreA: 76, scoreB: 69 });
});
