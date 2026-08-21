const test = require('node:test');
const assert = require('node:assert');
const { redact, redactDeep, buildTextReport, buildJsonReport, formatAge,
        suggestFileName, describeHistoryEntry } = require('../src/lib/report.js');
const report = require('../src/lib/report.js');

const AHORA = 1755550000000;

function snapshotDeEjemplo() {
  return {
    url: 'https://betplay.com.co/apuestas/evento/12345',
    lastScanAt: AHORA,
    scanCount: 12,
    lastScanMs: 23,
    headerCount: 4,
    visibleMarket: 'Q3_TOTAL',
    environment: { hints: ['Angular (ng-version)'], frames: [], shadowRoots: [] },
    markets: [
      {
        key: 'GAME_TOTAL', candidate: 'GAME_TOTAL', confidence: 0.95,
        headerText: 'Partido - Total de puntos', existsInDom: true, isVisible: false,
        inViewport: false, visibilityReasons: ['display:none'],
        firstSeenAt: AHORA - 60000, lastSeenAt: AHORA - 1200, lastMutationAt: AHORA - 1200,
        rawCandidates: 8, rawLineCount: 4, duplicates: 2, occurrences: 1, rootKind: 'document',
        lines: [{ line: 158.5, overOdds: 1.80, underOdds: 1.82 }],
        debug: { tagName: 'div', role: null, ariaLabel: null, selector: 'div[data-market]',
                 selectorFragile: false, rect: { x: 0, y: 0, w: 10, h: 10 },
                 parentChain: ['section'], dataAttributes: {} },
      },
      {
        key: 'Q3_TOTAL', candidate: 'Q3_TOTAL', confidence: 0.95,
        headerText: '3er cuarto - Total de puntos', existsInDom: true, isVisible: true,
        inViewport: true, visibilityReasons: [],
        firstSeenAt: AHORA - 5000, lastSeenAt: AHORA, lastMutationAt: AHORA,
        rawCandidates: 6, rawLineCount: 3, duplicates: 0, occurrences: 1, rootKind: 'document',
        lines: [{ line: 40.5, overOdds: 1.95, underOdds: 1.72 }],
        debug: { tagName: 'div', role: null, ariaLabel: null, selector: 'div.market',
                 selectorFragile: false, rect: { x: 0, y: 0, w: 10, h: 10 },
                 parentChain: ['section'], dataAttributes: {} },
      },
    ],
    history: [
      { ts: AHORA - 3000, type: 'marketVisibleChanged', from: 'GAME_TOTAL', to: 'Q3_TOTAL' },
      { ts: AHORA - 1200, type: 'linesChanged', market: 'GAME_TOTAL', visible: false,
        added: [], removed: [], changed: [{ line: 158.5, from: [1.80, 1.82], to: [1.80, 1.90] }] },
    ],
    errors: [],
  };
}

// ------------------------------------------------------------------ redaccion
test('enmascara correos, saldos e identificadores largos', () => {
  assert.equal(redact('escribe a juan.perez@correo.com'), 'escribe a [correo oculto]');
  assert.equal(redact('Saldo: $ 125.000'), '[importe oculto]');
  assert.equal(redact('usuario 1234567890'), 'usuario [numero oculto]');
});

test('no destroza los datos que si interesan', () => {
  assert.equal(redact('158.5 OVER 1.80 UNDER 1.82'), '158.5 OVER 1.80 UNDER 1.82');
  assert.equal(redact('Q3 - Total de puntos'), 'Q3 - Total de puntos');
});

test('la redaccion entra en objetos anidados', () => {
  const out = redactDeep({ a: { b: ['correo@x.com', 'ok'] } });
  assert.deepEqual(out, { a: { b: ['[correo oculto]', 'ok'] } });
});

// -------------------------------------------------------------- informe texto
test('el informe legible contiene lo esencial del experimento', () => {
  const texto = buildTextReport(snapshotDeEjemplo());
  assert.match(texto, /VISORAPUESTAS DOM DIAGNOSTIC/);
  assert.match(texto, /Mercado visualmente activo: Q3/);
  assert.match(texto, /Existe en DOM: SI/);
  assert.match(texto, /Visible: NO/);
  assert.match(texto, /Oculto por: display:none/);
  assert.match(texto, /158\.5\s+OVER 1\.8\s+UNDER 1\.82/);
});

