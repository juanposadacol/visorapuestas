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
importScripts('lib/dom.js', 'lib/errors.js', 'lib/text.js', 'lib/markets.js', 'lib/lines.js', 'lib/dedupe.js',
              'lib/visibility.js', 'lib/options.js', 'lib/scan.js', 'lib/report.js',
              'lib/gamestate.js', 'lib/payload.js', 'lib/bridge_client.js');

const { payload: payloadLib, bridgeClient } = self.VDIAG;

const BRIDGE_HEADER = 'X-VisorApuestas-Bridge';
const DEFAULT_PORT = 8765;
const HEALTH_TIMEOUT_MS = 1500;
const SEND_TIMEOUT_MS = 2500;

const estado = {
  port: DEFAULT_PORT,
  // EJE 1: la conexion con la aplicacion local. No sabe nada de mercados.
  link: { state: bridgeClient.LINK.DISCONNECTED, attempt: 0, error: '' },
  probeInFlight: false,
  nextProbeAt: 0,
  lastOkAt: 0,
  appVersion: '',
  // EJE 2: los datos. No sabe nada de la conexion.
  market: bridgeClient.MARKET.NONE,
  lastPayload: null,
  lastRejected: [],
  lastSignature: null,
  lastSentAt: 0,
  sent: 0,
  failed: 0,
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

/**
 * Comprueba si la aplicacion esta abierta.
 *
 * IMPORTANTE: esto no depende de que haya un mercado que enviar. La prueba
 * real dejo el caso clarisimo: `Invoke-RestMethod http://127.0.0.1:8765/health`
 * respondia `status: ok` mientras el popup decia DESCONECTADA, porque el
 * sondeo solo se lanzaba dentro del camino del payload y sin mercado nunca se
 * llegaba a el.
 */
async function probe() {
  if (estado.probeInFlight) return estado.link.state === bridgeClient.LINK.CONNECTED;
  estado.probeInFlight = true;
  estado.link = bridgeClient.nextLinkState(estado.link, 'probing');
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
    estado.nextProbeAt = 0;
    return true;
  } catch (error) {
    // La aplicacion cerrada es una situacion NORMAL, no un error que reportar
    // una y otra vez: se anota el estado y se reintenta mas tarde.
    estado.link = bridgeClient.nextLinkState(estado.link, 'aplicacion no disponible');
    estado.nextProbeAt = Date.now() + bridgeClient.retryDelay(estado.link.attempt);
    return false;
  } finally {
    estado.probeInFlight = false;
  }
}

/**
 * Mantiene vivo el enlace, HAYA O NO mercado.
 *
 * Se llama desde todo lo que despierta al service worker: el payload de un
 * escaneo, el latido del content script y la apertura del popup. Es la forma
 * de sobrevivir a que Manifest V3 duerma al worker sin pedir el permiso
 * "alarms": no hace falta un temporizador propio si la pestana ya nos habla.
 */
async function mantenerEnlace() {
  const ahora = Date.now();
  if (!bridgeClient.shouldProbe({
    link: estado.link,
    now: ahora,
    lastOkAt: estado.lastOkAt,
    nextProbeAt: estado.nextProbeAt,
    probeInFlight: estado.probeInFlight,
  })) {
    return estado.link.state === bridgeClient.LINK.CONNECTED;
  }
  return probe();
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
        estado.nextProbeAt = Date.now() + bridgeClient.retryDelay(estado.link.attempt);
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

/**
 * Recibe lo ultimo que vio una pestana.
 *
 * Los dos ejes se actualizan por separado:
 *   1. el enlace se mantiene SIEMPRE, haya mercado o no;
 *   2. el estado del mercado describe los datos, sin hablar de la conexion.
 */
async function procesar(mensaje) {
  const payload = (mensaje && mensaje.payload) || null;
  estado.lastPayload = payload;
  estado.lastRejected = (mensaje && mensaje.rejected) || [];

  const validacion = payload ? payloadLib.validatePayload(payload) : null;
  estado.market = bridgeClient.marketState({
    payload,
    validation: validacion,
    underReview: !!(mensaje && mensaje.underReview),
  });

  // 1) El enlace, pase lo que pase con los datos.
  const vivo = await mantenerEnlace();

  // 2) Los datos, solo si hay algo que valga la pena enviar.
  if (!payload || !vivo) return;
  if (validacion && !validacion.valid) return;    // no se envia lo que no cumple

  const decision = bridgeClient.decideSend({
    payload,
    lastSignature: estado.lastSignature,
    lastSentAt: estado.lastSentAt,
    now: Date.now(),
  });
  if (!decision.send) return;

  const ok = await enviar(payload);
  if (ok) estado.lastSignature = decision.signature;
}

/** Vista del puente para el popup: los dos ejes, separados y con su motivo. */
function vistaDelPuente() {
  const ahora = Date.now();
  return {
    url: baseUrl(),
    port: estado.port,
    link: bridgeClient.linkStateFor(estado.link, estado.lastOkAt, ahora),
    rawLink: estado.link.state,
    attempt: estado.link.attempt,
    error: estado.link.error,
    appVersion: estado.appVersion,
    market: estado.market,
    marketRejected: estado.lastRejected,
    sent: estado.sent,
    failed: estado.failed,
    lastSentAt: estado.lastSentAt,
    lastOkAt: estado.lastOkAt,
    hasPayload: !!estado.lastPayload,
  };
}

chrome.runtime.onMessage.addListener((mensaje, sender, sendResponse) => {
  if (!mensaje || typeof mensaje !== 'object') return undefined;

  if (mensaje.type === 'VDIAG_PAYLOAD') {
    procesar(mensaje);
    sendResponse({ ok: true });
    return true;
  }

  // Latido del content script. Existe para MANTENER EL ENLACE cuando no hay
  // nada que enviar: en Manifest V3 el service worker se duerme, asi que el
  // temporizador vive en la pestana y cada mensaje suyo lo despierta. Con esto
  // no hace falta el permiso "alarms".
  if (mensaje.type === 'VDIAG_HEARTBEAT') {
    mantenerEnlace();
    sendResponse({ ok: true, link: estado.link.state });
    return true;
  }

  if (mensaje.type === 'VDIAG_BRIDGE_STATE') {
    // Abrir el popup tambien es una ocasion para reconectar.
    mantenerEnlace();
    sendResponse({ ok: true, bridge: vistaDelPuente() });
    return true;
  }

  if (mensaje.type === 'VDIAG_SET_PORT') {
    const puerto = Number(mensaje.port);
    if (Number.isInteger(puerto) && puerto >= 1024 && puerto <= 65535) {
      estado.port = puerto;
      estado.link = bridgeClient.nextLinkState(null, 'puerto cambiado');
      estado.nextProbeAt = 0;
      estado.lastOkAt = 0;
      mantenerEnlace();
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
