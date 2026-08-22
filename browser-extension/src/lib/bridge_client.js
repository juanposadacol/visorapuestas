/**
 * Politica de envio al puente local. Logica pura, sin red ni APIs de Chrome.
 *
 * Por que existe un service worker y no se envia desde el content script:
 *
 *   Un `fetch` hecho desde el content script sale con el origen de la PAGINA
 *   (https://betplay.com.co). Para aceptarlo, el servidor local tendria que
 *   abrir la puerta a ese origen, y entonces cualquier script de esa web
 *   podria hablar con el puente. Desde el service worker el origen es
 *   `chrome-extension://<id>`, que es justo lo que el servidor acepta, asi que
 *   la puerta queda cerrada para las paginas.
 *
 *   Ademas centraliza en un solo sitio la reconexion y el latido, en vez de
 *   tener una copia por pestana abierta.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./payload.js') : root.VDIAG.payload
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { bridgeClient: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (payloadLib) {
  'use strict';

  const DEFAULTS = {
    //: Tope de envios utiles por segundo. 250 ms = 4/s como maximo.
    minIntervalMs: 250,
    //: Latido: se manda algo aunque nada cambie, para distinguir "la casa no
    //: movio nada" de "se corto la conexion".
    heartbeatMs: 1000,
    //: Reintento cuando la aplicacion no esta abierta.
    retryBaseMs: 2000,
    retryMaxMs: 15000,
    //: Cada cuanto se vuelve a comprobar /health estando ya conectados. Es lo
    //: que permite darse cuenta de que la aplicacion se cerro aunque no haya
    //: ningun mercado que enviar.
    probeIntervalMs: 5000,
    //: Sin contacto correcto durante este tiempo, el enlace se declara STALE:
    //: se creia conectado pero hace demasiado que no se confirma.
    staleAfterMs: 12000,
  };

  /**
   * Estado del ENLACE con la aplicacion local. Habla solo de la conexion.
   *
   *   DISCONNECTED  la aplicacion no responde
   *   CONNECTING    se esta comprobando ahora mismo
   *   CONNECTED     /health respondio bien
   *   STALE         respondio bien, pero hace demasiado que no se confirma
   */
  const LINK = {
    DISCONNECTED: 'DISCONNECTED',
    CONNECTING: 'CONNECTING',
    CONNECTED: 'CONNECTED',
    STALE: 'STALE',
  };

  /**
   * Estado del MERCADO. Habla solo de los datos, nunca de la conexion.
   *
   *   VALID         hay un mercado con lineas y cuotas listo para enviar
   *   NONE          todavia no se ha reconocido ningun mercado
   *   UNDER_REVIEW  hay lectura, pero algo no cuadra y no se publica
   *   REJECTED      habia payload pero no cumple el contrato
   *
   * Son EJES INDEPENDIENTES. "No hay mercado" no es "la aplicacion esta
   * cerrada": mezclarlos era justo el fallo que se veia en el popup, que decia
   * DESCONECTADA mientras /health respondia perfectamente.
   */
  const MARKET = {
    VALID: 'VALID',
    NO_LINES: 'NO_LINES',
    STATE_ONLY: 'STATE_ONLY',
    NONE: 'NONE',
    UNDER_REVIEW: 'UNDER_REVIEW',
    REJECTED: 'REJECTED',
  };

  /**
   * Decide si toca enviar.
   *
   * Devuelve { send, reason } con reason en:
   *   'change'     el mercado o las cuotas cambiaron
   *   'heartbeat'  no cambio nada pero toca dar senales de vida
   *   'throttled'  cambio, pero es demasiado pronto
   *   'nothing'    no hay nada que enviar
   */
  function decideSend(input, options) {
    const cfg = { ...DEFAULTS, ...(options || {}) };
    const { payload, lastSignature, lastSentAt, now } = input;
    if (!payload) return { send: false, reason: 'nothing' };

    const firma = payloadLib.payloadSignature(payload);
    const desdeElUltimo = lastSentAt ? now - lastSentAt : Infinity;

    if (firma !== lastSignature) {
      if (desdeElUltimo < cfg.minIntervalMs) return { send: false, reason: 'throttled', signature: firma };
      return { send: true, reason: 'change', signature: firma };
    }
    if (desdeElUltimo >= cfg.heartbeatMs) {
      return { send: true, reason: 'heartbeat', signature: firma };
    }
    return { send: false, reason: 'nothing', signature: firma };
  }

  /**
   * Espera antes del siguiente intento cuando la aplicacion no responde.
   * Crece pero se acota: reintentar cada 15 s es suficiente para que abrir
   * VisorApuestas reconecte solo, sin llenar la consola de errores.
   */
  function retryDelay(attempt, options) {
    const cfg = { ...DEFAULTS, ...(options || {}) };
    const intento = Math.max(0, Number(attempt) || 0);
    return Math.min(cfg.retryBaseMs * Math.pow(2, intento), cfg.retryMaxMs);
  }

  /**
   * Estado del enlace a partir de lo ocurrido, sin efectos secundarios.
   *
   * `result` puede ser:
   *   'ok'        /health respondio
   *   'probing'   se acaba de lanzar la comprobacion
   *   otra cadena el motivo del fallo
   */
  function nextLinkState(current, result) {
    if (result === 'ok') return { state: LINK.CONNECTED, attempt: 0, error: '' };
    if (result === 'probing') {
      // Estando conectados no se parpadea a CONNECTING por cada sondeo: eso
      // haria bailar el panel sin que pase nada.
      if (current && current.state === LINK.CONNECTED) return { ...current };
      return {
        state: LINK.CONNECTING,
        attempt: (current && current.attempt) || 0,
        error: (current && current.error) || '',
      };
    }
    const fallaba = current &&
      (current.state === LINK.DISCONNECTED || current.state === LINK.CONNECTING);
    return {
      state: LINK.DISCONNECTED,
      attempt: (fallaba ? current.attempt : 0) + 1,
      error: typeof result === 'string' ? result : 'sin conexion',
    };
  }

  /**
   * Estado del enlace tal y como debe MOSTRARSE, teniendo en cuenta cuanto
   * hace del ultimo contacto correcto.
   */
  function linkStateFor(link, lastOkAt, now, options) {
    const cfg = { ...DEFAULTS, ...(options || {}) };
    const estado = (link && link.state) || LINK.DISCONNECTED;
    if (estado !== LINK.CONNECTED) return estado;
    const desde = Number(lastOkAt) || 0;
    if (!desde) return LINK.CONNECTED;
    return (now - desde) >= cfg.staleAfterMs ? LINK.STALE : LINK.CONNECTED;
  }

  /**
   * Toca comprobar /health?
   *
   * ESTA DECISION NO MIRA EL PAYLOAD. Antes el sondeo colgaba de que hubiera
   * un mercado que enviar, asi que sin mercado el enlace se quedaba
   * DESCONECTADO para siempre aunque la aplicacion estuviera abierta.
   */
  function shouldProbe(input, options) {
    const cfg = { ...DEFAULTS, ...(options || {}) };
    const { link, now } = input;
    const estado = (link && link.state) || LINK.DISCONNECTED;
    if (input.probeInFlight) return false;
    if (estado === LINK.CONNECTED) {
      const desde = Number(input.lastOkAt) || 0;
      return (now - desde) >= cfg.probeIntervalMs;
    }
    return now >= (Number(input.nextProbeAt) || 0);
  }

  /**
   * Estado del mercado, independiente del enlace.
   *
   * `underReview` lo pone quien lee el DOM cuando tiene una lectura que no se
   * atreve a publicar (por ejemplo un marcador que retrocede).
   */
  function marketState(input) {
    const datos = input || {};
    if (datos.underReview) return MARKET.UNDER_REVIEW;
    if (!datos.payload) return MARKET.NONE;
    if (datos.validation && datos.validation.valid === false) return MARKET.REJECTED;
    const multiples = Array.isArray(datos.payload.markets) ? datos.payload.markets : [];
    if (multiples.some((m) => (m.lines || []).length)) return MARKET.VALID;
    if (multiples.length) return MARKET.NO_LINES;
    if (datos.payload.visibleMarket && (datos.payload.lines || []).length) return MARKET.VALID;
    if (datos.payload.visibleMarket) return MARKET.NO_LINES;
    if (datos.payload.gameState) return MARKET.STATE_ONLY;
    return MARKET.NONE;
  }

  return { DEFAULTS, LINK, MARKET, decideSend, retryDelay, nextLinkState,
           linkStateFor, shouldProbe, marketState };
});