test('el informe distingue no existir de estar oculto', () => {
  const snap = snapshotDeEjemplo();
  snap.markets[0].existsInDom = false;
  const texto = buildTextReport(snap);
  assert.match(texto, /Existe en DOM: NO/);
});

test('el debug solo aparece si se pide', () => {
  const snap = snapshotDeEjemplo();
  assert.ok(!buildTextReport(snap).includes('DEBUG'));
  assert.match(buildTextReport(snap, { includeDebug: true }), /DEBUG/);
  assert.match(buildTextReport(snap, { includeDebug: true }), /selector: div\[data-market\]/);
});

test('el historial deja ver que un mercado OCULTO cambio de cuota', () => {
  const texto = buildTextReport(snapshotDeEjemplo());
  assert.match(texto, /GAME_TOTAL \(OCULTO\) cambia 158\.5: 1\.8\/1\.82 -> 1\.8\/1\.9/);
});

test('describe cada tipo de entrada del historial', () => {
  assert.match(describeHistoryEntry({ type: 'marketVisibleChanged', from: null, to: 'Q3_TOTAL' }),
               /\(ninguno\) -> Q3_TOTAL/);
  assert.match(describeHistoryEntry({ type: 'marketDisappeared', market: 'GAME_TOTAL', lastLines: 4 }),
               /desaparece GAME_TOTAL/);
  assert.match(describeHistoryEntry({ type: 'visibilityChanged', market: 'Q1_TOTAL',
                                      isVisible: false, reasons: ['display:none'] }),
               /pasa a oculto \(display:none\)/);
});

// ---------------------------------------------------------------- informe JSON
test('el JSON lleva la informacion estructurada del experimento', () => {
  const json = buildJsonReport(snapshotDeEjemplo());
  assert.equal(json.visibleMarket, 'Q3_TOTAL');
  assert.equal(json.markets.length, 2);
  const juego = json.markets.find((m) => m.key === 'GAME_TOTAL');
  assert.equal(juego.existsInDom, true);
  assert.equal(juego.isVisible, false);
  assert.equal(juego.lines[0].underOdds, 1.82);
  assert.ok(JSON.stringify(json).length > 100);
});

test('el JSON no arrastra datos de la cuenta', () => {
  const snap = snapshotDeEjemplo();
  snap.markets[0].headerText = 'Partido - Total de puntos  juan@correo.com  Saldo: $ 340.000';
  const json = buildJsonReport(snap);
  const texto = JSON.stringify(json);
  assert.ok(!texto.includes('juan@correo.com'));
  assert.ok(!texto.includes('340.000'));
  assert.match(texto, /\[correo oculto\]/);
});

test('el JSON es serializable sin ciclos', () => {
  assert.doesNotThrow(() => JSON.stringify(buildJsonReport(snapshotDeEjemplo())));
});

// ------------------------------------------------------------------ auxiliares
test('la antiguedad se lee de un vistazo', () => {
  assert.equal(formatAge(AHORA, AHORA), 'ahora');
  assert.equal(formatAge(AHORA - 5000, AHORA), 'hace 5.0 s');
  assert.equal(formatAge(AHORA - 300000, AHORA), 'hace 5 min');
  assert.equal(formatAge(null, AHORA), 'nunca');
});

test('el nombre del fichero lleva fecha y hora', () => {
  const nombre = suggestFileName(new Date(2026, 7, 18, 18, 34, 22));
  assert.equal(nombre, 'visorapuestas-dom-diagnostic-20260818-183422.json');
});

// --------------------------------------------- lo que dice el popup, probado
//
// El panel es parte del diagnostico: en las pruebas reales una sola palabra
// mal elegida ("DESCONECTADA") mando la investigacion por el camino contrario.

test('el escaner dice ACTIVO cuando no hay errores', () => {
  const d = report.describeScanner({ scanCount: 12, lastScanMs: 34,
                                     rootCount: 5, rootsScanned: 5, activeErrors: 0 });
  assert.match(d.texto, /ACTIVO ✓/);
  assert.match(d.texto, /5\/5 raices/);
  assert.equal(d.clase, 'si');
});

