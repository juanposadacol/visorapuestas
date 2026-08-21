/**
 * Serializacion del diagnostico: texto legible y JSON estructurado.
 *
 * Incluye una pasada de REDACCION. Aunque el escaneo solo busca mercados y
 * cuotas, los textos de la pagina pueden arrastrar datos de la cuenta
 * (correo, saldo, identificadores). Como este informe esta pensado para
 * copiarse y enviarse, se enmascara antes de salir.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text,
    typeof require === 'function' ? require('./markets.js') : root.VDIAG.markets,
    typeof require === 'function' ? require('./visibility.js') : root.VDIAG.visibility
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { report: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text, markets, visibility) {
  'use strict';

  const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
  const LONG_DIGITS = /\b\d{9,}\b/g;
  const MONEY = /(?:saldo|balance|disponible|retirable)\s*[:=]?\s*\$?\s*[\d.,]+/gi;

  /** Enmascara datos personales que pudieran venir en los textos de la pagina. */
  function redact(value) {
    if (value === null || value === undefined) return value;
    return String(value)
      .replace(EMAIL, '[correo oculto]')
      .replace(MONEY, '[importe oculto]')
      .replace(LONG_DIGITS, '[numero oculto]');
  }

  function redactDeep(value) {
    if (typeof value === 'string') return redact(value);
    if (Array.isArray(value)) return value.map(redactDeep);
    if (value && typeof value === 'object') {
      const out = {};
      for (const [clave, contenido] of Object.entries(value)) out[clave] = redactDeep(contenido);
      return out;
    }
    return value;
  }

  function formatClock(ts) {
    if (!ts) return '--';
    const d = new Date(ts);
    const dos = (n) => String(n).padStart(2, '0');
    return `${dos(d.getHours())}:${dos(d.getMinutes())}:${dos(d.getSeconds())}.` +
      String(d.getMilliseconds()).padStart(3, '0');
  }

  function formatAge(ts, referencia) {
    if (!ts) return 'nunca';
    const ms = (referencia || Date.now()) - ts;
    if (ms < 1500) return 'ahora';
    if (ms < 90000) return `hace ${(ms / 1000).toFixed(1)} s`;
    return `hace ${Math.round(ms / 60000)} min`;
  }

  function marketStatusLine(market, referencia) {
    if (!market.existsInDom) return 'Existe en DOM: NO';
    const partes = [
      'Existe en DOM: SI',
      `Visible: ${market.isVisible ? 'SI' : 'NO'}`,
      `Lineas encontradas: ${market.lines.length}`,
      `Ultima mutacion: ${formatAge(market.lastMutationAt, referencia)}`,
      `Ultima lectura: ${formatAge(market.lastSeenAt, referencia)}`,
    ];
    if (!market.isVisible && market.visibilityReasons && market.visibilityReasons.length) {
      partes.push(`Oculto por: ${market.visibilityReasons.join(', ')}`);
    }
    return partes.join('\n');
  }

  /** Informe legible, listo para copiar y pegar. */
  function buildTextReport(snapshot, options) {
    const opciones = options || {};
    const referencia = snapshot.lastScanAt || Date.now();
    const out = [];

    out.push('VISORAPUESTAS DOM DIAGNOSTIC');
    out.push(`Generado: ${new Date().toISOString()}`);
    out.push(`URL: ${redact(snapshot.url)}`);
    out.push(`Ultimo escaneo: ${formatClock(snapshot.lastScanAt)} (${snapshot.lastScanMs} ms, ` +
             `${snapshot.scanCount} escaneos)`);
    out.push(`Mercado visualmente activo: ${snapshot.visibleMarket
      ? markets.labelFor(snapshot.visibleMarket) : 'no identificado'}`);

    if (snapshot.environment) {
      out.push('');
      out.push('ENTORNO DE LA PAGINA');
      const pistas = snapshot.environment.hints || [];
      out.push(pistas.length ? pistas.map((h) => `  - ${h}`).join('\n') : '  - sin pistas claras');
      const frames = snapshot.environment.frames || [];
      out.push(`  - iframes: ${frames.length}` + (frames.length
        ? ` (${frames.filter((f) => f.sameOrigin).length} accesibles)` : ''));
      out.push(`  - shadow roots abiertos: ${(snapshot.environment.shadowRoots || []).length}`);
    }

    out.push('');
    out.push('MERCADOS ENCONTRADOS EN DOM');
    if (!snapshot.markets.length) {
      out.push('  (ninguno reconocido todavia)');
    }
    for (const market of snapshot.markets) {
      out.push('');
      out.push(markets.labelFor(market.key).toUpperCase() +
        (market.key === 'UNKNOWN' ? `  [candidato: ${market.candidate || '?'}, ` +
          `confianza ${market.confidence.toFixed(2)}]` : ''));
      out.push(marketStatusLine(market, referencia));
      if (market.duplicates) {
        out.push(`Candidatos brutos: ${market.rawLineCount} | tras deduplicar: ${market.lines.length}`);
      }
    }

    for (const market of snapshot.markets) {
      if (!market.lines.length) continue;
      out.push('');
      out.push('-'.repeat(40));
      out.push(markets.labelFor(market.key).toUpperCase());
      for (const line of market.lines) {
        out.push(`${line.line}   OVER ${line.overOdds ?? '--'}   UNDER ${line.underOdds ?? '--'}`);
      }
    }

    if (snapshot.history && snapshot.history.length) {
      out.push('');
      out.push('-'.repeat(40));
      out.push('HISTORIAL DE LA SESION (mas reciente al final)');
      for (const entrada of snapshot.history.slice(-40)) {
        out.push(`${formatClock(entrada.ts)}  ${describeHistoryEntry(entrada)}`);
      }
    }

    if (opciones.includeDebug) {
      out.push('');
      out.push('-'.repeat(40));
      out.push('DEBUG');
      for (const market of snapshot.markets) {
        out.push('');
        out.push(`${markets.labelFor(market.key)}  <- "${redact(market.headerText)}"`);
        out.push(`  selector: ${market.debug.selector}` +
                 (market.debug.selectorFragile ? '   (FRAGIL: clase generada)' : ''));
        out.push(`  tag=${market.debug.tagName} role=${market.debug.role || '-'} ` +
                 `aria-label=${redact(market.debug.ariaLabel) || '-'}`);
        out.push(`  rect=${JSON.stringify(market.debug.rect)}`);
        out.push(`  padres: ${market.debug.parentChain.join(' < ')}`);
        const datos = market.debug.dataAttributes || {};
        if (Object.keys(datos).length) out.push(`  data-*: ${JSON.stringify(redactDeep(datos))}`);
      }
    }

    if (snapshot.errors && snapshot.errors.length) {
      out.push('');
      out.push('ERRORES');
      // Agrupados por causa y raiz: "createTreeWalker / iframe  x43", no la
      // misma frase cuarenta y tres veces.
      for (const error of snapshot.errors) {
        const donde = error.rootKind
          ? `${error.rootKind}${error.rootLabel ? ` (${redact(error.rootLabel)})` : ''}`
          : (error.stage || 'general');
        out.push(`  ${formatClock(error.lastSeen ?? error.ts)} [${error.type || '?'}] ` +
                 `${donde}  x${error.count ?? 1}`);
        out.push(`    ${redact(error.message)}`);
      }
    }

    if (snapshot.skippedRoots && snapshot.skippedRoots.length) {
      out.push('');
      out.push('RAICES OMITIDAS');
      for (const raiz of snapshot.skippedRoots) {
        out.push(`  ${raiz.kind} ${redact(raiz.label || '')}: ${raiz.reason}`);
      }
    }

    return out.join('\n');
  }

  function describeHistoryEntry(entrada) {
    switch (entrada.type) {
      case 'marketVisibleChanged':
        return `mercado visible: ${entrada.from || '(ninguno)'} -> ${entrada.to}`;
      case 'marketAppeared':
        return `aparece ${entrada.market} con ${entrada.lines} linea(s)`;
      case 'marketDisappeared':
        return `desaparece ${entrada.market} (tenia ${entrada.lastLines} linea(s))`;
      case 'visibilityChanged':
        return `${entrada.market} pasa a ${entrada.isVisible ? 'visible' : 'oculto'}` +
          (entrada.reasons && entrada.reasons.length ? ` (${entrada.reasons.join(', ')})` : '');
      case 'linesChanged': {
        const partes = [];
        if (entrada.added && entrada.added.length) partes.push(`+${entrada.added.join(',')}`);
        if (entrada.removed && entrada.removed.length) partes.push(`-${entrada.removed.join(',')}`);
        for (const cambio of entrada.changed || []) {
          partes.push(`${cambio.line}: ${cambio.from.join('/')} -> ${cambio.to.join('/')}`);
        }
        return `${entrada.market} ${entrada.visible ? '(visible)' : '(OCULTO)'} cambia ${partes.join(' ')}`;
      }
      case 'observerStarted':
        return 'observador de mutaciones activo';
      default:
        return entrada.type;
    }
  }

  /** JSON estructurado, ya redactado y sin datos de la cuenta. */
  function buildJsonReport(snapshot) {
    return redactDeep({
      tool: 'visorapuestas-dom-diagnostic',
      version: 1,
      generatedAt: new Date().toISOString(),
      url: snapshot.url,
      visibleMarket: snapshot.visibleMarket,
      scan: {
        lastScanAt: snapshot.lastScanAt,
        scanCount: snapshot.scanCount,
        lastScanMs: snapshot.lastScanMs,
        headerCount: snapshot.headerCount,
      },
      environment: snapshot.environment,
      markets: (snapshot.markets || []).map((market) => ({
        key: market.key,
        candidate: market.candidate,
        confidence: market.confidence,
        headerText: market.headerText,
        existsInDom: market.existsInDom,
        isVisible: market.isVisible,
        inViewport: market.inViewport,
        visibilityReasons: market.visibilityReasons,
        firstSeenAt: market.firstSeenAt,
        lastSeenAt: market.lastSeenAt,
        lastMutationAt: market.lastMutationAt,
        rootKind: market.rootKind,
        occurrences: market.occurrences,
        rawCandidates: market.rawCandidates,
        duplicates: market.duplicates,
        lines: market.lines,
        debug: market.debug,
      })),
      history: snapshot.history,
      errors: snapshot.errors,
      skippedRoots: snapshot.skippedRoots || [],
      unstableRoots: snapshot.unstableRoots || [],
    });
  }

  function suggestFileName(date) {
    const d = date || new Date();
    const dos = (n) => String(n).padStart(2, '0');
    return `visorapuestas-dom-diagnostic-${d.getFullYear()}${dos(d.getMonth() + 1)}` +
      `${dos(d.getDate())}-${dos(d.getHours())}${dos(d.getMinutes())}${dos(d.getSeconds())}.json`;
  }


  // ------------------------------------------------- estados para el popup
  //
  // Cada funcion responde UNA pregunta y devuelve { texto, clase }. Estan aqui
  // y no en el popup para poder probarlas: lo que el panel dice es justo lo
  // que llevo tres pruebas reales a diagnosticar mal el problema.

  /** ¿El escaneo esta funcionando? */
  function describeScanner(snapshot) {
    const datos = snapshot || {};
    if (!datos.scanCount) return { texto: 'todavia sin escanear', clase: 'oculto' };
    const activos = datos.activeErrors || 0;
    const inestables = (datos.unstableRoots || []).length;
    if (!activos && !inestables) {
      return { texto: `ACTIVO ✓  (${datos.rootsScanned || 0}/${datos.rootCount || 0} raices, ` +
                      `${datos.lastScanMs} ms)`, clase: 'si' };
    }
    const partes = [];
    if (activos) partes.push(`${activos} error(es) activos`);
    if (inestables) partes.push(`${inestables} raiz(ces) en descanso`);
    return { texto: `CON INCIDENCIAS: ${partes.join(', ')}`, clase: activos ? 'no' : 'oculto' };
  }

  /**
   * Estado de un campo del partido (marcador, cuarto o reloj).
   *
   * "no disponible" y "en revision" son cosas distintas y se dicen distinto:
   * la primera es que no se sabe, la segunda es que hay una lectura que no
   * cuadra y NO se esta publicando.
   */
  function describeGamePart(gameState, diagnostics, campo) {
    const estado = gameState || {};
    const diag = (diagnostics || {})[campo === 'marcador' ? 'score'
                 : campo === 'cuarto' ? 'period' : 'clock'] || {};

    if (campo === 'marcador') {
      if (diag.status === 'UNDER_REVIEW') {
        const enRevision = diag.candidate
          ? `${diag.candidate.scoreA}-${diag.candidate.scoreB}` : '?';
        const publicado = estado.scoreA !== undefined
          ? `${estado.scoreA}-${estado.scoreB}` : '--';
        return { texto: `${publicado}  (EN REVISION: se leyo ${enRevision})`, clase: 'oculto' };
      }
      if (estado.scoreA === undefined) {
        return { texto: `no disponible  (${diag.reason || 'sin datos'})`, clase: 'oculto' };
      }
      const equipos = diag.teams ? `  ${diag.teams.join(' / ')}` : '';
      return { texto: `${estado.scoreA}-${estado.scoreB} ✓${equipos}`, clase: 'si' };
    }

    const valor = campo === 'cuarto' ? estado.period : estado.clock;
    if (valor === undefined || valor === null) {
      return { texto: `no disponible  (${diag.reason || 'sin datos'})`, clase: 'oculto' };
    }
    return { texto: `${campo === 'cuarto' ? `Q${valor}` : valor} ✓`, clase: 'si' };
  }

  /** Resumen de mercados: cuantos, y cuantos con lineas. */
  function describeMarketsSummary(snapshot) {
    const lista = (snapshot || {}).markets || [];
    const enDom = lista.filter((m) => m.existsInDom);
    const conLineas = enDom.filter((m) => (m.lines || []).length);
    if (!enDom.length) return { texto: 'ninguno reconocido todavia', clase: 'oculto' };
    return {
      texto: `${enDom.length} detectado(s), ${conLineas.length} con lineas`,
      clase: conLineas.length ? 'si' : 'oculto',
    };
  }

  /** Errores agrupados, listos para pintar. Nunca la misma linea repetida. */
  function describeErrors(snapshot) {
    return ((snapshot || {}).errors || []).map((error) => {
      const donde = error.rootKind
        ? `${error.rootKind}${error.rootLabel ? ` (${redact(error.rootLabel)})` : ''}`
        : (error.stage || 'general');
      return `${error.type || '?'} / ${donde}  x${error.count ?? 1}\n    ${redact(error.message)}`;
    });
  }

  return { redact, redactDeep, formatClock, formatAge, buildTextReport, buildJsonReport,
           describeHistoryEntry, suggestFileName, describeScanner, describeGamePart,
           describeMarketsSummary, describeErrors };
});
