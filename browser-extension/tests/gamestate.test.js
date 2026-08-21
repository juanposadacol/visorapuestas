/**
 * Marcador, cuarto y reloj: acertar importa menos que NO acertar por
 * casualidad. Ante la duda no se devuelve nada y la aplicacion usa el OCR.
 *
 * El caso que dio origen a media parte de este fichero es real: en BetPlay la
 * extension llego a mostrar
 *
 *     MARCADOR/RELOJ DOM
 *     43-232
 *
 * porque bastaba con dos enteros cercanos en el arbol. Aqui se fija que eso ya
 * no puede volver a pasar, y que un marcador de verdad si se reconoce.
 */
const test = require('node:test');
const assert = require('node:assert');
const gs = require('../src/lib/gamestate.js');
const dom = require('../src/lib/dom.js');
const { createDocument, el } = require('./fake_dom.js');

const A = dom.createAdapter();

/** Cabecera de evento como la que pinta una casa de apuestas. */
function scoreboard(doc, opciones) {
  const o = { a: 56, b: 69, equipoA: 'Las Vegas Aces', equipoB: 'Atlanta Dream',
              periodo: 'Q3', reloj: '06:42', ...(opciones || {}) };
  const hijos = [
    el(doc, 'div', { class: 'scoreboard__team team--home' }, [
      el(doc, 'span', { class: 'team__name' }, [o.equipoA]),
      el(doc, 'span', { class: 'team__score' }, [String(o.a)]),
    ]),
    el(doc, 'div', { class: 'scoreboard__team team--away' }, [
      el(doc, 'span', { class: 'team__name' }, [o.equipoB]),
      el(doc, 'span', { class: 'team__score' }, [String(o.b)]),
    ]),
  ];
  if (o.periodo || o.reloj) {
    hijos.push(el(doc, 'div', { class: 'scoreboard__status live' }, [
      ...(o.periodo ? [el(doc, 'span', { class: 'period' }, [o.periodo])] : []),
      ...(o.reloj ? [el(doc, 'span', { class: 'clock' }, [o.reloj])] : []),
    ]));
  }
  return el(doc, 'div', { class: 'event-header scoreboard' }, hijos);
}

function conCuerpo(construir) {
  const doc = createDocument();
  construir(doc, doc.body);
  return doc.body;
}

// -------------------------------------------------------------- lo que SI vale

test('F. un marcador dentro de un scoreboard semantico se acepta a la primera', () => {
  const raiz = conCuerpo((doc, body) => body.appendChild(scoreboard(doc)));
  const r = gs.extractGameState(raiz, A, null);
  assert.deepEqual(r.gameState, { clock: '06:42', period: 3, scoreA: 56, scoreB: 69 });
  assert.equal(r.diagnostics.score.status, 'CONFIRMED');
  assert.deepEqual(r.diagnostics.score.teams, ['Las Vegas Aces', 'Atlanta Dream']);
});

test('la puntuacion del marcador correcto es alta y dice por que', () => {
  const raiz = conCuerpo((doc, body) => body.appendChild(scoreboard(doc)));
  const [candidato] = gs.findScoreCandidates(raiz, A, null);
  assert.ok(candidato.confidence >= 0.9, `confianza ${candidato.confidence}`);
  assert.ok(candidato.strong, 'evidencia estructural fuerte');
  assert.ok(candidato.reasons.some((m) => /equipos asociados/.test(m)));
  assert.ok(candidato.reasons.some((m) => /contenedor de marcador/.test(m)));
});

// ------------------------------------------------------------- lo que NO vale

test('E. 43-232 NO se acepta como marcador por proximidad sola', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'row' }, [
      el(doc, 'div', {}, ['43']),
      el(doc, 'div', {}, ['232']),
    ]));
  });
  const [candidato] = gs.findScoreCandidates(raiz, A, null);
  assert.equal(candidato.raw, '43-232', 'se ve el candidato...');
  assert.ok(candidato.confidence < 0.5, `...pero con confianza baja (${candidato.confidence})`);
  assert.equal(gs.extractGameState(raiz, A, null).gameState, null,
               'y no se publica nada');
});

test('E. 43-232 repetido sin evidencia sigue sin publicarse', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'row' }, [
      el(doc, 'div', {}, ['43']),
      el(doc, 'div', {}, ['232']),
    ]));
  });
  let memoria = null;
  for (let i = 0; i < 8; i += 1) {
    const r = gs.extractGameState(raiz, A, memoria);
    memoria = r.memory;
    assert.equal(r.gameState, null, `lectura ${i + 1}`);
  }
});

