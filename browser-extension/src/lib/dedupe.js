/**
 * Deduplicacion de candidatos.
 *
 * Una misma linea aparece varias veces en el DOM por versiones movil/escritorio,
 * nodos de accesibilidad, animaciones o componentes clonados. Se deduplica para
 * el informe legible, pero SIEMPRE se conserva el recuento bruto: en modo
 * diagnostico interesa saber cuantos candidatos habia antes de agrupar.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { dedupe: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * Funde las lecturas de una misma linea, completando huecos.
   * Devuelve { lines, rawCount, duplicates }.
   */
  function dedupeLines(lines) {
    const byValue = new Map();
    let duplicates = 0;
    for (const line of lines || []) {
      if (line == null || typeof line.line !== 'number') continue;
      const clave = line.line.toFixed(2);
      const previa = byValue.get(clave);
      if (!previa) {
        byValue.set(clave, { ...line });
        continue;
      }
      duplicates += 1;
      // Se completa lo que falte sin pisar lo ya leido.
      if (previa.overOdds == null) previa.overOdds = line.overOdds;
      if (previa.underOdds == null) previa.underOdds = line.underOdds;
    }
    const out = Array.from(byValue.values()).sort((a, b) => a.line - b.line);
    return { lines: out, rawCount: (lines || []).length, duplicates };
  }

  /** Firma estable de un conjunto de lineas, para detectar cambios reales. */
  function linesSignature(lines) {
    return (lines || [])
      .slice()
      .sort((a, b) => a.line - b.line)
      .map((l) => `${l.line}|${l.overOdds ?? '-'}|${l.underOdds ?? '-'}`)
      .join(';');
  }

  /** Diferencia entre dos conjuntos de lineas, para el historial. */
  function diffLines(before, after) {
    const antes = new Map((before || []).map((l) => [l.line, l]));
    const despues = new Map((after || []).map((l) => [l.line, l]));
    const added = [];
    const removed = [];
    const changed = [];
    for (const [value, line] of despues) {
      if (!antes.has(value)) { added.push(line); continue; }
      const previa = antes.get(value);
      if (previa.overOdds !== line.overOdds || previa.underOdds !== line.underOdds) {
        changed.push({ line: value, from: previa, to: line });
      }
    }
    for (const [value, line] of antes) {
      if (!despues.has(value)) removed.push(line);
    }
    return { added, removed, changed, hasChanges: !!(added.length || removed.length || changed.length) };
  }

  return { dedupeLines, linesSignature, diffLines };
});
