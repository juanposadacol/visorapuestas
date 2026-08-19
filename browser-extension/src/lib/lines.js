/**
 * Deteccion de lineas y cuotas dentro del texto de un bloque.
 *
 * En esta fase el objetivo es DESCUBRIR como estructura BetPlay sus datos, no
 * disimular la incertidumbre. Por eso el resultado siempre incluye el texto
 * bruto y cuantos numeros candidatos se vieron, aunque no se hayan podido
 * agrupar en lineas.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { lines: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text) {
  'use strict';

  //: Una cuota decimal razonable. Fuera de aqui, no es una cuota.
  const MIN_ODDS = 1.01;
  const MAX_ODDS = 100.0;
  //: Un total de baloncesto no baja de aqui ni en un cuarto suelto.
  const MIN_LINE = 15.0;
  const MAX_LINE = 400.0;

  const OVER_WORDS = ['over', 'mas de', 'mas', 'alta', 'arriba', 'o', '+'];
  const UNDER_WORDS = ['under', 'menos de', 'menos', 'baja', 'abajo', 'u', '-'];

  const NUMBER_TOKEN = /\d+(?:[.,]\d+)?/g;

  function isOddsShaped(value, decimals) {
    return decimals >= 2 && value >= MIN_ODDS && value <= MAX_ODDS;
  }

  function isLineShaped(value, decimals) {
    if (value < MIN_LINE || value > MAX_LINE) return false;
    return decimals === 0 || decimals === 1;
  }

  /** Extrae los numeros de una fila conservando la pista OVER/UNDER previa. */
  function tokenize(row) {
    const normalized = text.normalizeOrdinals(row);
    const tokens = [];
    let cursor = 0;
    let match;
    NUMBER_TOKEN.lastIndex = 0;
    while ((match = NUMBER_TOKEN.exec(normalized)) !== null) {
      const prefix = normalized.slice(cursor, match.index);
      cursor = NUMBER_TOKEN.lastIndex;
      let hint = '';
      const words = prefix.split(/[^a-z+-]+/).filter(Boolean).reverse();
      for (const word of words) {
        if (UNDER_WORDS.includes(word)) { hint = 'under'; break; }
        if (OVER_WORDS.includes(word)) { hint = 'over'; break; }
      }
      // Una fila como "Menos de 153.5  1.95" solo lleva la palabra al
      // principio: los numeros posteriores heredan la pista.
      if (!hint && tokens.length) hint = tokens[tokens.length - 1].hint;
      const value = text.toNumber(match[0]);
      if (value === null) continue;
      tokens.push({ raw: match[0], value, decimals: text.decimalsOf(match[0]), hint });
    }
    return tokens;
  }

  /**
   * Agrupa lineas y cuotas de un texto con varias filas.
   * Devuelve { lines, rawCandidates, unassigned }.
   */
  function parseLines(rawText) {
    const rows = String(rawText ?? '').split('\n');
    const groups = [];
    let current = null;
    let rawCandidates = 0;
    let unassigned = 0;

    for (const row of rows) {
      for (const token of tokenize(row)) {
        rawCandidates += 1;
        if (isLineShaped(token.value, token.decimals) && !isOddsShaped(token.value, token.decimals)) {
          // La pista viaja con el grupo: en el DOM, "Menos de 140.5" y "2.85"
          // suelen ser nodos distintos, asi que la cuota llega sin palabra y
          // solo la cabecera de su linea sabe de que lado es.
          current = { line: token.value, overOdds: null, underOdds: null,
                      raw: row.trim(), hint: token.hint };
          groups.push(current);
        } else if (isOddsShaped(token.value, token.decimals)) {
          if (!current) { unassigned += 1; continue; }
          const hint = token.hint || current.hint;
          if (hint === 'under' && current.underOdds === null) current.underOdds = token.value;
          else if (hint === 'over' && current.overOdds === null) current.overOdds = token.value;
          else if (current.overOdds === null) current.overOdds = token.value;
          else if (current.underOdds === null) current.underOdds = token.value;
          else unassigned += 1;
        } else {
          unassigned += 1;
        }
      }
    }

    return { lines: groups, rawCandidates, unassigned };
  }

  return { MIN_ODDS, MAX_ODDS, MIN_LINE, MAX_LINE, tokenize, parseLines, isOddsShaped, isLineShaped };
});
