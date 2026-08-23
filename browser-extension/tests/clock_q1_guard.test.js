'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const guard = require('../src/lib/clock_q1_guard.js');

function sample(overrides = {}) {
  return {
    structured: true,
    gameState: {
      period: 1,
      clock: '08:40',
      clockRaw: '08:40',
      clockSemantics: 'PERIOD_REMAINING',
      scoreA: 18,
      scoreB: 15,
    },
    diagnostics: {
      clock: {
        value: '08:40', raw: '08:40', semantics: 'PERIOD_REMAINING',
        source: 'structural', status: 'CONFIRMED', confidence: 1, reason: '',
      },
    },
    memory: {
      clock: {
        seconds: 520, value: '08:40', raw: '08:40', rawSeconds: 520,
        semantics: 'PERIOD_REMAINING', period: 1,
      },
    },
    ...overrides,
  };
}

test('Q1 estructural retira clock restante y publica GAME_ELAPSED', () => {
  const r = guard.correctResult(sample());
  assert.equal(r.gameState.clock, undefined);
  assert.equal(r.gameState.clockRaw, '08:40');
  assert.equal(r.gameState.clockSemantics, 'GAME_ELAPSED');
  assert.equal(r.memory.clock.semantics, 'GAME_ELAPSED');
  assert.equal(r.memory.clock.value, null);
  assert.equal(r.memory.clock.seconds, null);
  assert.equal(r.diagnostics.clock.source, 'kambi-structural-q1');
  assert.equal(r.diagnostics.clock.originalSemantics, 'PERIOD_REMAINING');
});

test('Q2 no se altera', () => {
  const r = sample();
  r.gameState.period = 2;
  r.memory.clock.period = 2;
  const out = guard.correctResult(r);
  assert.equal(out.gameState.clock, '08:40');
  assert.equal(out.gameState.clockSemantics, 'PERIOD_REMAINING');
});

test('Q1 heuristico no se fuerza', () => {
  const r = sample();
  r.structured = false;
  r.diagnostics.clock.source = 'heuristic';
  const out = guard.correctResult(r);
  assert.equal(out.gameState.clock, '08:40');
  assert.equal(out.gameState.clockSemantics, 'PERIOD_REMAINING');
});

test('CLOCK_STOPPED se conserva', () => {
  const r = sample();
  r.diagnostics.clock.status = 'CLOCK_STOPPED';
  const out = guard.correctResult(r);
  assert.equal(out.diagnostics.clock.status, 'CLOCK_STOPPED');
  assert.equal(out.gameState.clockSemantics, 'GAME_ELAPSED');
});

test('install envuelve ambas rutas y es idempotente', () => {
  let oneCalls = 0;
  let manyCalls = 0;
  const fake = {
    extractGameState() { oneCalls += 1; return sample(); },
    extractGameStateFromRoots() { manyCalls += 1; return sample(); },
  };
  guard.install(fake);
  const first = fake.extractGameState();
  const second = fake.extractGameStateFromRoots();
  guard.install(fake);
  fake.extractGameState();

  assert.equal(first.gameState.clockSemantics, 'GAME_ELAPSED');
  assert.equal(second.gameState.clockSemantics, 'GAME_ELAPSED');
  assert.equal(oneCalls, 2);
  assert.equal(manyCalls, 1);
});