test('numeros dentro de un bloque de apuestas nunca son el marcador', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'market-list' }, [
      el(doc, 'div', { class: 'market__outcome' }, [
        el(doc, 'span', {}, ['56']),
        el(doc, 'span', {}, ['69']),
      ]),
    ]));
  });
  const [candidato] = gs.findScoreCandidates(raiz, A, null);
  assert.ok(candidato.confidence < 0.3, `confianza ${candidato.confidence}`);
  assert.ok(candidato.reasons.some((m) => /apuestas/.test(m)));
  assert.equal(gs.extractGameState(raiz, A, null).gameState, null);
});

test('una fila de estadisticas llena de numeros no produce marcador', () => {
  const raiz = conCuerpo((doc, body) => {
    const panel = el(doc, 'div', { class: 'stats-panel' }, []);
    for (const n of ['12', '43', '232', '7', '109', '88', '5']) {
      panel.appendChild(el(doc, 'span', {}, [n]));
    }
    body.appendChild(panel);
  });
  const candidatos = gs.findScoreCandidates(raiz, A, null);
  assert.ok(candidatos.every((c) => c.confidence < 0.4),
            'ninguna pareja llega a nada');
  assert.equal(gs.extractGameState(raiz, A, null).gameState, null);
});

test('un numero suelto no se toma por marcador', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', {}, [
      el(doc, 'span', {}, ['Rebotes']), el(doc, 'span', {}, ['42']),
    ]));
  });
  assert.equal(gs.extractGameState(raiz, A, null).gameState, null);
});

// ------------------------------------------------- estabilizacion en el tiempo

test('sin atributos claros hace falta ver la misma lectura varias veces', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', {}, [
      el(doc, 'div', {}, [el(doc, 'span', {}, ['Las Vegas Aces']),
                          el(doc, 'span', {}, ['56'])]),
      el(doc, 'div', {}, [el(doc, 'span', {}, ['Atlanta Dream']),
                          el(doc, 'span', {}, ['69'])]),
    ]));
  });
  let memoria = null;
  const publicados = [];
  for (let i = 0; i < 4; i += 1) {
    const r = gs.extractGameState(raiz, A, memoria);
    memoria = r.memory;
    publicados.push(r.gameState ? `${r.gameState.scoreA}-${r.gameState.scoreB}` : null);
  }
  assert.deepEqual(publicados, [null, null, '56-69', '56-69'],
                   'candidate primero, confirmed despues');
});

test('con marcador confirmado, una subida normal se acepta enseguida', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, { a: 58, b: 52 }));
  const primero = gs.extractGameState(doc.body, A, null);
  assert.equal(primero.gameState.scoreA, 58);

  const doc2 = createDocument();
  doc2.body.appendChild(scoreboard(doc2, { a: 60, b: 52 }));
  const segundo = gs.extractGameState(doc2.body, A, primero.memory);
  assert.equal(segundo.gameState.scoreA, 60);
  assert.equal(segundo.diagnostics.score.status, 'CONFIRMED');
});

test('un retroceso no reemplaza el marcador: queda SCORE_UNDER_REVIEW', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, { a: 58, b: 52 }));
  const primero = gs.extractGameState(doc.body, A, null);

  const doc2 = createDocument();
  doc2.body.appendChild(scoreboard(doc2, { a: 40, b: 52 }));
  const segundo = gs.extractGameState(doc2.body, A, primero.memory);

  assert.equal(segundo.gameState.scoreA, 58, 'se conserva el anterior');
  assert.equal(segundo.diagnostics.score.status, 'UNDER_REVIEW');
  assert.equal(segundo.diagnostics.underReview, true);
  assert.match(segundo.diagnostics.score.reason, /incompatible/);
});

test('un salto imposible tampoco entra de golpe', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, { a: 58, b: 52 }));
  const primero = gs.extractGameState(doc.body, A, null);

  const doc2 = createDocument();
  doc2.body.appendChild(scoreboard(doc2, { a: 121, b: 7 }));
  const segundo = gs.extractGameState(doc2.body, A, primero.memory);
  assert.deepEqual([segundo.gameState.scoreA, segundo.gameState.scoreB], [58, 52]);
  assert.equal(segundo.diagnostics.score.status, 'UNDER_REVIEW');
});

