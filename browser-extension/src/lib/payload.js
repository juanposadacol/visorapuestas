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

  /** Identificador del evento a partir de la URL, sin datos de la cuenta. */
  function eventIdFromUrl(url) {
    const texto = String(url || '');
    // BetPlay usa rutas con identificadores numericos largos del evento.
    const match = texto.match(/(?:event|evento|match|partido)[/-]?(\d{4,})/i) ||
                  texto.match(/\/(\d{6,})(?:[/?#]|$)/);
    if (match) return match[1];
    try {
      const parsed = new URL(texto);
      return `${parsed.pathname}`.replace(/\/+$/, '') || null;
    } catch (error) {
      return null;
    }
  }

  /**
   * Construye el payload. Devuelve { payload, rejected } donde `payload` es
   * null si no hay confianza suficiente, con el motivo en `rejected`.
   */
  function buildPayload(input) {
    const datos = input || {};
    const motivos = [];

    const wire = toWireMarket(datos.marketKey);
    if (!wire) motivos.push(`mercado no reconocido: ${datos.marketKey || '(ninguno)'}`);

    const confianza = Number(datos.confidence || 0);
    if (confianza < MIN_MARKET_CONFIDENCE) {
      motivos.push(`confianza del mercado ${confianza.toFixed(2)} < ${MIN_MARKET_CONFIDENCE}`);
    }

    const lineas = (datos.lines || []).filter(
      (l) => l && typeof l.line === 'number' && (l.overOdds != null || l.underOdds != null));
    if (!lineas.length) motivos.push('sin lineas con cuota');
    if (lineas.length > MAX_LINES) motivos.push(`demasiadas lineas: ${lineas.length}`);

    if (motivos.length) return { payload: null, rejected: motivos };

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
        visibleMarket: {
          ...wire,
          confidence: Number(confianza.toFixed(3)),
          rawTitle: String(datos.rawTitle || '').slice(0, 160),
          // Si la pagina no marca "Mas de"/"Menos de", el reparto OVER/UNDER
          // es posicional y no se puede garantizar. Se dice, no se disimula.
          sidesConfirmed: !!sides.both,
        },
        lines: lineas.slice(0, MAX_LINES).map((l) => ({
          line: Number(l.line),
          overOdds: l.overOdds == null ? null : Number(l.overOdds),
          underOdds: l.underOdds == null ? null : Number(l.underOdds),
        })),
        gameState: datos.gameState || null,
      },
      rejected: [],
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
    if (!market || typeof market !== 'object') {
      errores.push('falta visibleMarket');
    } else {
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

    if (!Array.isArray(p.lines) || !p.lines.length) {
      errores.push('sin lineas');
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

    return { valid: errores.length === 0, errors: errores };
  }

  /** Firma para no reenviar lo mismo una y otra vez. */
  function payloadSignature(payload) {
    if (!payload) return '';
    const market = payload.visibleMarket;
    const lineas = payload.lines
      .map((l) => `${l.line}|${l.overOdds ?? '-'}|${l.underOdds ?? '-'}`)
      .join(';');
    return `${payload.event.id || '-'}#${market.marketType}:${market.period ?? '-'}:` +
      `${market.half ?? '-'}#${lineas}`;
  }

  return { PROTOCOL_VERSION, MIN_MARKET_CONFIDENCE, MAX_LINES, WIRE_MARKET,
           toWireMarket, eventIdFromUrl, buildPayload, validatePayload, payloadSignature };
});
