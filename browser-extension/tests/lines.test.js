const test = require('node:test');
const assert = require('node:assert');
const { parseLines, isLineShaped, isOddsShaped } = require('../src/lib/lines.js');
const { dedupeLines } = require('../src/lib/dedupe.js');

test('agrupa el formato "Mas de / Menos de" de BetPlay', () => {
  // El parser extrae un candidato por fila; fundirlos es tarea de dedupe.
  // Esta es la tuberia completa tal y como la usa el content script.
  const { lines } = parseLines('Más de 140.5 1.32\nMenos de 140.5 2.85');
  assert.equal(lines.length, 2);
  const fundidas = dedupeLines(lines).lines;
  assert.equal(fundidas.length, 1);
  assert.deepEqual(
    { line: fundidas[0].line, overOdds: fundidas[0].overOdds, underOdds: fundidas[0].underOdds },
    { line: 140.5, overOdds: 1.32, underOdds: 2.85 },
  );
});

test('agrupa el formato horizontal con OVER/UNDER', () => {
  const { lines } = parseLines(
    '176.5 OVER 1.85 UNDER 2.05\n178.5 OVER 1.90 UNDER 1.93');
  assert.equal(lines.length, 2);
  assert.equal(lines[1].line, 178.5);
  assert.equal(lines[1].underOdds, 1.93);
});

test('usa el orden visual cuando no hay palabras', () => {
  const { lines } = parseLines('40.5\n1.75\n1.87');
  assert.deepEqual(
    { l: lines[0].line, o: lines[0].overOdds, u: lines[0].underOdds },
    { l: 40.5, o: 1.75, u: 1.87 });
});

test('distingue una linea de una cuota', () => {
  assert.ok(isLineShaped(140.5, 1));
  assert.ok(isLineShaped(153, 0));
  assert.ok(!isLineShaped(1.85, 2));
  assert.ok(isOddsShaped(1.85, 2));
  assert.ok(!isOddsShaped(1.8, 1));      // una cifra decimal no es una cuota
  assert.ok(!isOddsShaped(0.5, 2));
});

test('cuenta los candidatos aunque no pueda agruparlos', () => {
  const r = parseLines('1.85 2.05');     // cuotas sin linea previa
  assert.equal(r.lines.length, 0);
  assert.equal(r.rawCandidates, 2);
  assert.equal(r.unassigned, 2);
});

test('texto sin numeros no inventa lineas', () => {
  const r = parseLines('Mercado suspendido');
  assert.equal(r.lines.length, 0);
  assert.equal(r.rawCandidates, 0);
});

test('acepta la coma decimal', () => {
  const { lines } = parseLines('Más de 140,5 1,32');
  assert.equal(lines[0].line, 140.5);
  assert.equal(lines[0].overOdds, 1.32);
});