test('una correccion REAL de la casa acaba aceptandose si insiste', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, { a: 58, b: 52 }));
  let memoria = gs.extractGameState(doc.body, A, null).memory;

  const corregido = createDocument();
  corregido.body.appendChild(scoreboard(corregido, { a: 55, b: 52 }));
  const vistos = [];
  for (let i = 0; i < 4; i += 1) {
    const r = gs.extractGameState(corregido.body, A, memoria);
    memoria = r.memory;
    vistos.push(`${r.gameState.scoreA}-${r.gameState.scoreB}`);
  }
  assert.deepEqual(vistos, ['58-52', '58-52', '55-52', '55-52'],
                   'primero en revision, y solo despues se acepta');
});

test('si el marcador desaparece un instante, no se olvida el confirmado', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, { a: 58, b: 52 }));
  const primero = gs.extractGameState(doc.body, A, null);

  const vacio = conCuerpo((d, body) => body.appendChild(el(d, 'div', {}, ['cargando'])));
  const segundo = gs.extractGameState(vacio, A, primero.memory);
  assert.equal(segundo.gameState.scoreA, 58);
  assert.equal(segundo.diagnostics.score.status, 'CONFIRMED');
});

// ------------------------------------------------------------------- reloj

test('el reloj exige forma MM:SS y minutos verosimiles', () => {
  const conTexto = (valor) => conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'span', { class: 'clock' }, [valor]));
  });
  assert.equal(gs.findClockCandidates(conTexto('06:24'), A).length, 1);
  assert.equal(gs.findClockCandidates(conTexto('6:99'), A).length, 0);
  assert.equal(gs.findClockCandidates(conTexto('45:00'), A).length, 0);
  assert.equal(gs.findClockCandidates(conTexto('abc'), A).length, 0);
});

test('un MM:SS suelto sin contexto NO se toma por el reloj del partido', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'promo-banner' }, [
      el(doc, 'span', {}, ['Termina en']), el(doc, 'span', {}, ['09:30']),
    ]));
  });
  const [candidato] = gs.findClockCandidates(raiz, A);
  assert.ok(candidato.confidence < 0.6, `confianza ${candidato.confidence}`);
  assert.equal(gs.extractGameState(raiz, A, null).gameState, null);
});

test('el reloj del marcador si se reconoce, y dice por que', () => {
  const raiz = conCuerpo((doc, body) => body.appendChild(scoreboard(doc)));
  const [candidato] = gs.findClockCandidates(raiz, A);
  assert.ok(candidato.confidence >= 0.6);
  assert.ok(candidato.reasons.some((m) => /marcador/.test(m)));
});

test('dos relojes igual de plausibles no producen reloj', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'scoreboard live' }, [
      el(doc, 'span', { class: 'clock' }, ['06:24']),
    ]));
    body.appendChild(el(doc, 'div', { class: 'scoreboard live' }, [
      el(doc, 'span', { class: 'clock' }, ['03:11']),
    ]));
  });
  const r = gs.extractGameState(raiz, A, null);
  assert.equal(r.diagnostics.clock.reason, 'candidatos ambiguos');
  assert.deepEqual(r.diagnostics.clock.ambiguous, ['06:24', '03:11']);
});

test('el reloj baja, o sube solo al empezar un cuarto', () => {
  const anterior = { seconds: 384 };
  assert.ok(gs.clockValidator({ seconds: 380 }, anterior));
  assert.ok(gs.clockValidator({ seconds: 384 }, anterior));      // parado
  assert.ok(!gs.clockValidator({ seconds: 500 }, anterior));     // salto raro
  assert.ok(gs.clockValidator({ seconds: 600 }, anterior));      // cuarto nuevo
});

// ------------------------------------------------------------------ cuarto

test('el cuarto se reconoce en varias formas', () => {
  for (const etiqueta of ['Q3', '3Q', 'Cuarto 3', '3er cuarto']) {
    const raiz = conCuerpo((doc, body) => {
      body.appendChild(el(doc, 'div', { class: 'scoreboard__status live' }, [
        el(doc, 'span', { class: 'period' }, [etiqueta]),
      ]));
    });
    const encontrados = gs.findPeriodCandidates(raiz, A);
    assert.equal(encontrados.length, 1, etiqueta);
    assert.equal(encontrados[0].value, 3, etiqueta);
  }
});

