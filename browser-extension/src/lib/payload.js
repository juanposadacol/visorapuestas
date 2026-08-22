/**
 * Construccion y validacion del payload que viaja a VisorApuestas.
 *
 * Este modulo es el CONTRATO entre la extension y la aplicacion Python. Las
 * mismas reglas se comprueban en los dos lados: aqui antes de enviar, y en
 * Python antes de aceptar. Si algo no cumple, no se envia; nunca se envia una
 * linea "por si acaso".
 *
 * Nombres del cable: se usan los mismos que el dominio Python (QUARTER_TOTAL,
 * HALF_TOTAL, GAME_TOTAL) en lugar de inventar otros. Traducir nombres entre
 * las dos mitades solo crea una capa mas que se puede desincronizar.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./lines.js') : root.VDIAG.lines
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { payload: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (linesLib) {
  'use strict';

  const PROTOCOL_VERSION = 1;

  //: Confianza minima del mercado para enviarlo. Por debajo, la aplicacion no
  //: recibe nada: preferimos que el radar diga "sin datos" a que muestre un
  //: mercado equivocado.
  const MIN_MARKET_CONFIDENCE = 0.9;
  const MAX_LINES = 40;
  const MARKET_SOURCES = ['CANONICAL_SECTION', 'TITLE_ONLY', 'SELECTED_BETS_COPY'];

  const WIRE_MARKET = {
    GAME_TOTAL: { marketType: 'GAME_TOTAL', period: null, half: null },
    FIRST_HALF_TOTAL: { marketType: 'HALF_TOTAL', period: null, half: 1 },
    SECOND_HALF_TOTAL: { marketType: 'HALF_TOTAL', period: null, half: 2 },
    Q1_TOTAL: { marketType: 'QUARTER_TOTAL', period: 1, half: null },
    Q2_TOTAL: { marketType: 'QUARTER_TOTAL', period: 2, half: null },
    Q3_TOTAL: { marketType: 'QUARTER_TOTAL', period: 3, half: null },
    Q4_TOTAL: { marketType: 'QUARTER_TOTAL', period: 4, half: null },
  };

  /** Traduce la clave interna de la extension al formato del cable. */
  function toWireMarket(key) {
    const wire = WIRE_MARKET[key];
    return wire ? { ...wire } : null;
  }

  /**
   * Identificador del evento a partir de la URL, sin datos de la cuenta.
   *
   * BetPlay usa el enrutado por HASH de Angular:
   *
   *     https://betplay.com.co/apuestas#event/live/123456789
   *
   * Ahi el identificador NO esta en `pathname`: esta detras de la almohadilla,
   * que para `new URL()` es un solo bloque opaco. Mirar solo el pathname
   * devolvia "/apuestas" para TODOS los partidos, asi que al cambiar de evento
   * la aplicacion no se enteraba y podia mezclar dos partidos distintos.
   *
   * Se busca primero en el hash, que es donde vive la ruta de verdad, y solo
   * despues en el resto de la URL.
   */
  function eventIdFromUrl(url) {
    const texto = String(url || '');
    const almohadilla = texto.indexOf('#');
    const hash = almohadilla === -1 ? '' : texto.slice(almohadilla + 1);
    const resto = almohadilla === -1 ? texto : texto.slice(0, almohadilla);

    //: "event/live/123456789", "evento-123456", "match/98765/mercados"
    const PORNOMBRE = /(?:event|evento|match|partido|game|juego)[/_-]?(?:live|envivo|en-vivo|directo|prematch|pre-match)?[/_-]?(\d{4,})/i;
    //: Un identificador largo suelto en la ruta.
    const SUELTO = /(?:^|[/_-])(\d{6,})(?:[/?#&]|$)/;

    for (const trozo of [hash, resto]) {
      if (!trozo) continue;
      const match = trozo.match(PORNOMBRE) || trozo.match(SUELTO);
      if (match) return match[1];
    }

    // Sin numero reconocible, la ruta del hash sigue distinguiendo un evento de
    // otro mejor que el pathname, que en Angular es siempre el mismo.
    const rutaHash = hash.split('?')[0].replace(/\/+$/, '');
    if (rutaHash) return rutaHash;
    try {
      const parsed = new URL(texto);
      return `${parsed.pathname}`.replace(/\/+$/, '') || null;
    } catch (error) {
      return null;
    }
  }

  /**
   * Construye una actualizacion tipada del mismo evento.
   *
   * Mercado y estado del partido son independientes: un mercado reconocido
   * puede viajar con `lines: []` (suspendido/sin oferta actual), y un
   * `gameState` puede viajar con `visibleMarket: null`. Solo se devuelve null
   * cuando no hay ninguna observacion util de ninguno de los dos ejes.
   */
  function buildPayload(input) {
    const datos = input || {};
    const motivos = [];

    const wire = toWireMarket(datos.marketKey);
    if (!wire && datos.marketKey) {
      motivos.push(`mercado no reconocido: ${datos.marketKey}`);
    }

    const confianza = Number(datos.confidence || 0);
    if (wire && confianza < MIN_MARKET_CONFIDENCE) {
      motivos.push(`confianza del mercado ${confianza.toFixed(2)} < ${MIN_MARKET_CONFIDENCE}`);
    }

    const lineas = (datos.lines || []).filter(
      (l) => l && typeof l.line === 'number' && (l.overOdds != null || l.underOdds != null));
    if (wire && !lineas.length) motivos.push('sin lineas actuales');
    if (lineas.length > MAX_LINES) motivos.push(`demasiadas lineas: ${lineas.length}`);

    const marketUsable = !!wire && confianza >= MIN_MARKET_CONFIDENCE &&
      lineas.length <= MAX_LINES;
    const marketObservations = [];
    for (const observado of datos.markets || []) {
      const marketWire = toWireMarket(observado.marketKey);
      const marketConfidence = Number(observado.confidence || 0);
      const marketLines = (observado.lines || []).filter(
        (l) => l && typeof l.line === 'number' && (l.overOdds != null || l.underOdds != null));
      if (!marketWire || marketConfidence < MIN_MARKET_CONFIDENCE ||
          marketLines.length > MAX_LINES) continue;
      marketObservations.push({
        ...marketWire,
        confidence: Number(marketConfidence.toFixed(3)),
        rawTitle: String(observado.rawTitle || '').slice(0, 160),
        sidesConfirmed: !!((observado.sideMarkers || {}).both),
        observedAt: new Date(observado.observedAt || datos.observedAt || Date.now()).toISOString(),
        section: observado.section == null ? null : String(observado.section).slice(0, 80),
        source: MARKET_SOURCES.includes(observado.source) ? observado.source : 'TITLE_ONLY',
        lines: marketLines.slice(0, MAX_LINES).map((l) => ({
          line: Number(l.line),
          overOdds: l.overOdds == null ? null : Number(l.overOdds),
          underOdds: l.underOdds == null ? null : Number(l.underOdds),
        })),
      });
    }

    const gameState = datos.gameState && typeof datos.gameState === 'object'
      ? datos.gameState : null;
    if (!marketUsable && !marketObservations.length && !gameState) {
      if (!motivos.length) motivos.push('sin estado del partido ni mercado identificado');
      return { payload: null, rejected: motivos };
    }

    const sides = datos.sideMarkers || {};
    return {
      payload: {
        protocol: PROTOCOL_VERSION,
        source: 'betplay',
        observedAt: new Date(datos.observedAt || Date.now()).toISOString(),
        event: {
          id: datos.eventId || null,
          name: datos.eventName || null,
        },
        visibleMarket: marketUsable ? {
          ...wire,
          confidence: Number(confianza.toFixed(3)),
          rawTitle: String(datos.rawTitle || '').slice(0, 160),
          // Si la pagina no marca "Mas de"/"Menos de", el reparto OVER/UNDER
          // es posicional y no se puede garantizar. Se dice, no se disimula.
          sidesConfirmed: !!sides.both,
        } : null,
        lines: (marketUsable ? lineas : []).slice(0, MAX_LINES).map((l) => ({
          line: Number(l.line),
          overOdds: l.overOdds == null ? null : Number(l.overOdds),
          underOdds: l.underOdds == null ? null : Number(l.underOdds),
        })),
        // Extension retrocompatible de protocol v1: los consumidores antiguos
        // siguen usando visibleMarket/lines; los nuevos renuevan cada clave.
        markets: marketObservations,
        gameState,
      },
      rejected: motivos,
    };
  }

  /**
   * Valida un payload ya construido. Es la misma comprobacion que hara Python;
   * tenerla aqui evita enviar basura y permite probar el contrato en los dos
   * lados con los mismos casos.
   */
  function validatePayload(payload) {
    const errores = [];
    const p = payload;
    if (!p || typeof p !== 'object') return { valid: false, errors: ['payload vacio'] };
    if (p.protocol !== PROTOCOL_VERSION) errores.push('protocolo desconocido');
    if (p.source !== 'betplay') errores.push('fuente desconocida');
    if (!p.observedAt || Number.isNaN(Date.parse(p.observedAt))) errores.push('observedAt invalido');

    const market = p.visibleMarket;
    if (market != null && typeof market !== 'object') {
      errores.push('visibleMarket invalido');
    } else if (market) {
      const tipos = ['GAME_TOTAL', 'HALF_TOTAL', 'QUARTER_TOTAL'];
      if (!tipos.includes(market.marketType)) errores.push('marketType desconocido');
      if (market.marketType === 'QUARTER_TOTAL' &&
          !(Number.isInteger(market.period) && market.period >= 1 && market.period <= 4)) {
        errores.push('period invalido para QUARTER_TOTAL');
      }
      if (market.marketType === 'HALF_TOTAL' && ![1, 2].includes(market.half)) {
        errores.push('half invalido para HALF_TOTAL');
      }
      if (!(typeof market.confidence === 'number' &&
            market.confidence >= MIN_MARKET_CONFIDENCE && market.confidence <= 1)) {
        errores.push('confianza insuficiente');
      }
    }

    if (!Array.isArray(p.lines)) {
      errores.push('lines no es una lista');
    } else if (p.lines.length > MAX_LINES) {
      errores.push('demasiadas lineas');
    } else {
      for (const linea of p.lines) {
        if (!(typeof linea.line === 'number' &&
              linea.line >= linesLib.MIN_LINE && linea.line <= linesLib.MAX_LINE)) {
          errores.push(`linea fuera de rango: ${linea.line}`);
          continue;
        }
        for (const lado of ['overOdds', 'underOdds']) {
          const cuota = linea[lado];
          if (cuota === null || cuota === undefined) continue;
          if (!(typeof cuota === 'number' &&
                cuota >= linesLib.MIN_ODDS && cuota <= linesLib.MAX_ODDS)) {
            errores.push(`cuota fuera de rango en ${linea.line}: ${cuota}`);
          }
        }
        if (linea.overOdds == null && linea.underOdds == null) {
          errores.push(`linea sin cuotas: ${linea.line}`);
        }
      }
    }
    if (Array.isArray(p.lines) && p.lines.length && !market) {
      errores.push('lineas sin visibleMarket');
    }

    if (p.markets !== undefined) {
      if (!Array.isArray(p.markets)) {
        errores.push('markets no es una lista');
      } else {
        const vistos = new Set();
        for (let i = 0; i < p.markets.length; i += 1) {
          const observado = p.markets[i];
          if (!observado || typeof observado !== 'object') {
            errores.push(`markets[${i}] invalido`);
            continue;
          }
          const permitido = new Set(['marketType', 'period', 'half', 'confidence', 'rawTitle',
            'sidesConfirmed', 'observedAt', 'section', 'source', 'lines']);
          const sobran = Object.keys(observado).filter((k) => !permitido.has(k));
          if (sobran.length) errores.push(`campos desconocidos en markets[${i}]: ${sobran.join(',')}`);
          if (!MARKET_SOURCES.includes(observado.source)) {
            errores.push(`markets[${i}].source invalido`);
          }
          if (observado.section !== null && observado.section !== undefined &&
              typeof observado.section !== 'string') errores.push(`markets[${i}].section invalido`);
          const key = `${observado.marketType}:${observado.period ?? '-'}:${observado.half ?? '-'}`;
          if (vistos.has(key)) errores.push(`market duplicado en markets: ${key}`);
          vistos.add(key);
          const sintentico = {
            protocol: PROTOCOL_VERSION, source: 'betplay', observedAt: observado.observedAt,
            event: p.event, visibleMarket: {
              marketType: observado.marketType, period: observado.period, half: observado.half,
              confidence: observado.confidence, rawTitle: observado.rawTitle,
              sidesConfirmed: observado.sidesConfirmed,
            },
            lines: observado.lines, gameState: null,
          };
          for (const error of validatePayload(sintentico).errors) {
            errores.push(`markets[${i}]: ${error}`);
          }
        }
      }
    }

    const gameState = p.gameState;
    if (gameState != null && typeof gameState !== 'object') {
      errores.push('gameState invalido');
    } else if (gameState) {
      for (const key of ['teamA', 'teamB']) {
        const team = gameState[key];
        // Se acepta texto por compatibilidad con versiones anteriores de la
        // extension; la version actual publica el objeto completo.
        if (team == null || typeof team === 'string') continue;
        if (typeof team !== 'object') {
          errores.push(`${key} invalido`);
          continue;
        }
        if (typeof team.name !== 'string' || !team.name.trim() || team.name.length > 60) {
          errores.push(`${key}.name invalido`);
        }
        if (!Number.isInteger(team.total) || team.total < 0 || team.total > 300) {
          errores.push(`${key}.total invalido`);
        }
        if (!team.periods || typeof team.periods !== 'object' || Array.isArray(team.periods)) {
          errores.push(`${key}.periods invalido`);
          continue;
        }
        for (const [period, value] of Object.entries(team.periods)) {
          if (!/^(?:Q[1-4]|OT[1-9]\d*)$/.test(period)) {
            errores.push(`${key}.periods.${period} invalido`);
          }
          if (value !== null &&
              (!Number.isInteger(value) || value < 0 || value > 300)) {
            errores.push(`${key}.periods.${period} invalido`);
          }
        }
      }
    }
    if (!market && !(Array.isArray(p.markets) && p.markets.length) && !gameState) {
      errores.push('actualizacion sin mercado ni gameState');
    }

    return { valid: errores.length === 0, errors: errores };
  }

  /** Firma para no reenviar lo mismo una y otra vez. */
  function payloadSignature(payload) {
    if (!payload) return '';
    const market = payload.visibleMarket;
    const lineas = (payload.lines || [])
      .map((l) => `${l.line}|${l.overOdds ?? '-'}|${l.underOdds ?? '-'}`)
      .join(';');
    const state = payload.gameState ? JSON.stringify(payload.gameState) : '-';
    const marketKey = market
      ? `${market.marketType}:${market.period ?? '-'}:${market.half ?? '-'}` : '-';
    const todos = (payload.markets || []).map((m) =>
      `${m.marketType}:${m.period ?? '-'}:${m.half ?? '-'}@${(m.lines || [])
        .map((l) => `${l.line}|${l.overOdds ?? '-'}|${l.underOdds ?? '-'}`).join(';')}`)
      .join('||');
    return `${payload.event.id || '-'}#${marketKey}#${lineas}#${todos}#${state}`;
  }

  return { PROTOCOL_VERSION, MIN_MARKET_CONFIDENCE, MAX_LINES, MARKET_SOURCES, WIRE_MARKET,
           toWireMarket, eventIdFromUrl, buildPayload, validatePayload, payloadSignature };
});
