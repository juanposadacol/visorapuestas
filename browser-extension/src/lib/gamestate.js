/**
 * Descubrimiento del marcador, el cuarto y el reloj en el DOM.
 *
 * Aqui hay mas riesgo que en el mercado: una pagina de deportes esta llena de
 * numeros que se parecen a un marcador. Por eso:
 *
 * * se recogen TODOS los candidatos con su confianza, no se elige el primero;
 * * si hay empate entre candidatos distintos, no se elige ninguno;
 * * se aplican las validaciones acordadas: el marcador no baja, el reloj tiene
 *   forma MM:SS y baja, y el cuarto va de 1 a 4;
 * * si no hay confianza suficiente, no se envia nada y la aplicacion usara OCR.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text,
    typeof require === 'function' ? require('./markets.js') : root.VDIAG.markets
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { gamestate: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text, markets) {
  'use strict';

  const CLOCK_RE = /^(\d{1,2}):([0-5]\d)$/;
  const MAX_SCORE = 250;
  //: Un marcador de baloncesto por debajo de esto al principio es normal, pero
  //: un numero suelto tambien: por eso el marcador exige un PAR cercano.
  const MAX_PERIOD = 4;

  /** Recorrido con la cadena de padres, igual que el resto de modulos. */
  function walk(node, adapter, visit, chain) {
    const padres = chain || [];
    visit(node, padres);
    for (const hijo of adapter.children(node)) walk(hijo, adapter, visit, [node, ...padres]);
  }

  function leaves(root, adapter) {
    const hojas = [];
    walk(root, adapter, (node, chain) => {
      if (adapter.children(node).length === 0) {
        const valor = (adapter.text(node) || '').trim();
        if (valor) hojas.push({ node, chain, text: valor });
      }
    });
    return hojas;
  }

  // ------------------------------------------------------------------ reloj
  /** Candidatos a reloj: hojas con forma MM:SS y un tiempo verosimil. */
  function findClockCandidates(root, adapter) {
    const candidatos = [];
    for (const hoja of leaves(root, adapter)) {
      const match = hoja.text.match(CLOCK_RE);
      if (!match) continue;
      const minutos = Number(match[1]);
      const segundos = Number(match[2]);
      // Un cuarto no dura mas de 12 minutos en ninguna competicion habitual.
      if (minutos > 12) continue;
      candidatos.push({
        node: hoja.node,
        raw: hoja.text,
        value: `${String(minutos).padStart(2, '0')}:${match[2]}`,
        seconds: minutos * 60 + segundos,
        confidence: minutos <= 12 ? 0.8 : 0.4,
      });
    }
    return candidatos;
  }

  // ----------------------------------------------------------------- cuarto
  /** Candidatos a cuarto, reutilizando el reconocedor de mercados. */
  function findPeriodCandidates(root, adapter) {
    const candidatos = [];
    for (const hoja of leaves(root, adapter)) {
      if (hoja.text.length > 24) continue;
      const normalizado = text.normalizeOrdinals(hoja.text);
      let periodo = null;
      const directo = normalizado.match(/^q\s*([1-4])$/) ||
                      normalizado.match(/^([1-4])\s*q$/) ||
                      normalizado.match(/\b([1-4])\s+(?:cuarto|periodo|parcial|quarter)\b/) ||
                      normalizado.match(/\b(?:cuarto|periodo|parcial|quarter)\s+([1-4])\b/);
      if (directo) periodo = Number(directo[1]);
      if (periodo === null || periodo < 1 || periodo > MAX_PERIOD) continue;
      candidatos.push({
        node: hoja.node, raw: hoja.text, value: periodo,
        // "Q3" a secas es mas fiable que un texto largo que lo contenga.
        confidence: /^q?\s*[1-4]\s*q?$/.test(normalizado) ? 0.8 : 0.75,
      });
    }
    return candidatos;
  }

  // --------------------------------------------------------------- marcador
  /**
   * Candidatos a marcador: PAREJAS de enteros que cuelgan de un mismo
   * contenedor cercano. Un numero suelto nunca se toma por un marcador.
   */
  function findScoreCandidates(root, adapter) {
    const hojas = leaves(root, adapter);
    const numeros = [];
    for (const hoja of hojas) {
      if (!/^\d{1,3}$/.test(hoja.text)) continue;
      const valor = Number(hoja.text);
      if (valor > MAX_SCORE) continue;
      numeros.push({ ...hoja, value: valor });
    }

    const candidatos = [];
    for (let i = 0; i < numeros.length - 1; i += 1) {
      const a = numeros[i];
      const b = numeros[i + 1];
      // Deben compartir un ancestro cercano: si no, son numeros sin relacion.
      const cercania = sharedAncestorDepth(a, b);
      if (cercania === null || cercania > 3) continue;
      candidatos.push({
        nodes: [a.node, b.node],
        raw: `${a.text}-${b.text}`,
        value: { scoreA: a.value, scoreB: b.value },
        confidence: cercania <= 2 ? 0.75 : 0.6,
      });
    }
    return candidatos;
  }

  function sharedAncestorDepth(a, b) {
    for (let i = 0; i < a.chain.length && i < 4; i += 1) {
      const indice = b.chain.indexOf(a.chain[i]);
      if (indice !== -1 && indice < 4) return Math.max(i, indice);
    }
    return null;
  }

  // ------------------------------------------------------------- validacion
  /**
   * Elige entre candidatos aplicando las validaciones y la memoria del ciclo
   * anterior. Devuelve { value, confidence, reason } y `value` null si no hay
   * una respuesta clara.
   */
  function pickBest(candidatos, previous, validate) {
    if (!candidatos.length) return { value: null, confidence: 0, reason: 'sin candidatos' };

    const validos = candidatos.filter((c) => validate(c, previous));
    if (!validos.length) return { value: null, confidence: 0, reason: 'ningun candidato valido' };

    validos.sort((a, b) => b.confidence - a.confidence);
    const mejor = validos[0];
    const empatados = validos.filter(
      (c) => Math.abs(c.confidence - mejor.confidence) < 1e-9 &&
             JSON.stringify(c.value) !== JSON.stringify(mejor.value));
    if (empatados.length) {
      // Varios candidatos igual de plausibles y distintos: no se elige a dedo.
      return { value: null, confidence: 0, reason: 'candidatos ambiguos',
               ambiguous: [mejor, ...empatados].map((c) => c.raw) };
    }
    return { value: mejor.value, confidence: mejor.confidence, reason: '', raw: mejor.raw };
  }

  function clockValidator(candidato, previous) {
    if (!previous || previous.seconds === undefined || previous.seconds === null) return true;
    // El reloj baja o se para. Solo puede subir al empezar un cuarto nuevo.
    if (candidato.seconds <= previous.seconds) return true;
    return candidato.seconds >= 9 * 60;    // reinicio verosimil de cuarto
  }

  function periodValidator(candidato, previous) {
    if (candidato.value < 1 || candidato.value > MAX_PERIOD) return false;
    if (previous === null || previous === undefined) return true;
    return candidato.value >= previous;    // el cuarto no retrocede
  }

  function scoreValidator(candidato, previous) {
    const { scoreA, scoreB } = candidato.value;
    if (scoreA > MAX_SCORE || scoreB > MAX_SCORE) return false;
    if (!previous) return true;
    // El marcador normalmente no baja.
    return scoreA >= previous.scoreA && scoreB >= previous.scoreB;
  }

  /**
   * Estado del partido segun el DOM, o null en cada campo que no se pueda
   * afirmar. Nunca se rellena a medias con suposiciones.
   */
  function extractGameState(root, adapter, previous) {
    const anterior = previous || {};
    const reloj = pickBest(findClockCandidates(root, adapter), anterior.clock, clockValidator);
    const cuarto = pickBest(findPeriodCandidates(root, adapter),
                            anterior.period ? anterior.period.value : null, periodValidator);
    const marcador = pickBest(findScoreCandidates(root, adapter),
                              anterior.score ? anterior.score.value : null, scoreValidator);

    const estado = {};
    if (reloj.value) estado.clock = reloj.value;
    if (cuarto.value) estado.period = cuarto.value;
    if (marcador.value) {
      estado.scoreA = marcador.value.scoreA;
      estado.scoreB = marcador.value.scoreB;
    }

    return {
      gameState: Object.keys(estado).length ? estado : null,
      diagnostics: { clock: reloj, period: cuarto, score: marcador },
      memory: {
        clock: reloj.value ? { seconds: secondsOf(reloj.value), value: reloj.value } : anterior.clock,
        period: cuarto.value ? { value: cuarto.value } : anterior.period,
        score: marcador.value ? { value: marcador.value } : anterior.score,
      },
    };
  }

  function secondsOf(reloj) {
    const match = String(reloj).match(CLOCK_RE);
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
  }

  return { CLOCK_RE, findClockCandidates, findPeriodCandidates, findScoreCandidates,
           pickBest, clockValidator, periodValidator, scoreValidator, extractGameState };
});
