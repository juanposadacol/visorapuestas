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
  };

  const LINK = {
    DISCONNECTED: 'DISCONNECTED',
    CONNECTED: 'CONNECTED',
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

  /** Estado del enlace a partir de lo ocurrido, sin efectos secundarios. */
  function nextLinkState(current, result) {
    if (result === 'ok') return { state: LINK.CONNECTED, attempt: 0, error: '' };
    return {
      state: LINK.DISCONNECTED,
      attempt: (current && current.state === LINK.DISCONNECTED ? current.attempt : 0) + 1,
      error: typeof result === 'string' ? result : 'sin conexion',
    };
  }

  return { DEFAULTS, LINK, decideSend, retryDelay, nextLinkState };
});
