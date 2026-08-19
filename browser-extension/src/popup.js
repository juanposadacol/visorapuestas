/**
 * Popup del diagnostico.
 *
 * Pide el estado al content script de la pestana activa y lo pinta. No hace
 * ninguna peticion de red ni guarda nada fuera de la memoria del popup.
 */
(function () {
  'use strict';

  const { markets, report } = globalThis.VDIAG;
  let ultimoEstado = null;

  const $ = (id) => document.getElementById(id);

  function aviso(texto, esError) {
    const nodo = $('aviso');
    nodo.textContent = texto;
    nodo.classList.toggle('error', !!esError);
    if (texto) setTimeout(() => { if (nodo.textContent === texto) nodo.textContent = ''; }, 4000);
  }

  async function pestanaActiva() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  }

  async function pedirEstado() {
    const tab = await pestanaActiva();
    if (!tab || tab.id === undefined) throw new Error('no hay pestana activa');
    try {
      const respuesta = await chrome.tabs.sendMessage(tab.id, { type: 'VDIAG_GET_STATE' });
      if (!respuesta || !respuesta.ok) {
        throw new Error(respuesta && respuesta.error ? respuesta.error : 'sin respuesta');
      }
      return respuesta.state;
    } catch (error) {
      throw new Error(
        'No se pudo hablar con la pagina. Abre un evento de BetPlay y recarga la pestana ' +
        `(detalle: ${error.message}).`);
    }
  }

  // ------------------------------------------------------------------- pintado

  function pintarEstado(estado) {
    $('sitio').textContent = /betplay/i.test(estado.url) ? 'BetPlay ✓' : 'sitio no reconocido';
    $('url').textContent = report.redact(estado.url);
    $('visible').textContent = estado.visibleMarket
      ? markets.labelFor(estado.visibleMarket)
      : 'no identificado';
    $('escaneo').textContent =
      `${report.formatClock(estado.lastScanAt)}  (${estado.lastScanMs} ms, ${estado.scanCount})`;
    const pistas = (estado.environment && estado.environment.hints) || [];
    $('entorno').textContent = pistas.length ? pistas.join(' · ') : 'sin pistas claras';
  }

  function pintarMercados(estado) {
    const contenedor = $('mercados');
    contenedor.textContent = '';
    if (!estado.markets.length) {
      contenedor.textContent = 'Todavia no se ha reconocido ningun mercado.';
      return;
    }
    const referencia = estado.lastScanAt || Date.now();
    for (const market of estado.markets) {
      const bloque = document.createElement('div');
      bloque.className = 'mercado';

      const titulo = document.createElement('div');
      titulo.className = 'titulo';
      const nombre = document.createElement('span');
      nombre.textContent = markets.labelFor(market.key).toUpperCase();
      if (market.key === 'UNKNOWN') nombre.className = 'dudoso';
      const estadoNodo = document.createElement('span');
      if (!market.existsInDom) {
        estadoNodo.textContent = 'NO EXISTE EN DOM';
        estadoNodo.className = 'no';
      } else if (market.isVisible) {
        estadoNodo.textContent = 'EN DOM · VISIBLE';
        estadoNodo.className = 'si';
      } else {
        estadoNodo.textContent = 'EN DOM · OCULTO';
        estadoNodo.className = 'oculto';
      }
      titulo.append(nombre, estadoNodo);
      bloque.appendChild(titulo);

      const detalle = document.createElement('div');
      detalle.className = 'detalle';
      const partes = [];
      if (market.existsInDom) {
        partes.push(`Lineas: ${market.lines.length}`);
        partes.push(`Ultima mutacion: ${report.formatAge(market.lastMutationAt, referencia)}`);
        partes.push(`Ultima lectura: ${report.formatAge(market.lastSeenAt, referencia)}`);
        if (!market.isVisible && market.visibilityReasons.length) {
          partes.push(`Oculto por: ${market.visibilityReasons.join(', ')}`);
        }
        if (!market.inViewport && market.isVisible) partes.push('fuera del viewport');
        if (market.duplicates) {
          partes.push(`candidatos brutos ${market.rawLineCount} → ${market.lines.length}`);
        }
        if (market.rootKind !== 'document') partes.push(`en ${market.rootKind}`);
      }
      if (market.key === 'UNKNOWN') {
        partes.push(`candidato ${market.candidate || '?'} (confianza ${market.confidence.toFixed(2)})`);
        partes.push(`texto: "${report.redact(market.headerText)}"`);
      }
      detalle.textContent = partes.join(' · ');
      bloque.appendChild(detalle);
      contenedor.appendChild(bloque);
    }
  }

  function pintarLineas(estado) {
    const contenedor = $('lineas');
    contenedor.textContent = '';
    const conLineas = estado.markets.filter((m) => m.lines.length);
    if (!conLineas.length) {
      contenedor.textContent = 'Sin lineas reconocidas todavia.';
      return;
    }
    for (const market of conLineas) {
      const titulo = document.createElement('h2');
      titulo.textContent = markets.labelFor(market.key) +
        (market.isVisible ? '' : '  (oculto)');
      contenedor.appendChild(titulo);

      const tabla = document.createElement('table');
      const cabecera = document.createElement('tr');
      for (const nombre of ['LINEA', 'OVER', 'UNDER']) {
        const th = document.createElement('th');
        th.textContent = nombre;
        cabecera.appendChild(th);
      }
      tabla.appendChild(cabecera);
      for (const line of market.lines) {
        const fila = document.createElement('tr');
        for (const valor of [line.line, line.overOdds ?? '--', line.underOdds ?? '--']) {
          const td = document.createElement('td');
          td.textContent = String(valor);
          fila.appendChild(td);
        }
        tabla.appendChild(fila);
      }
      contenedor.appendChild(tabla);
    }
  }

  function pintarHistorial(estado) {
    const lineas = (estado.history || []).slice(-30).map(
      (entrada) => `${report.formatClock(entrada.ts)}  ${report.describeHistoryEntry(entrada)}`);
    $('historial').textContent = lineas.length ? lineas.join('\n') : 'sin eventos todavia';
  }

  function pintarDebug(estado) {
    const bloques = estado.markets.map((market) => {
      const d = market.debug || {};
      return [
        `${markets.labelFor(market.key)}  <- "${report.redact(market.headerText)}"`,
        `  normalizado: ${market.normalized}`,
        `  motivos: ${(market.reasons || []).join('; ')}`,
        `  visible: ${market.isVisible}  existe: ${market.existsInDom}  viewport: ${market.inViewport}`,
        `  tag=${d.tagName} id=${d.id || '-'} role=${d.role || '-'}`,
        `  aria-label=${report.redact(d.ariaLabel) || '-'}`,
        `  class=${report.redact(d.className) || '-'}`,
        `  data-*=${JSON.stringify(report.redactDeep(d.dataAttributes || {}))}`,
        `  rect=${JSON.stringify(d.rect)}`,
        `  selector=${d.selector}${d.selectorFragile ? '   (FRAGIL: clase generada)' : ''}`,
        `  padres: ${(d.parentChain || []).join(' < ')}`,
      ].join('\n');
    });
    $('debug').textContent = bloques.join('\n\n') || 'sin mercados';
  }

  function pintar(estado) {
    ultimoEstado = estado;
    pintarEstado(estado);
    pintarMercados(estado);
    pintarLineas(estado);
    pintarHistorial(estado);
    if ($('ver-debug').checked) pintarDebug(estado);
  }

  // ------------------------------------------------------------------ acciones

  async function copiar(texto, queEs) {
    try {
      await navigator.clipboard.writeText(texto);
      aviso(`${queEs} copiado (${texto.length} caracteres)`);
    } catch (error) {
      aviso(`No se pudo copiar: ${error.message}`, true);
    }
  }

  function descargarJson() {
    if (!ultimoEstado) return;
    const contenido = JSON.stringify(report.buildJsonReport(ultimoEstado), null, 2);
    // Se genera un blob local en el propio popup: asi no hace falta el permiso
    // "downloads" ni ningun acceso adicional.
    const url = URL.createObjectURL(new Blob([contenido], { type: 'application/json' }));
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = report.suggestFileName();
    enlace.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    aviso('JSON descargado');
  }

  async function refrescar() {
    try {
      pintar(await pedirEstado());
    } catch (error) {
      aviso(error.message, true);
      $('mercados').textContent = error.message;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('copiar-texto').addEventListener('click', () => {
      if (!ultimoEstado) return aviso('sin datos todavia', true);
      copiar(report.buildTextReport(ultimoEstado, { includeDebug: $('ver-debug').checked }),
             'Diagnostico');
    });
    $('copiar-json').addEventListener('click', () => {
      if (!ultimoEstado) return aviso('sin datos todavia', true);
      copiar(JSON.stringify(report.buildJsonReport(ultimoEstado), null, 2), 'JSON');
    });
    $('descargar').addEventListener('click', descargarJson);
    $('refrescar').addEventListener('click', refrescar);
    $('ver-debug').addEventListener('change', (evento) => {
      $('tarjeta-debug').hidden = !evento.target.checked;
      if (evento.target.checked && ultimoEstado) pintarDebug(ultimoEstado);
    });
    refrescar();
    // El content script sigue observando aunque el popup este cerrado; mientras
    // esta abierto se refresca solo para ver los cambios en directo.
    setInterval(refrescar, 2000);
  });
})();