test('el escaner avisa de los errores activos sin repetirlos', () => {
  const d = report.describeScanner({ scanCount: 3, lastScanMs: 20, activeErrors: 1,
                                     unstableRoots: [{ key: 'iframe:x' }] });
  assert.match(d.texto, /CON INCIDENCIAS/);
  assert.match(d.texto, /1 error\(es\) activos/);
  assert.match(d.texto, /1 raiz\(ces\) en descanso/);
});

test('marcador confirmado se muestra con los equipos', () => {
  const d = report.describeGamePart(
    { scoreA: 56, scoreB: 69 },
    { score: { status: 'CONFIRMED', teams: ['Las Vegas Aces', 'Atlanta Dream'] } },
    'marcador');
  assert.match(d.texto, /56-69 ✓/);
  assert.match(d.texto, /Las Vegas Aces \/ Atlanta Dream/);
  assert.equal(d.clase, 'si');
});

test('marcador en revision se distingue de marcador ausente', () => {
  const revision = report.describeGamePart(
    { scoreA: 58, scoreB: 52 },
    { score: { status: 'UNDER_REVIEW', candidate: { scoreA: 40, scoreB: 52 } } },
    'marcador');
  assert.match(revision.texto, /58-52/);
  assert.match(revision.texto, /EN REVISION: se leyo 40-52/);

  const ausente = report.describeGamePart(
    null, { score: { reason: 'evidencia insuficiente (0.25 < 0.6)' } }, 'marcador');
  assert.match(ausente.texto, /no disponible/);
  assert.match(ausente.texto, /0\.25/);
});

test('cuarto y reloj se dicen por separado', () => {
  const cuarto = report.describeGamePart({ period: 3 }, {}, 'cuarto');
  assert.equal(cuarto.texto, 'Q3 ✓');
  const reloj = report.describeGamePart({ period: 3 },
                                        { clock: { reason: 'sin candidatos' } }, 'reloj');
  assert.match(reloj.texto, /no disponible/);
  assert.match(reloj.texto, /sin candidatos/);
});

test('el resumen de mercados cuenta los que traen lineas', () => {
  const d = report.describeMarketsSummary({ markets: [
    { existsInDom: true, lines: [{ line: 44.5 }] },
    { existsInDom: true, lines: [] },
    { existsInDom: false, lines: [{ line: 1 }] },
  ] });
  assert.equal(d.texto, '2 detectado(s), 1 con lineas');
});

test('los errores se pintan agrupados, con su cuenta', () => {
  const lineas = report.describeErrors({ errors: [{
    type: 'createTreeWalker', rootKind: 'iframe', rootLabel: 'live',
    message: "Cannot read properties of null (reading 'createTreeWalker')", count: 43,
  }] });
  assert.equal(lineas.length, 1);
  assert.match(lineas[0], /createTreeWalker \/ iframe \(live\)  x43/);
});

test('el escaner muestra el coste del escaneo cuando hay medida', () => {
  const d = report.describeScanner({ scanCount: 40, lastScanMs: 18, avgScanMs: 22,
                                     scansPerMinute: 12.5, rootCount: 6, rootsScanned: 6 });
  assert.match(d.texto, /18 ms/);
  assert.match(d.texto, /media 22 ms/);
  assert.match(d.texto, /12\.5\/min/);
});

test('un reloj en otra semantica NO se anuncia como reloj ausente', () => {
  // BetPlay muestra el tiempo JUGADO del partido. La casa SI da reloj.
  const d = report.describeGamePart(
    { period: 4, clockRaw: '33:52', clockSemantics: 'GAME_ELAPSED' },
    { clock: { semantics: 'GAME_ELAPSED' } }, 'reloj');
  assert.match(d.texto, /33:52 jugado del partido/);
  assert.match(d.texto, /lo convierte la app/);
  assert.equal(d.clase, 'si');
});

test('un reloj que de verdad no esta sigue diciendose "no disponible"', () => {
  const d = report.describeGamePart({ period: 4 },
                                    { clock: { reason: 'sin candidatos' } }, 'reloj');
  assert.match(d.texto, /no disponible/);
  assert.match(d.texto, /sin candidatos/);
});