test('el cuarto de un MERCADO no es el cuarto del partido', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'scoreboard__status live' }, [
      el(doc, 'span', { class: 'period' }, ['Q3']),
    ]));
    body.appendChild(el(doc, 'div', { class: 'market-list' }, [
      el(doc, 'div', { class: 'market__header' }, ['Cuarto 4']),
    ]));
  });
  const r = gs.extractGameState(raiz, A, null);
  assert.equal(r.gameState.period, 3, 'manda el marcador, no la pestana del mercado');

  const soloMercado = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'market-list' }, [
      el(doc, 'div', { class: 'market__header' }, ['Cuarto 4']),
    ]));
  });
  assert.equal(gs.extractGameState(soloMercado, A, null).gameState, null,
               'un mercado de Q4 por si solo no dice en que cuarto va el partido');
});

test('el cuarto no retrocede ni se sale de rango', () => {
  assert.ok(gs.periodValidator({ value: 4 }, 3));
  assert.ok(!gs.periodValidator({ value: 2 }, 3));
  assert.ok(!gs.periodValidator({ value: 7 }, null));
});

// --------------------------------------------------------- estados parciales

test('un estado parcial se envia solo con lo que se sabe', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', { class: 'scoreboard__status live' }, [
      el(doc, 'span', { class: 'clock' }, ['06:24']),
    ]));
  });
  assert.deepEqual(gs.extractGameState(raiz, A, null).gameState, { clock: '06:24' });
});

test('marcador sin reloj tambien es un estado valido', () => {
  const doc = createDocument();
  doc.body.appendChild(scoreboard(doc, { reloj: null, periodo: null }));
  const r = gs.extractGameState(doc.body, A, null);
  assert.deepEqual(r.gameState, { scoreA: 56, scoreB: 69 });
});

test('sin nada reconocible no se inventa un estado', () => {
  const raiz = conCuerpo((doc, body) => {
    body.appendChild(el(doc, 'div', {}, ['Mis apuestas']));
    body.appendChild(el(doc, 'div', {}, ['Retirar']));
  });
  const r = gs.extractGameState(raiz, A, null);
  assert.equal(r.gameState, null);
  assert.equal(r.diagnostics.score.reason, 'sin candidatos');
});

// ------------------------------------------------------------- piezas sueltas

test('ante dos candidatos igual de plausibles no se elige ninguno', () => {
  const r = gs.pickBest([
    { value: 3, confidence: 0.8, raw: 'Q3' },
    { value: 4, confidence: 0.8, raw: 'Q4' },
  ], null, () => true);
  assert.equal(r.value, null);
  assert.equal(r.reason, 'candidatos ambiguos');
  assert.deepEqual(r.ambiguous, ['Q3', 'Q4']);
});

test('dos candidatos que dicen lo MISMO no son ambiguos', () => {
  const r = gs.pickBest([
    { value: 3, confidence: 0.8, raw: 'Q3' },
    { value: 3, confidence: 0.8, raw: 'Cuarto 3' },
  ], null, () => true);
  assert.equal(r.value, 3);
});

test('reconoce nombres de equipo y descarta lo que no lo es', () => {
  assert.ok(gs.pareceNombreDeEquipo('Las Vegas Aces'));
  assert.ok(gs.pareceNombreDeEquipo('Atlanta Dream'));
  assert.ok(!gs.pareceNombreDeEquipo('56'));
  assert.ok(!gs.pareceNombreDeEquipo('06:42'));
  assert.ok(!gs.pareceNombreDeEquipo('Más de 44.5'));
  assert.ok(!gs.pareceNombreDeEquipo('Total de puntos'));
  assert.ok(!gs.pareceNombreDeEquipo('Q3'));
});

test('continuaDe acepta subidas normales y rechaza lo imposible', () => {
  const previo = { scoreA: 58, scoreB: 52 };
  assert.ok(gs.continuaDe(previo, { scoreA: 60, scoreB: 52 }));
  assert.ok(gs.continuaDe(previo, { scoreA: 58, scoreB: 54 }));
  assert.ok(!gs.continuaDe(previo, { scoreA: 40, scoreB: 200 }));
  assert.ok(!gs.continuaDe(previo, { scoreA: 121, scoreB: 7 }));
});

test('el marcador se valida por forma, y la memoria decide lo demas', () => {
  assert.ok(gs.scoreValidator({ value: { scoreA: 60, scoreB: 52 } }, null));
  assert.ok(!gs.scoreValidator({ value: { scoreA: 999, scoreB: 52 } }, null));
  assert.ok(!gs.scoreValidator({ value: { scoreA: 1.5, scoreB: 52 } }, null));
});
