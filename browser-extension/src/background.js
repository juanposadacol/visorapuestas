/**
 * Service worker: unico punto de contacto con la aplicacion local.
 *
 * Por que existe (en la version diagnostica no hacia falta y no se puso):
 * un `fetch` desde el content script sale con el origen de BetPlay, y para
 * aceptarlo el servidor local tendria que abrir la puerta a esa web entera.
 * Desde aqui el origen es `chrome-extension://<id>`, que es justo lo que el
 * servidor acepta. Ademas centraliza la reconexion y el latido en un solo
 * sitio en vez de una copia por pestana.
 *
 * Sigue siendo de SOLO LECTURA respecto de BetPlay: aqui no se toca la pagina.
 */
importScripts('lib/text.js', 'lib/markets.js', 'lib/lines.js', 'lib/dedupe.js',
              'lib/visibility.js', 'lib/options.js', 'lib/scan.js', 'lib/report.js',
              'lib/payload.js', 'lib/bridge_client.js');

const { payload: payloadLib, bridgeClient } = self.VDIAG;

const BRIDGE_HEADER = 'X-VisorApuestas-Bridge';
const DEFAULT_PORT = 8765;
const HEALTH_TIMEOUT_MS = 1500;
const SEND_TIMEOUT_MS = 2500;

const estado = {
  port: DEFAULT_PORT,
  link: { state: bridgeClient.LINK.DISCONNECTED, attempt: 0, error: '' },
  lastSignature: null,
  lastSentAt: 0,
  lastOkAt: 0,
  lastPayload: null,
  sent: 0,
  failed: 0,
  appVersion: '',
  nextProbeAt: 0,
};

function baseUrl() {
  return `http://127.0.0.1:${estado.port}`;
}

async function conFetch(url, opciones, timeoutMs) {
  const control = new AbortController();
  const temporizador = setTimeout(() => control.abort(), timeoutMs);
  try {
    return await fetch(url, { ...opciones, signal: control.signal });
  } finally {
    clearTimeout(temporizador);
  }
}

/** Comprueba si la aplicacion esta abierta. Sin ruido si no lo esta. */
async function probe() {
  try {
    const respuesta = await conFetch(`${baseUrl()}/health`, {
      method: 'GET',
      headers: { [BRIDGE_HEADER]: '1' },
    }, HEALTH_TIMEOUT_MS);
    if (!respuesta.ok) throw new Error(`health ${respuesta.status}`);
    const cuerpo = await respuesta.json();
    estado.appVersion = cuerpo.version || '';
    estado.link = bridgeClient.nextLinkState(estado.link, 'ok');
    estado.lastOkAt = Date.now();
    return true;
  } catch (error) {
    // La aplicacion cerrada es una situacion NORMAL, no un error que reportar
    // una y otra vez: se anota el estado y se reintenta mas tarde.
    estado.link = bridgeClient.nextLinkState(estado.link, 'aplicacion no disponible');
    estado.nextProbeAt = Date.now() + bridgeClient.retryDelay(estado.link.attempt);
    return false;
  }
}

async function enviar(payload) {
  try {
    const respuesta = await conFetch(`${baseUrl()}/v1/browser-state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', [BRIDGE_HEADER]: '1' },
      body: JSON.stringify(payload),
    }, SEND_TIMEOUT_MS);
    if (!respuesta.ok) {
      estado.failed += 1;
      if (respuesta.status >= 500 || respuesta.status === 0) {
        estado.link = bridgeClient.nextLinkState(estado.link, `error ${respuesta.status}`);
      }
      return false;
    }
    estado.sent += 1;
    estado.lastSentAt = Date.now();
    estado.lastOkAt = estado.lastSentAt;
    estado.link = bridgeClient.nextLinkState(estado.link, 'ok');
    return true;
  } catch (error) {
    estado.failed += 1;
    estado.link = bridgeClient.nextLinkState(estado.link, 'aplicacion no disponible');
    estado.nextProbeAt = Date.now() + bridgeClient.retryDelay(estado.link.attempt);
    return false;
  }
}

/** Recibe el payload de una pestana y decide si toca enviarlo. */
async function procesar(payload) {
  estado.lastPayload = payload;
  if (!payload) return;

  const ahora = Date.now();
  if (estado.link.state !== bridgeClient.LINK.CONNECTED) {
    if (ahora < estado.nextProbeAt) return;      // todavia no toca reintentar
    const vivo = await probe();
    if (!vivo) return;
  }

  const decision = bridgeClient.decideSend({
    payload,
    lastSignature: estado.lastSignature,
    lastSentAt: estado.lastSentAt,
    now: ahora,
  });
  if (!decision.send) return;

  const validacion = payloadLib.validatePayload(payload);
  if (!validacion.valid) return;                 // no se envia lo que no cumple

  const ok = await enviar(payload);
  if (ok) estado.lastSignature = decision.signature;
}

chrome.runtime.onMessage.addListener((mensaje, sender, sendResponse) => {
  if (!mensaje || typeof mensaje !== 'object') return undefined;

  if (mensaje.type === 'VDIAG_PAYLOAD') {
    procesar(mensaje.payload || null);
    sendResponse({ ok: true });
    return true;
  }

  if (mensaje.type === 'VDIAG_BRIDGE_STATE') {
    sendResponse({
      ok: true,
      bridge: {
        url: baseUrl(),
        port: estado.port,
        link: estado.link.state,
        attempt: estado.link.attempt,
        error: estado.link.error,
        appVersion: estado.appVersion,
        sent: estado.sent,
        failed: estado.failed,
        lastSentAt: estado.lastSentAt,
        lastOkAt: estado.lastOkAt,
        hasPayload: !!estado.lastPayload,
      },
    });
    return true;
  }

  if (mensaje.type === 'VDIAG_SET_PORT') {
    const puerto = Number(mensaje.port);
    if (Number.isInteger(puerto) && puerto >= 1024 && puerto <= 65535) {
      estado.port = puerto;
      estado.link = bridgeClient.nextLinkState(null, 'puerto cambiado');
      estado.nextProbeAt = 0;
      chrome.storage.local.set({ bridgePort: puerto });
    }
    sendResponse({ ok: true, port: estado.port });
    return true;
  }

  return undefined;
});

// El puerto elegido sobrevive al reinicio del service worker.
chrome.storage.local.get({ bridgePort: DEFAULT_PORT }, (datos) => {
  const puerto = Number(datos.bridgePort);
  if (Number.isInteger(puerto) && puerto >= 1024 && puerto <= 65535) estado.port = puerto;
});
