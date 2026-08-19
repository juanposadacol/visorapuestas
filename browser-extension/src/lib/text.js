/**
 * Normalizacion de texto para el diagnostico.
 *
 * Funciones puras y sin DOM, para poder probarlas con `node --test`.
 * Se normaliza la FORMA del texto (mayusculas, tildes, espacios, ordinales),
 * nunca su significado: si algo queda dudoso, quien decide es el clasificador
 * de mercados y su nivel de confianza.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { text: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /**
   * Quita tildes y marcas ordinales voladas.
   *
   * Se usa NFKD y no NFD porque los ordinales de las casas ("1.ª", "2.º")
   * llevan caracteres de compatibilidad que NFD deja intactos: NFKD los
   * convierte en la letra normal ("a", "o"), que es justo lo que hace falta
   * para comparar etiquetas.
   */
  function stripAccents(value) {
    if (!value) return '';
    return String(value)
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '');
  }

  /** Minusculas, sin tildes, espacios colapsados. */
  function normalize(value) {
    if (value === null || value === undefined) return '';
    return stripAccents(String(value))
      .toLowerCase()
      .replace(/\s+/g, ' ')
      .trim();
  }

  //: Ordinales escritos con palabra, solo cuando acompanan a un nombre de
  //: periodo. "cuarto" a secas es el sustantivo, no el ordinal 4.
  const WORD_ORDINALS = [
    [/\b(primer|primero|primera)\b/g, '1'],
    [/\b(segundo|segunda)\b/g, '2'],
    [/\b(tercer|tercero|tercera)\b/g, '3'],
    [/\b(cuarta)\b/g, '4'],
  ];

  const PERIOD_NOUNS = 'cuarto|cuartos|periodo|periodos|parcial|parciales|tiempo|mitad|mitades|parte|partes|quarter|half';

  /**
   * Unifica las variantes ordinales que usan las casas.
   *
   *   "3.er Cuarto"  -> "3 cuarto"
   *   "1.ª mitad"    -> "1 mitad"
   *   "2º periodo"   -> "2 periodo"
   *   "primer cuarto"-> "1 cuarto"
   *   "cuarto cuarto"-> "4 cuarto"   (el primero es ordinal, el segundo nombre)
   */
  function normalizeOrdinals(value) {
    let out = normalize(value);

    // "cuarto" seguido de un nombre de periodo es el ordinal 4.
    out = out.replace(new RegExp(`\\bcuarto\\s+(?=(?:${PERIOD_NOUNS})\\b)`, 'g'), '4 ');

    for (const [pattern, digit] of WORD_ORDINALS) {
      out = out.replace(pattern, digit);
    }

    // Marcas ordinales pegadas al digito: 1.er, 1er, 1ro, 1o, 1a, 1.a, 3.º
    out = out.replace(/\b(\d{1,2})\s*[.°ºªo]*\s*(?:er|ero|do|ro|to|ma|a|o)?\b(?=\s|$|-)/g, '$1');
    // Restos de puntuacion ordinal sueltos
    out = out.replace(/[°ºª]/g, ' ');
    return out.replace(/\s+/g, ' ').trim();
  }

  /** Convierte "1,85" en 1.85 y devuelve null si no es un numero limpio. */
  function toNumber(value) {
    if (value === null || value === undefined) return null;
    const cleaned = String(value).trim().replace(',', '.');
    if (!/^[+-]?\d+(\.\d+)?$/.test(cleaned)) return null;
    const parsed = Number(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }

  /** Cuenta los decimales tal y como venian escritos ("1.80" -> 2). */
  function decimalsOf(text) {
    const cleaned = String(text).replace(',', '.');
    const dot = cleaned.indexOf('.');
    return dot === -1 ? 0 : cleaned.length - dot - 1;
  }

  /** Recorta un texto largo para los informes, sin romper por la mitad. */
  function truncate(value, max = 120) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (text.length <= max) return text;
    return `${text.slice(0, max - 1)}…`;
  }

  return { stripAccents, normalize, normalizeOrdinals, toNumber, decimalsOf, truncate };
});
