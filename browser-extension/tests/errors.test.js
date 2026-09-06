/**
 * Errores estructurados: ni ocultarlos ni repetirlos cuarenta veces.
 *
 * En la prueba real sobre BetPlay el historial quedo lleno de la MISMA linea
 * decenas de veces. Estas pruebas fijan el comportamiento contrario: una
 * entrada por causa y raiz, con su cuenta, y una raiz que falla sin parar se
 * deja descansar sin arrastrar a las raices sanas.
 */
const test = require('node:test');
const assert = require('node:assert');
const errores = require('../src/lib/errors.js');

const CRASH = "Cannot read properties of null (reading 'createTreeWalker')";

test('el mismo fallo en la misma raiz se agrupa en una entrada con cuenta', () => {
  const log = errores.createErrorLog();
  for (let i = 0; i < 43; i += 1) {
    log.record({ stage: 'scan', rootKind: 'iframe', rootLabel: 'live', message: CRASH, now: 1000 + i });
  }
  const lista = log.list();
  assert.equal(lista.length, 1, '43 ocurrencias, una sola entrada');
  assert.equal(lista[0].count, 43);
  assert.equal(lista[0].type, 'createTreeWalker');
  assert.equal(lista[0].firstSeen, 1000);
  assert.equal(lista[0].lastSeen, 1042);
  assert.equal(errores.summarize(lista[0]), 'createTreeWalker / iframe (live)  x43');
});

test('el mismo fallo en raices distintas son entradas distintas', () => {
  const log = errores.createErrorLog();
  log.record({ stage: 'scan', rootKind: 'iframe', rootLabel: 'a', message: CRASH, now: 1 });
  log.record({ stage: 'scan', rootKind: 'iframe', rootLabel: 'b', message: CRASH, now: 2 });
  log.record({ stage: 'scan', rootKind: 'document', rootLabel: 'principal', message: CRASH, now: 3 });
  assert.equal(log.list().length, 3);
});

test('clasifica las causas para agrupar mensajes parecidos', () => {
  assert.equal(errores.classify(CRASH), 'createTreeWalker');
  assert.equal(errores.classify("Cannot read properties of null (reading 'children')"),
               'propiedad-nula:children');
  assert.equal(errores.classify('Blocked a frame with origin ...'), 'otro-origen');
  assert.equal(errores.classify(''), 'desconocido');
});

test('solo cuentan como activos los errores recientes', () => {
  const log = errores.createErrorLog({ activeWindowMs: 1000 });
  log.record({ stage: 'scan', rootKind: 'iframe', message: CRASH, now: 0 });
  log.record({ stage: 'scan', rootKind: 'shadow-root', message: CRASH, now: 5000 });
  assert.equal(log.list().length, 2);
  assert.equal(log.active(5200).length, 1, 'el viejo ya no se esta repitiendo');
});

test('no crece sin limite: olvida las familias mas antiguas', () => {
  const log = errores.createErrorLog({ maxEntries: 3 });
  for (let i = 0; i < 10; i += 1) {
    log.record({ stage: 'scan', rootKind: `iframe-${i}`, message: CRASH, now: i });
  }
  assert.equal(log.size(), 3);
});

// ------------------------------------------------------------- cortacircuitos

test('una raiz que falla sin parar se marca inestable y descansa', () => {
  const breaker = errores.createCircuitBreaker({ threshold: 3, cooldownMs: 1000 });
  assert.equal(breaker.shouldSkip('iframe:live', 0), false);
  breaker.failure('iframe:live', 0);
  breaker.failure('iframe:live', 10);
  assert.equal(breaker.shouldSkip('iframe:live', 20), false, 'todavia no se rinde');
  breaker.failure('iframe:live', 20);
  assert.equal(breaker.shouldSkip('iframe:live', 30), true, 'ROOT_UNSTABLE');
  assert.equal(breaker.unstable(30)[0].key, 'iframe:live');
});

test('la raiz inestable vuelve a intentarse cuando pasa el descanso', () => {
  const breaker = errores.createCircuitBreaker({ threshold: 2, cooldownMs: 1000 });
  breaker.failure('iframe:x', 0);
  breaker.failure('iframe:x', 0);
  assert.equal(breaker.shouldSkip('iframe:x', 500), true);
  assert.equal(breaker.shouldSkip('iframe:x', 1500), false, 'segunda oportunidad');
});

test('J. una raiz inestable NO bloquea a las demas', () => {
  const breaker = errores.createCircuitBreaker({ threshold: 2, cooldownMs: 1000 });
  breaker.failure('iframe:roto', 0);
  breaker.failure('iframe:roto', 0);
  assert.equal(breaker.shouldSkip('iframe:roto', 100), true);
  assert.equal(breaker.shouldSkip('document:principal', 100), false);
  assert.equal(breaker.shouldSkip('shadow-root:bp-market', 100), false);
});

test('un exito devuelve la raiz a la normalidad', () => {
  const breaker = errores.createCircuitBreaker({ threshold: 2, cooldownMs: 10000 });
  breaker.failure('iframe:x', 0);
  breaker.success('iframe:x');
  breaker.failure('iframe:x', 10);
  assert.equal(breaker.shouldSkip('iframe:x', 20), false, 'la cuenta se reinicio');
});
