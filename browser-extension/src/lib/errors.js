/**
 * Errores estructurados, deduplicados y con cortacircuitos por raiz.
 *
 * En la prueba real sobre BetPlay el mismo fallo aparecio decenas de veces
 * seguidas y el historial quedo inservible:
 *
 *     escaneo: Cannot read properties of null (reading 'createTreeWalker')
 *     escaneo: Cannot read properties of null (reading 'createTreeWalker')
 *     ... (x43)
 *
 * Ni ocultar el error (`catch (_) {}`) ni repetirlo cuarenta veces. Se agrupa
 * por causa y por raiz, con cuenta y marcas de tiempo, para poder decir:
 *
 *     1 error activo · createTreeWalker / iframe · x43
 *
 * Ademas, una raiz que falla una y otra vez (un iframe que aparece y
 * desaparece) se marca ROOT_UNSTABLE y se deja descansar un rato, en lugar de
 * reintentarla en cada escaneo. Las raices sanas no se ven afectadas.
 *
 * Todo es logica pura: sin DOM, sin red y sin APIs de Chrome.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { errors: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DEFAULTS = {
    //: Familias de error distintas que se recuerdan a la vez.
    maxEntries: 40,
    //: Un error deja de considerarse "activo" si no se repite en este tiempo.
    activeWindowMs: 30000,
  };

  const BREAKER = {
    //: Fallos seguidos de la MISMA raiz antes de dejarla descansar.
    threshold: 4,
    //: Cuanto descansa una raiz inestable antes de volver a intentarlo.
    cooldownMs: 20000,
  };

  /** `0` es un instante valido: `Number(x) || Date.now()` se lo comeria. */
  function instante(valor) {
    const numero = Number(valor);
    return Number.isFinite(numero) ? numero : Date.now();
  }

  /**
   * Resume un mensaje de error a su causa, para que dos ocurrencias del mismo
   * problema con textos ligeramente distintos cuenten como una sola.
   */
  function classify(message) {
    const texto = String(message || '').trim();
    if (/createTreeWalker/i.test(texto)) return 'createTreeWalker';
    if (/is not a function/i.test(texto)) return 'api-ausente';
    if (/Cannot read propert/i.test(texto)) {
      const propiedad = texto.match(/reading '([^']+)'/);
      return propiedad ? `propiedad-nula:${propiedad[1]}` : 'propiedad-nula';
    }
    if (/cross-?origin|SecurityError|Blocked a frame/i.test(texto)) return 'otro-origen';
    if (/detached|not connected|no longer/i.test(texto)) return 'nodo-desmontado';
    return texto.slice(0, 60) || 'desconocido';
  }

  /**
   * Registro de errores con deduplicacion.
   *
   * `record` devuelve la entrada agrupada, con `count` acumulado. Quien llame
   * decide si merece la pena contarlo; aqui no se imprime nada.
   */
  function createErrorLog(options) {
    const cfg = { ...DEFAULTS, ...(options || {}) };
    const entradas = new Map();

    function keyOf(detalle) {
      return [detalle.stage || 'general', detalle.rootKind || '-',
              detalle.rootLabel || '-', classify(detalle.message)].join('|');
    }

    function record(detalle) {
      const dato = detalle || {};
      const ahora = instante(dato.now);
      const clave = keyOf(dato);
      const previa = entradas.get(clave);
      if (previa) {
        previa.count += 1;
        previa.lastSeen = ahora;
        previa.message = String(dato.message || previa.message);
        return previa;
      }
      const entrada = {
        key: clave,
        type: classify(dato.message),
        stage: dato.stage || 'general',
        rootKind: dato.rootKind || null,
        rootLabel: dato.rootLabel || null,
        message: String(dato.message || ''),
        count: 1,
        firstSeen: ahora,
        lastSeen: ahora,
      };
      entradas.set(clave, entrada);
      if (entradas.size > cfg.maxEntries) {
        // Se olvida la familia mas antigua, no la mas repetida.
        const masVieja = [...entradas.values()].sort((a, b) => a.lastSeen - b.lastSeen)[0];
        if (masVieja) entradas.delete(masVieja.key);
      }
      return entrada;
    }

    function list() {
      return [...entradas.values()].sort((a, b) => b.lastSeen - a.lastSeen);
    }

    /** Errores que se siguen repitiendo ahora mismo, no los ya superados. */
    function active(now) {
      const ahora = instante(now);
      return list().filter((e) => ahora - e.lastSeen <= cfg.activeWindowMs);
    }

    function clear() { entradas.clear(); }

    return { record, list, active, clear, classify, size: () => entradas.size };
  }

  /**
   * Cortacircuitos por raiz.
   *
   * Una raiz que falla `threshold` veces seguidas se marca ROOT_UNSTABLE y se
   * salta durante `cooldownMs`. Un exito la devuelve a la normalidad. Nunca
   * bloquea a las demas raices: la clave es por raiz.
   */
  function createCircuitBreaker(options) {
    const cfg = { ...BREAKER, ...(options || {}) };
    const estado = new Map();

    function get(key) {
      return estado.get(key) || { key, failures: 0, unstableUntil: 0 };
    }

    function failure(key, now) {
      const ahora = instante(now);
      const actual = get(key);
      actual.failures += 1;
      if (actual.failures >= cfg.threshold) {
        actual.unstableUntil = ahora + cfg.cooldownMs;
      }
      estado.set(key, actual);
      return { ...actual, unstable: actual.unstableUntil > ahora };
    }

    function success(key) {
      estado.delete(key);
    }

    /** ¿Toca saltarse esta raiz en este escaneo? */
    function shouldSkip(key, now) {
      const ahora = instante(now);
      const actual = estado.get(key);
      if (!actual) return false;
      if (actual.unstableUntil > ahora) return true;
      if (actual.unstableUntil) {
        // Se acabo el descanso: se le da otra oportunidad desde cero.
        estado.delete(key);
      }
      return false;
    }

    function unstable(now) {
      const ahora = instante(now);
      return [...estado.values()].filter((e) => e.unstableUntil > ahora)
        .map((e) => ({ key: e.key, retryInMs: e.unstableUntil - ahora }));
    }

    return { failure, success, shouldSkip, unstable, size: () => estado.size };
  }

  /** Linea corta para el popup: "createTreeWalker / iframe  x43". */
  function summarize(entrada) {
    if (!entrada) return '';
    const donde = entrada.rootKind
      ? `${entrada.rootKind}${entrada.rootLabel && entrada.rootLabel !== entrada.rootKind ? ` (${entrada.rootLabel})` : ''}`
      : entrada.stage;
    return `${entrada.type} / ${donde}  x${entrada.count}`;
  }

  return { DEFAULTS, BREAKER, classify, createErrorLog, createCircuitBreaker, summarize };
});
