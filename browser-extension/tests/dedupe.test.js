const test = require('node:test');
const assert = require('node:assert');
const { dedupeLines, linesSignature, diffLines } = require('../src/lib/dedupe.js');

test('funde duplicados conservando el recuento bruto', () => {
  const r = dedupeLines([
    { line: 140.5, overOdds: 1.32, underOdds: null },
    { line: 140.5, overOdds: null, underOdds: 2.85 },
    { line: 138.5, overOdds: 1.20, underOdds: 3.10 },
  ]);
  assert.equal(r.lines.length, 2);
  assert.equal(r.rawCount, 3);
  assert.equal(r.duplicates, 1);
  const fundida = r.lines.find((l) => l.line === 140.5);
  assert.equal(fundida.overOdds, 1.32);
  assert.equal(fundida.underOdds, 2.85);
});

test('la fusion no pisa un valor ya leido', () => {
  const r = dedupeLines([
    { line: 140.5, overOdds: 1.32, underOdds: 2.85 },
    { line: 140.5, overOdds: 9.99, underOdds: 9.99 },
  ]);
  assert.equal(r.lines[0].overOdds, 1.32);
});

test('la firma detecta cambios de cuota', () => {
  const a = [{ line: 158.5, overOdds: 1.80, underOdds: 1.82 }];
  const b = [{ line: 158.5, overOdds: 1.80, underOdds: 1.90 }];
  assert.notEqual(linesSignature(a), linesSignature(b));
  assert.equal(linesSignature(a), linesSignature([...a]));
});

test('la firma no depende del orden', () => {
  const a = [{ line: 1.5 }, { line: 2.5 }];
  const b = [{ line: 2.5 }, { line: 1.5 }];
  assert.equal(linesSignature(a), linesSignature(b));
});

test('el diff distingue altas, bajas y cambios de cuota', () => {
  const antes = [
    { line: 158.5, overOdds: 1.80, underOdds: 1.82 },
    { line: 159.5, overOdds: 1.90, underOdds: 1.75 },
  ];
  const despues = [
    { line: 158.5, overOdds: 1.80, underOdds: 1.90 },
    { line: 160.5, overOdds: 2.00, underOdds: 1.70 },
  ];
  const d = diffLines(antes, despues);
  assert.equal(d.changed.length, 1);
  assert.equal(d.changed[0].line, 158.5);
  assert.equal(d.added[0].line, 160.5);
  assert.equal(d.removed[0].line, 159.5);
  assert.ok(d.hasChanges);
});

test('sin cambios el diff lo dice', () => {
  const l = [{ line: 158.5, overOdds: 1.80, underOdds: 1.82 }];
  assert.equal(diffLines(l, [...l]).hasChanges, false);
});
