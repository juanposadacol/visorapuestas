/**
 * Identificacion del mercado a partir del texto de una cabecera.
 *
 * Regla que hereda del resto del proyecto: nada dudoso se clasifica en
 * silencio. Si la confianza no llega al umbral, la clave es UNKNOWN y el
 * candidato queda registrado aparte para poder revisarlo en el diagnostico.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { markets: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text) {
  'use strict';

  const KEYS = {
    GAME: 'GAME_TOTAL',
    H1: 'FIRST_HALF_TOTAL',
    H2: 'SECOND_HALF_TOTAL',
    Q1: 'Q1_TOTAL',
    Q2: 'Q2_TOTAL',
    Q3: 'Q3_TOTAL',
    Q4: 'Q4_TOTAL',
    UNKNOWN: 'UNKNOWN',
  };

  const LABELS = {
    GAME_TOTAL: 'Partido',
    FIRST_HALF_TOTAL: '1.a mitad',
    SECOND_HALF_TOTAL: '2.a mitad',
    Q1_TOTAL: 'Q1',
    Q2_TOTAL: 'Q2',
    Q3_TOTAL: 'Q3',
    Q4_TOTAL: 'Q4',
    UNKNOWN: 'Desconocido',
  };

  //: Confianza minima para atribuir una clave. Por debajo, UNKNOWN.
  const CONFIDENCE_THRESHOLD = 0.7;

  const TOTAL_WORDS = ['total de puntos', 'total puntos', 'totales', 'total'];
  //: Marcas de un total POR EQUIPO. Es otro mercado: sus lineas no son el
  //: total del partido y confundirlos daria numeros sin sentido.
  const TEAM_TOTAL_WORDS = ['equipo', 'local', 'visitante', 'casa', 'fuera',
                            'jugador', 'team'];
  //: Mercados que tambien llevan numeros pero no son totales.
  const OTHER_MARKET_WORDS = ['handicap', 'handicap asiatico', 'ganador', 'ganara',
                              'linea de dinero', 'moneyline', 'diferencia',
                              'margen', 'primer', 'ambos'];
  const GAME_WORDS = ['partido', 'encuentro', 'juego completo', 'tiempo reglamentario', 'match'];
  const QUARTER_PATTERNS = [
    /\bq\s*([1-4])\b/,
    /\b([1-4])\s*q\b/,
    /\b([1-4])\s+(?:cuarto|periodo|parcial|quarter)\b/,
    /\b(?:cuarto|periodo|parcial|quarter)\s+([1-4])\b/,
  ];
  const HALF_PATTERNS = [
    /\b([12])\s+(?:mitad|parte|tiempo|half)\b/,
    /\b(?:mitad|parte|tiempo|half)\s+([12])\b/,
  ];

  function hasAny(haystack, words) {
    return words.some((word) => haystack.includes(word));
  }

  /**
   * Devuelve { key, confidence, normalized, isTotal, candidate, reasons }.
   *
   * `candidate` guarda la clave que se sospechaba cuando la confianza no
   * alcanza el umbral: es informacion de diagnostico, no una clasificacion.
   */
  function identifyMarket(rawText) {
    const normalized = text.normalizeOrdinals(rawText);
    const reasons = [];
    if (!normalized) {
      return { key: KEYS.UNKNOWN, confidence: 0, normalized: '', isTotal: false,
               candidate: null, reasons: ['sin texto'] };
    }

    const isTotal = hasAny(normalized, TOTAL_WORDS);
    if (isTotal) reasons.push('menciona total de puntos');

    // Un total POR EQUIPO o un handicap no son el total del partido. Se
    // descartan de forma explicita, no por casualidad de la puntuacion.
    if (hasAny(normalized, TEAM_TOTAL_WORDS)) {
      return { key: KEYS.UNKNOWN, confidence: 0, normalized, isTotal,
               candidate: null, reasons: [...reasons, 'parece un total por equipo'] };
    }
    if (hasAny(normalized, OTHER_MARKET_WORDS)) {
      return { key: KEYS.UNKNOWN, confidence: 0, normalized, isTotal,
               candidate: null, reasons: [...reasons, 'parece otro mercado, no un total'] };
    }

    // Banderas explicitas. Deducir la confianza buscando subcadenas dentro de
    // los motivos era fragil: "total sin periodo explicito" contiene
    // "explicit" y disparaba la confianza maxima por accidente.
    let candidate = null;
    let explicitPeriod = false;   // cuarto o mitad indicados con numero
    let explicitGame = false;     // se nombra el partido completo
    let ambiguous = false;

    for (const pattern of QUARTER_PATTERNS) {
      const match = normalized.match(pattern);
      if (match) {
        candidate = KEYS[`Q${match[1]}`];
        explicitPeriod = true;
        reasons.push(`cuarto ${match[1]} indicado`);
        break;
      }
    }

    if (!candidate) {
      for (const pattern of HALF_PATTERNS) {
        const match = normalized.match(pattern);
        if (match) {
          candidate = match[1] === '1' ? KEYS.H1 : KEYS.H2;
          explicitPeriod = true;
          reasons.push(`mitad ${match[1]} indicada`);
          break;
        }
      }
    }

    if (!candidate && normalized.includes('descanso')) {
      // "Descanso" suele referirse a la primera mitad, pero tambien puede ser
      // el mercado de resultado al descanso: no basta por si solo.
      candidate = KEYS.H1;
      ambiguous = true;
      reasons.push('menciona descanso, que es ambiguo');
    }

    if (!candidate && hasAny(normalized, GAME_WORDS)) {
      candidate = KEYS.GAME;
      explicitGame = true;
      reasons.push('nombra el partido completo');
    }

    if (!candidate && isTotal) {
      // "Total de puntos" a secas suele ser el del partido, pero sin periodo
      // indicado no hay confianza suficiente para afirmarlo.
      candidate = KEYS.GAME;
      reasons.push('total sin periodo indicado');
    }

    let confidence = 0;
    if (candidate) {
      if (ambiguous) confidence = 0.4;
      else if (explicitPeriod && isTotal) confidence = 0.95;
      else if (explicitGame && isTotal) confidence = 0.9;
      else if (explicitPeriod || explicitGame) confidence = 0.55;
      else confidence = 0.5;
    }

    const key = confidence >= CONFIDENCE_THRESHOLD ? candidate : KEYS.UNKNOWN;
    return { key, confidence, normalized, isTotal, candidate, reasons };
  }

  function labelFor(key) {
    return LABELS[key] || key;
  }

  /** Orden estable de presentacion: partido, mitades y luego cuartos. */
  function sortKey(key) {
    const order = ['GAME_TOTAL', 'FIRST_HALF_TOTAL', 'SECOND_HALF_TOTAL',
                   'Q1_TOTAL', 'Q2_TOTAL', 'Q3_TOTAL', 'Q4_TOTAL', 'UNKNOWN'];
    const index = order.indexOf(key);
    return index === -1 ? order.length : index;
  }

  return { KEYS, LABELS, CONFIDENCE_THRESHOLD, identifyMarket, labelFor, sortKey };
});
