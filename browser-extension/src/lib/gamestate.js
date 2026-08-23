/**
 * Descubrimiento del marcador, el cuarto y el reloj en el DOM.
 *
 * Aqui hay mucho mas riesgo que en los mercados: una pagina de apuestas esta
 * llena de numeros que se parecen a un marcador. La version anterior emparejaba
 * dos enteros cercanos en el arbol y les daba 0.75 de confianza, y en la prueba
 * real sobre BetPlay eso produjo:
 *
 *     MARCADOR/RELOJ DOM
 *     43-232
 *
 * que no era el marcador de nada. Bajar el maximo de 250 a 150 habria tapado
 * ESE caso concreto sin arreglar el problema: la proximidad entre dos numeros
 * NO es evidencia de que sean un marcador.
 *
 * La regla de esta version:
 *
 *   PROXIMIDAD SOLA NUNCA CONFIRMA UN MARCADOR.
 *
 * Hace falta evidencia semantica o estructural: un contenedor que se declare
 * marcador, nombres de equipo asociados a cada numero, simetria de maquetacion,
 * cercania al reloj o al cuarto, continuidad con lo que ya se sabia. Y en
 * contra: estar dentro de un bloque de apuestas, de una lista de mercados, de
 * cuotas, o acompanado de "Mas de"/"Menos de".
 *
 * Ademas, una sola lectura no confirma nada salvo que la evidencia sea muy
 * fuerte: un candidato debil tiene que repetirse varias veces seguidas. Y si un
 * marcador ya confirmado retrocede o pega un salto imposible, no se reemplaza:
 * se marca SCORE_UNDER_REVIEW y se conserva el anterior, para no contaminar el
 * calculo con un dato inventado.
 *
 * Principio de todo el proyecto: NINGUN DATO ES MEJOR QUE UN DATO INCORRECTO.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text,
    typeof require === 'function' ? require('./scoreboard.js') : root.VDIAG.scoreboard
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { gamestate: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text, scoreboardLib) {
  'use strict';

  const CLOCK_RE = /^(\d{1,2}):([0-5]\d)$/;
  //: Tope defensivo. NO es la defensa principal: el 232 del falso positivo
  //: cabia de sobra aqui y se rechaza por falta de evidencia, no por tamano.
  const MAX_SCORE = 250;
  const MAX_PERIOD = 4;

  //: Salto maximo creible del marcador de un equipo entre dos lecturas.
  const MAX_JUMP = 25;

  // ------------------------------------------------------------- vocabulario

  //: Un contenedor que se declara marcador / cabecera del evento.
  const SCOREBOARD_HINTS = /\b(scoreboard|score-?board|scoreheader|marcador|tanteo|resultado|match-?header|event-?header|game-?header|live-?header|score-?panel|scores?)\b|score|marcador/;
  /**
   * Un numero que se declara puntuacion.
   *
   * OJO con el limite de palabra final: la version anterior terminaba en
   * `|score`, y eso hacia que "kambibc-scoreboard-grid-item" —una celda de
   * PARCIAL— contase como "declarado puntuacion", porque "scoreboard" contiene
   * "score". Ahora se exige que "score" termine ahi: `-score\b` casa con
   * "grid-score" y NO con "scoreboard".
   */
  const SCORE_VALUE_HINTS =
    /\b(score|scores|puntos|points|tanteo|marcador|result|resultado)\b|-score\b|\bscore-/;
  //: Nombres de equipo: atributos que los identifican.
  const TEAM_HINTS = /\b(team|equipo|participant|competitor|home|away|local|visitante|opponent|contender)\b|team|equipo/;
  //: Bloques de APUESTAS. Un numero aqui dentro no es un marcador.
  const BETTING_HINTS = /\b(market|mercado|odds|cuota|cuotas|bet|apuesta|apuestas|selection|seleccion|outcome|coupon|cupon|betslip|bet-?slip|boleto|carrito|price|stake|wager)\b|odds|cuota|market|bet/;
  //: Listas de mercados.
  const MARKET_LIST_HINTS = /\b(market-?list|markets|lista-?mercados|accordion|coupon-?list|outcomes)\b/;
  //: Estado en vivo: sitio natural del cuarto y del reloj.
  const LIVE_HINTS = /\b(live|en-?vivo|directo|period|periodo|cuarto|quarter|clock|reloj|timer|tiempo|match-?state|game-?state|status)\b/;

  const OVER_UNDER_RE = /\b(mas de|menos de|over|under)\b/;

  //: Palabras que descartan un texto como nombre de equipo.
  const NO_ES_EQUIPO = /\b(total|puntos|cuota|apuesta|mercado|mas de|menos de|over|under|handicap|ganador|linea|cuarto|periodo|mitad|prorroga|iniciar|sesion|deposito|saldo|retirar|combinada|acumulada)\b/;

  // ----------------------------------------------------------- recorrido base

  function attrTextOf(node, adapter) {
    if (!adapter || typeof adapter.attrText !== 'function') return '';
    return adapter.attrText(node) || '';
  }

  /** Recorrido con la cadena de padres, del mas cercano al mas lejano. */
  function walk(node, adapter, visit, chain) {
    const padres = chain || [];
    visit(node, padres);
    for (const hijo of adapter.children(node)) walk(hijo, adapter, visit, [node, ...padres]);
  }

  /**
   * Hojas con texto de un arbol.
   *
   * Reloj, cuarto y marcador necesitan las MISMAS hojas. Recorrer el arbol una
   * vez por cada uno significaba tres recorridos completos del documento en
   * cada escaneo, y en una pagina como BetPlay eso se nota. Se permite pasar
   * las hojas ya calculadas.
   */
  function leaves(root, adapter, cache) {
    if (cache && cache.has(root)) return cache.get(root);
    const hojas = [];
    let indice = 0;
    walk(root, adapter, (node, chain) => {
      if (adapter.children(node).length === 0) {
        const valor = (adapter.text(node) || '').trim();
        if (valor) hojas.push({ node, chain, text: valor, order: indice++ });
      }
    });
    if (cache) cache.set(root, hojas);
    return hojas;
  }

  /** ¿Alguno de los ancestros cercanos encaja con este patron? */
  function chainMatches(hoja, adapter, patron, profundidad) {
    const limite = profundidad === undefined ? 6 : profundidad;
    const cadena = hoja.chain || [];
    for (let i = 0; i < cadena.length && i < limite; i += 1) {
      if (patron.test(attrTextOf(cadena[i], adapter))) return i;
    }
    return -1;
  }

  /** Ancestro comun mas cercano de dos hojas, con su profundidad. */
  function sharedAncestor(a, b, limite) {
    const tope = limite === undefined ? 6 : limite;
    const cadenaA = a.chain || [];
    const cadenaB = b.chain || [];
    for (let i = 0; i < cadenaA.length && i < tope; i += 1) {
      const indice = cadenaB.indexOf(cadenaA[i]);
      if (indice !== -1 && indice < tope) {
        return { node: cadenaA[i], depth: Math.max(i, indice), depthA: i, depthB: indice };
      }
    }
    return null;
  }

  // --------------------------------------------------------- nombres de equipo

  /** ¿Este texto puede ser el nombre de un equipo? */
  function pareceNombreDeEquipo(valor) {
    const crudo = String(valor || '').trim();
    if (crudo.length < 3 || crudo.length > 40) return false;
    if (/^\d/.test(crudo)) return false;
    const letras = (crudo.match(/[a-zA-ZáéíóúñÁÉÍÓÚÑ]/g) || []).length;
    if (letras < 3) return false;
    if (/\d{2,}/.test(crudo)) return false;                 // "Cuota 1.85", "12:34"
    return !NO_ES_EQUIPO.test(text.normalize(crudo));
  }

  /**
   * Nombre de equipo asociado a un numero: se busca en el ancestro que los
   * agrupa (la tarjeta del equipo), no en cualquier sitio de la pagina.
   */
  function equipoDe(hoja, hojas, adapter) {
    const cadena = hoja.chain || [];
    for (let i = 0; i < cadena.length && i < 4; i += 1) {
      const contenedor = cadena[i];
      const dentro = hojas.filter((h) => (h.chain || []).includes(contenedor));
      const nombres = dentro.filter((h) => h !== hoja && pareceNombreDeEquipo(h.text));
      if (!nombres.length) continue;
      // Si el contenedor tiene DOS nombres o mas, no es la tarjeta de un
      // equipo sino el bloque entero: no se puede atribuir el numero.
      if (nombres.length > 1 && i > 0) continue;
      const marcado = TEAM_HINTS.test(attrTextOf(contenedor, adapter));
      return { name: nombres[0].text, depth: i, marked: marcado };
    }
    return null;
  }

  // ------------------------------------------------------------------ reloj

  /**
   * Candidatos a reloj: hojas con forma MM:SS, puntuadas por su CONTEXTO.
   *
   * En BetPlay hay relojes de transmision, temporizadores y otros partidos.
   * Un MM:SS suelto en cualquier rincon de la pagina no es el reloj del
   * partido, por muy bien formado que este.
   */
  function findClockCandidates(root, adapter, cache) {
    const hojas = leaves(root, adapter, cache);
    const candidatos = [];
    for (const hoja of hojas) {
      const match = hoja.text.match(CLOCK_RE);
      if (!match) continue;
      const minutos = Number(match[1]);
      const segundos = Number(match[2]);
      // Un cuarto no dura mas de 12 minutos en ninguna competicion habitual.
      if (minutos > 12) continue;

      const razones = [];
      let confianza = 0.25;                    // un MM:SS solo, sin contexto

      if (SCOREBOARD_HINTS.test(attrTextOf(hoja.node, adapter)) ||
          chainMatches(hoja, adapter, SCOREBOARD_HINTS, 4) !== -1) {
        confianza += 0.35;
        razones.push('dentro del marcador');
      }
      if (LIVE_HINTS.test(attrTextOf(hoja.node, adapter)) ||
          chainMatches(hoja, adapter, LIVE_HINTS, 3) !== -1) {
        confianza += 0.20;
        razones.push('en el bloque de estado en vivo');
      }
      if (cercaDeUnCuarto(hoja, hojas)) {
        confianza += 0.20;
        razones.push('junto al cuarto');
      }
      if (cercaDeNombresDeEquipo(hoja, hojas)) {
        confianza += 0.15;
        razones.push('junto a los nombres de los equipos');
      }
      if (chainMatches(hoja, adapter, BETTING_HINTS, 6) !== -1) {
        confianza -= 0.40;
        razones.push('dentro de un bloque de apuestas');
      }

      candidatos.push({
        node: hoja.node,
        raw: hoja.text,
        value: `${String(minutos).padStart(2, '0')}:${match[2]}`,
        seconds: minutos * 60 + segundos,
        confidence: acotar(confianza),
        reasons: razones,
      });
    }
    return candidatos;
  }

  function cercaDeUnCuarto(hoja, hojas) {
    return hojas.some((otra) => {
      if (otra === hoja) return false;
      if (!periodoDe(otra.text)) return false;
      const comun = sharedAncestor(hoja, otra, 4);
      return !!comun;
    });
  }

  function cercaDeNombresDeEquipo(hoja, hojas) {
    const cerca = hojas.filter((otra) => otra !== hoja &&
      pareceNombreDeEquipo(otra.text) && !!sharedAncestor(hoja, otra, 4));
    return cerca.length >= 2;
  }

  // ----------------------------------------------------------------- cuarto

  function periodoDe(valor) {
    const normalizado = text.normalizeOrdinals(valor || '');
    if (!normalizado || normalizado.length > 24) return null;
    const directo = normalizado.match(/^q\s*([1-4])$/) ||
                    normalizado.match(/^([1-4])\s*q$/) ||
                    normalizado.match(/\b([1-4])\s+(?:cuarto|periodo|parcial|quarter)\b/) ||
                    normalizado.match(/\b(?:cuarto|periodo|parcial|quarter)\s+([1-4])\b/);
    if (!directo) return null;
    const periodo = Number(directo[1]);
    return periodo >= 1 && periodo <= MAX_PERIOD ? periodo : null;
  }

  /**
   * Candidatos a cuarto.
   *
   * Ojo con la trampa: estando en el Q3 la pagina muestra tambien mercados del
   * Q4. Que exista un titulo "Total de puntos - Cuarto 4" NO significa que el
   * partido este en el cuarto 4. Por eso los candidatos que cuelgan de un
   * bloque de apuestas se penalizan fuerte, y manda el marcador / estado en
   * vivo.
   */
  function findPeriodCandidates(root, adapter, cache) {
    const hojas = leaves(root, adapter, cache);
    const candidatos = [];
    for (const hoja of hojas) {
      if (hoja.text.length > 24) continue;
      const periodo = periodoDe(hoja.text);
      if (periodo === null) continue;

      const razones = [];
      let confianza = 0.3;
      const normalizado = text.normalizeOrdinals(hoja.text);
      if (/^q?\s*[1-4]\s*q?$/.test(normalizado)) {
        confianza += 0.1;
        razones.push('etiqueta escueta');
      }
      if (SCOREBOARD_HINTS.test(attrTextOf(hoja.node, adapter)) ||
          chainMatches(hoja, adapter, SCOREBOARD_HINTS, 4) !== -1) {
        confianza += 0.35;
        razones.push('dentro del marcador');
      }
      if (LIVE_HINTS.test(attrTextOf(hoja.node, adapter)) ||
          chainMatches(hoja, adapter, LIVE_HINTS, 3) !== -1) {
        confianza += 0.25;
        razones.push('en el bloque de estado en vivo');
      }
      const enApuestas = chainMatches(hoja, adapter, BETTING_HINTS, 6);
      if (enApuestas !== -1) {
        confianza -= 0.55;
        razones.push('es el cuarto de un MERCADO, no el del partido');
      }
      if (chainMatches(hoja, adapter, MARKET_LIST_HINTS, 6) !== -1) {
        confianza -= 0.25;
        razones.push('dentro de una lista de mercados');
      }
      if (OVER_UNDER_RE.test(text.normalize(hoja.text))) {
        confianza -= 0.30;
        razones.push('acompanado de mas/menos');
      }

      candidatos.push({
        node: hoja.node, raw: hoja.text, value: periodo,
        confidence: acotar(confianza), reasons: razones,
      });
    }
    return candidatos;
  }

  // --------------------------------------------------------------- marcador

  function acotar(valor) {
    return Math.max(0, Math.min(1, Math.round(valor * 1000) / 1000));
  }

  /** Cuantos numeros hay colgando de un contenedor: mucho ruido resta. */
  function numerosBajo(contenedor, hojas) {
    return hojas.filter((h) => (h.chain || []).includes(contenedor) &&
                               /\d/.test(h.text)).length;
  }

  /**
   * Candidatos a marcador, con una puntuacion EXPLICITA.
   *
   * La base es deliberadamente baja: dos enteros cercanos, por si solos, no
   * llegan ni de lejos al umbral. Lo que sube la nota es la evidencia:
   *
   *   +0.35  cada numero esta asociado al nombre de un equipo
   *   +0.20  los dos cuelgan de un contenedor que se declara marcador
   *   +0.15  los propios numeros se declaran puntuacion
   *   +0.10  maquetacion simetrica (misma profundidad y misma etiqueta)
   *   +0.10  continuidad con el marcador que ya teniamos
   *   +0.10  cerca del reloj o del cuarto
   *
   * y lo que la hunde:
   *
   *   -0.40  dentro de un bloque de apuestas
   *   -0.30  dentro de cuotas
   *   -0.30  dentro de una lista de mercados
   *   -0.30  acompanados de "Mas de" / "Menos de"
   *   -0.20  el ancestro comun esta lleno de numeros
   */
  function findScoreCandidates(root, adapter, previous, cache) {
    const hojas = leaves(root, adapter, cache);
    const numeros = [];
    for (const hoja of hojas) {
      if (!/^\d{1,3}$/.test(hoja.text)) continue;
      const valor = Number(hoja.text);
      if (valor > MAX_SCORE) continue;
      numeros.push({ ...hoja, value: valor });
    }

    const anterior = previous && previous.value ? previous.value : null;
    const candidatos = [];
    for (let i = 0; i < numeros.length - 1; i += 1) {
      const a = numeros[i];
      const b = numeros[i + 1];
      const comun = sharedAncestor(a, b, 4);
      if (!comun) continue;

      // ------------------------------------------------ imposibles, no dudosos
      //
      // Estas dos no son penalizaciones: son parejas que NO PUEDEN ser un
      // marcador, y penalizarlas dejaria la puerta abierta a que otra suma de
      // bonos las colase. En la prueba real sobre BetPlay/Kambi el par elegido
      // fue exactamente el primero de los dos casos: el TOTAL de un equipo con
      // el parcial del primer cuarto del otro.
      const totalA = scoreboardLib.isTotalCell(a.node, adapter);
      const totalB = scoreboardLib.isTotalCell(b.node, adapter);
      const parcialA = scoreboardLib.isPartialCell(a.node, adapter);
      const parcialB = scoreboardLib.isPartialCell(b.node, adapter);

      // 1. TOTAL de un equipo con PARCIAL del otro.
      if ((totalA && parcialB) || (parcialA && totalB)) continue;

      // 2. Dos PARCIALES de equipos distintos: son el Qx de uno y el Qy del
      //    otro, nunca el marcador.
      const equipoA = equipoDe(a, hojas, adapter);
      const equipoB = equipoDe(b, hojas, adapter);
      if (parcialA && parcialB && equipoA && equipoB && equipoA.name !== equipoB.name) {
        continue;
      }

      const razones = [];
      //: Base baja a proposito: la proximidad sola no confirma nada.
      let confianza = 0.15;

      if (equipoA && equipoB && equipoA.name !== equipoB.name) {
        confianza += 0.35;
        razones.push(`equipos asociados: ${equipoA.name} / ${equipoB.name}`);
      }

      const marcadorA = SCOREBOARD_HINTS.test(attrTextOf(a.node, adapter)) ||
                        chainMatches(a, adapter, SCOREBOARD_HINTS, 4) !== -1;
      const marcadorB = SCOREBOARD_HINTS.test(attrTextOf(b.node, adapter)) ||
                        chainMatches(b, adapter, SCOREBOARD_HINTS, 4) !== -1;
      if (marcadorA && marcadorB) {
        confianza += 0.20;
        razones.push('mismo contenedor de marcador');
      }

      const valorA = SCORE_VALUE_HINTS.test(attrTextOf(a.node, adapter));
      const valorB = SCORE_VALUE_HINTS.test(attrTextOf(b.node, adapter));
      if (valorA && valorB) {
        confianza += 0.15;
        razones.push('los numeros se declaran puntuacion');
      }

      if (comun.depthA === comun.depthB && mismaEtiqueta(a.node, b.node, adapter)) {
        confianza += 0.10;
        razones.push('maquetacion simetrica');
      }

      if (anterior && continuaDe(anterior, { scoreA: a.value, scoreB: b.value })) {
        confianza += 0.10;
        razones.push('continua el marcador anterior');
      }

      if (cercaDeRelojOCuarto(a, b, hojas)) {
        confianza += 0.10;
        razones.push('junto al reloj o al cuarto');
      }

      if (chainMatches(a, adapter, BETTING_HINTS, 6) !== -1 ||
          chainMatches(b, adapter, BETTING_HINTS, 6) !== -1) {
        confianza -= 0.40;
        razones.push('dentro de un bloque de apuestas');
      }
      if (chainMatches(a, adapter, MARKET_LIST_HINTS, 6) !== -1) {
        confianza -= 0.30;
        razones.push('dentro de una lista de mercados');
      }
      if (textoConLados(comun.node, adapter)) {
        confianza -= 0.30;
        razones.push('acompanado de mas/menos');
      }
      const cuantos = numerosBajo(comun.node, hojas);
      if (cuantos > 6) {
        confianza -= 0.20;
        razones.push(`el contenedor tiene ${cuantos} numeros`);
      }

      candidatos.push({
        nodes: [a.node, b.node],
        //: Contenedor para el diagnostico estructural: el ancestro que declara
        //: ser marcador si lo hay, y si no el que agrupa a los dos numeros.
        container: contenedorDelMarcador(a, b, adapter) || comun.node,
        raw: `${a.text}-${b.text}`,
        value: { scoreA: a.value, scoreB: b.value },
        teams: equipoA && equipoB ? [equipoA.name, equipoB.name] : null,
        //: Evidencia fuerte = se puede confirmar en una sola lectura. Una
        //: celda de parcial nunca cuenta como evidencia fuerte, por muchos
        //: otros indicios que la acompanen.
        strong: !!(equipoA && equipoB && equipoA.name !== equipoB.name) &&
                (marcadorA && marcadorB) && !parcialA && !parcialB,
        confidence: acotar(confianza),
        reasons: razones,
      });
    }
    return candidatos;
  }

  /** Ancestro comun que se declara marcador, si existe. */
  function contenedorDelMarcador(a, b, adapter) {
    const cadena = a.chain || [];
    for (let i = 0; i < cadena.length && i < 6; i += 1) {
      const ancestro = cadena[i];
      if (!(b.chain || []).includes(ancestro)) continue;
      if (SCOREBOARD_HINTS.test(attrTextOf(ancestro, adapter))) return ancestro;
    }
    return null;
  }

  /**
   * Contenedores que se declaran marcador, aunque no se haya podido leer
   * ningun marcador dentro. Sirve para el diagnostico estructural: si no
   * sabemos leer el marcador, al menos podemos mandar como esta montado.
   */
  function findScoreboardContainers(root, adapter) {
    const encontrados = [];
    const cadenas = new Map();
    walk(root, adapter, (node, chain) => {
      if (SCOREBOARD_HINTS.test(attrTextOf(node, adapter))) {
        encontrados.push(node);
        cadenas.set(node, chain);
      }
    });
    // Se prefiere el MAS EXTERNO: es el bloque entero de la cabecera del
    // evento, con los dos equipos, el cuarto y el reloj dentro.
    const externos = encontrados.filter(
      (node) => !(cadenas.get(node) || []).some((padre) => encontrados.includes(padre)));
    return externos.slice(0, 3);
  }

  function mismaEtiqueta(a, b, adapter) {
    const ta = (attrTextOf(a, adapter).split(' ')[0] || '');
    const tb = (attrTextOf(b, adapter).split(' ')[0] || '');
    return !!ta && ta === tb;
  }

  function textoConLados(nodo, adapter) {
    return OVER_UNDER_RE.test(text.normalize(adapter.text(nodo) || ''));
  }

  function cercaDeRelojOCuarto(a, b, hojas) {
    return hojas.some((h) => {
      if (h === a || h === b) return false;
      if (!CLOCK_RE.test(h.text) && periodoDe(h.text) === null) return false;
      return !!sharedAncestor(a, h, 4) && !!sharedAncestor(b, h, 4);
    });
  }

  /** ¿Es este marcador una continuacion creible del anterior? */
  function continuaDe(anterior, actual) {
    const subeA = actual.scoreA - anterior.scoreA;
    const subeB = actual.scoreB - anterior.scoreB;
    return subeA >= 0 && subeB >= 0 && subeA <= MAX_JUMP && subeB <= MAX_JUMP;
  }

  // ------------------------------------------------------------- validacion

  //: Sin memoria, la primera lectura tiene que ser MUY buena: equivocarse aqui
  //: contamina despues toda la memoria, porque el marcador siguiente se juzga
  //: contra este.
  const UMBRAL_INICIAL = 0.9;
  //: Evidencia intermedia (equipos asociados, pero maquetacion opaca): se
  //: acepta solo despues de repetirse varias lecturas seguidas.
  const UMBRAL_REPETIDO = 0.6;
  //: Con un marcador ya confirmado, una continuacion creible exige menos.
  //: Aun asi queda MUY por encima de lo que puntua la proximidad sola (0.15).
  const UMBRAL_CONTINUACION = 0.5;
  //: Lecturas seguidas iguales que exige un candidato sin evidencia fuerte.
  const REPETICIONES = 3;

  /**
   * Elige entre candidatos aplicando las validaciones. Devuelve
   * { value, confidence, reason } con `value` null si no hay respuesta clara.
   */
  function pickBest(candidatos, previous, validate, umbral) {
    if (!candidatos.length) return { value: null, confidence: 0, reason: 'sin candidatos' };

    const minimo = umbral === undefined ? 0 : umbral;
    const validos = candidatos.filter((c) => validate(c, previous));
    if (!validos.length) return { value: null, confidence: 0, reason: 'ningun candidato valido' };

    const suficientes = validos.filter((c) => (c.confidence || 0) >= minimo);
    if (!suficientes.length) {
      const mejor = [...validos].sort((a, b) => b.confidence - a.confidence)[0];
      return { value: null, confidence: mejor.confidence, raw: mejor.raw,
               reason: `evidencia insuficiente (${mejor.confidence.toFixed(2)} < ${minimo})`,
               rejected: mejor };
    }

    suficientes.sort((a, b) => b.confidence - a.confidence);
    const mejor = suficientes[0];
    const empatados = suficientes.filter(
      (c) => Math.abs(c.confidence - mejor.confidence) < 1e-9 &&
             JSON.stringify(c.value) !== JSON.stringify(mejor.value));
    if (empatados.length) {
      // Varios candidatos igual de plausibles y distintos: no se elige a dedo.
      return { value: null, confidence: 0, reason: 'candidatos ambiguos',
               ambiguous: [mejor, ...empatados].map((c) => c.raw) };
    }
    return { value: mejor.value, confidence: mejor.confidence, reason: '',
             raw: mejor.raw, strong: !!mejor.strong, reasons: mejor.reasons,
             teams: mejor.teams || null, node: mejor.container || null };
  }

  function clockValidator(candidato, previous) {
    if (!previous || previous.seconds === undefined || previous.seconds === null) return true;
    // El reloj baja o se para. Solo puede subir al empezar un cuarto nuevo.
    if (candidato.seconds <= previous.seconds) return true;
    return candidato.seconds >= 9 * 60;    // reinicio verosimil de cuarto
  }

  function periodValidator(candidato, previous) {
    if (candidato.value < 1 || candidato.value > MAX_PERIOD) return false;
    if (previous === null || previous === undefined) return true;
    return candidato.value >= previous;    // el cuarto no retrocede
  }

  function scoreValidator(candidato, previous) {
    const { scoreA, scoreB } = candidato.value;
    if (!Number.isInteger(scoreA) || !Number.isInteger(scoreB)) return false;
    if (scoreA > MAX_SCORE || scoreB > MAX_SCORE) return false;
    return true;                            // el resto lo decide la memoria
  }

  // ------------------------------------------------- estabilizacion temporal

  /**
   * Convierte una lectura en una decision, usando la memoria.
   *
   * Devuelve { value, confirmed, streak, status, reason }. `status` puede ser
   * 'CONFIRMED', 'CANDIDATE', 'UNDER_REVIEW' o 'NONE'.
   */
  function stabilizeScore(lectura, memoria) {
    const previa = memoria || null;
    const confirmadoPrevio = previa && previa.confirmed ? previa.value : null;

    if (!lectura.value) {
      // Sin lectura nueva se conserva lo confirmado: que la casa repinte el
      // marcador un instante no es motivo para olvidarlo.
      return {
        value: confirmadoPrevio,
        confirmed: !!confirmadoPrevio,
        streak: 0,
        candidate: null,
        status: confirmadoPrevio ? 'CONFIRMED' : 'NONE',
        reason: lectura.reason,
        confidence: confirmadoPrevio ? (previa.confidence || 0) : 0,
      };
    }

    const nueva = lectura.value;
    const igualQueConfirmado = confirmadoPrevio &&
      confirmadoPrevio.scoreA === nueva.scoreA && confirmadoPrevio.scoreB === nueva.scoreB;

    if (igualQueConfirmado) {
      return { value: nueva, confirmed: true, streak: (previa.streak || 1) + 1,
               candidate: null, status: 'CONFIRMED', reason: '',
               confidence: Math.max(lectura.confidence, previa.confidence || 0) };
    }

    if (confirmadoPrevio && !continuaDe(confirmadoPrevio, nueva)) {
      // Retroceso o salto imposible: NO se reemplaza. Se conserva el anterior
      // y se avisa, en vez de meter un numero raro en los calculos.
      const repetido = previa.pending &&
        previa.pending.scoreA === nueva.scoreA && previa.pending.scoreB === nueva.scoreB
        ? (previa.pendingStreak || 0) + 1 : 1;
      if (repetido >= REPETICIONES && lectura.confidence >= UMBRAL_INICIAL) {
        // Se ha repetido lo suficiente y con evidencia fuerte: la casa
        // corrigio el marcador de verdad.
        return { value: nueva, confirmed: true, streak: 1, candidate: null,
                 status: 'CONFIRMED', reason: 'correccion aceptada tras repetirse',
                 confidence: lectura.confidence };
      }
      return {
        value: confirmadoPrevio, confirmed: true, streak: previa.streak || 1,
        candidate: nueva, pending: nueva, pendingStreak: repetido,
        status: 'UNDER_REVIEW', confidence: previa.confidence || 0,
        reason: `lectura ${nueva.scoreA}-${nueva.scoreB} incompatible con ` +
                `${confirmadoPrevio.scoreA}-${confirmadoPrevio.scoreB}`,
      };
    }

    // Lectura nueva y creible. ¿Se publica ya o hace falta que se repita?
    const mismaQueCandidato = previa && previa.candidate &&
      previa.candidate.scoreA === nueva.scoreA && previa.candidate.scoreB === nueva.scoreB;
    const racha = mismaQueCandidato ? (previa.candidateStreak || 1) + 1 : 1;

    // Tres caminos para confirmar, en orden de exigencia:
    //   1. evidencia estructural fuerte (equipos + contenedor de marcador) o
    //      confianza muy alta: vale una sola lectura;
    //   2. ya habia un marcador confirmado y esto lo continua de forma
    //      creible: basta con evidencia media;
    //   3. evidencia media sin marcador previo: hay que verlo repetido.
    const deUnaVez = lectura.strong || lectura.confidence >= UMBRAL_INICIAL ||
                     (confirmadoPrevio && lectura.confidence >= UMBRAL_CONTINUACION);
    const repitiendose = lectura.confidence >= UMBRAL_REPETIDO && racha >= REPETICIONES;

    if (deUnaVez || repitiendose) {
      return { value: nueva, confirmed: true, streak: 1, candidate: null,
               status: 'CONFIRMED', reason: '', confidence: lectura.confidence };
    }

    const conservado = {
      value: confirmadoPrevio, confirmed: !!confirmadoPrevio, streak: 0,
      status: confirmadoPrevio ? 'CONFIRMED' : 'NONE',
      confidence: confirmadoPrevio ? (previa.confidence || 0) : 0,
    };
    if (lectura.confidence >= UMBRAL_REPETIDO) {
      return { ...conservado, candidate: nueva, candidateStreak: racha,
               reason: `esperando confirmacion (${racha}/${REPETICIONES})` };
    }
    // Por debajo de esto no hay repeticion que valga: es proximidad y poco mas.
    return { ...conservado, candidate: null,
             reason: `evidencia insuficiente ` +
                     `(${lectura.confidence.toFixed(2)} < ${UMBRAL_REPETIDO})` };
  }

  //: Confianza minima para publicar reloj y cuarto. Por debajo, `null`: un
  //: MM:SS de un banner o el cuarto de un mercado futuro no valen.
  const UMBRAL_CONTEXTO = 0.6;

  // ------------------------------------------------------ semantica del reloj
  //
  // No todas las casas muestran lo mismo en el reloj del marcador. BetPlay/
  // Kambi mostro "Q4 • 33:52" en un partido de baloncesto: 33:52 NO puede ser
  // el restante de un cuarto, porque ningun cuarto dura tanto.
  //
  // La aplicacion espera `clock` = RESTANTE DEL CUARTO ACTUAL (es lo que usa
  // `elapsed_period_seconds = duracion - restante`). Convertir un acumulado a
  // restante exige saber cuanto dura un cuarto y cuantos van, y eso lo sabe
  // GameRules, que vive en Python. La extension no lo sabe y no lo inventa:
  // manda lo que observo mas su semantica, y Python convierte.

  const CLOCK_SEMANTICS = {
    //: Cuenta atras del cuarto en curso. Es lo que la aplicacion usa tal cual.
    PERIOD_REMAINING: 'PERIOD_REMAINING',
    //: Tiempo de juego acumulado del partido. Python lo convierte con sus reglas.
    GAME_ELAPSED: 'GAME_ELAPSED',
    //: No se ha podido determinar. No se publica reloj.
    UNKNOWN: 'UNKNOWN',
  };

  //: Ningun cuarto dura mas de esto en ninguna competicion habitual. Superar
  //: el limite descarta PERIOD_REMAINING; quedar por debajo NO confirma nada.
  const MAX_QUARTER_SECONDS = 12 * 60;

  /**
   * Que representa el reloj observado, decidido por EVIDENCIA y no por fe.
   *
   * La magnitud solo puede DESCARTAR una semantica. La direccion la confirma:
   * ascendente = GAME_ELAPSED, descendente = PERIOD_REMAINING. Una lectura
   * aislada o estacionaria es ambigua salvo que el evento ya tuviera una
   * semantica confirmada. `periodo` evita confundir el reinicio de un countdown
   * al cambiar de cuarto con un reloj acumulado.
   */
  function decideClockSemantics(segundos, previa, periodo) {
    const cabeEnUnCuarto = segundos <= MAX_QUARTER_SECONDS;
    const anterior = previa && Number.isFinite(previa.rawSeconds) ? previa : null;
    const periodoActual = Number.isInteger(periodo) ? periodo : null;
    const periodoAnterior = anterior && Number.isInteger(anterior.period)
      ? anterior.period : null;
    const cambioDePeriodoDirecto = periodoActual !== null && periodoAnterior !== null &&
      periodoActual !== periodoAnterior;
    const cambioDePeriodo = cambioDePeriodoDirecto ||
      !!(anterior && anterior.periodTransitionPending);
    const confirmada = anterior &&
      [CLOCK_SEMANTICS.GAME_ELAPSED, CLOCK_SEMANTICS.PERIOD_REMAINING]
        .includes(anterior.semantics);

    if (!anterior) {
      return CLOCK_SEMANTICS.UNKNOWN;
    }
    if (segundos === anterior.rawSeconds) {
      // Reloj parado: no aporta informacion nueva, se mantiene lo que habia.
      return confirmada ? anterior.semantics : CLOCK_SEMANTICS.UNKNOWN;
    }

    const sube = segundos > anterior.rawSeconds;
    if (cambioDePeriodo) {
      if (!confirmada) return CLOCK_SEMANTICS.UNKNOWN;
      if (anterior.semantics === CLOCK_SEMANTICS.GAME_ELAPSED) {
        // El acumulado no se reinicia entre cuartos.
        return sube ? CLOCK_SEMANTICS.GAME_ELAPSED : CLOCK_SEMANTICS.UNKNOWN;
      }
      // Un countdown si se reinicia al total del cuarto nuevo. La extension
      // no conoce su duracion exacta, pero sabe que no puede exceder 12:00.
      return cabeEnUnCuarto ? CLOCK_SEMANTICS.PERIOD_REMAINING : CLOCK_SEMANTICS.UNKNOWN;
    }

    if (!cabeEnUnCuarto) {
      // Mas de un cuarto: solo puede ser un acumulado, y un acumulado sube.
      // Si baja, es un contador de otra cosa y no se toca.
      return sube ? CLOCK_SEMANTICS.GAME_ELAPSED : CLOCK_SEMANTICS.UNKNOWN;
    }
    return sube ? CLOCK_SEMANTICS.GAME_ELAPSED : CLOCK_SEMANTICS.PERIOD_REMAINING;
  }

  function formatClock(segundos) {
    const minutos = Math.floor(segundos / 60);
    const resto = segundos % 60;
    return `${String(minutos).padStart(2, '0')}:${String(resto).padStart(2, '0')}`;
  }

  /**
   * Convierte una observacion del reloj en lo que se publica.
   *
   * `clock` solo se rellena cuando la lectura ES el restante del cuarto. En
   * cualquier otro caso viaja el valor crudo con su semantica y decide Python,
   * que es quien conoce las reglas de la competicion.
   */
  function resolveClock(observacion, previa, periodo) {
    if (!observacion) return null;
    const semantica = decideClockSemantics(observacion.seconds, previa, periodo);
    const stationary = !!(previa && observacion.seconds === previa.rawSeconds);
    const semanticaPreviaConfirmada = previa &&
      [CLOCK_SEMANTICS.GAME_ELAPSED, CLOCK_SEMANTICS.PERIOD_REMAINING]
        .includes(previa.semantics);
    const periodChanged = !!(previa && Number.isInteger(previa.period) &&
      Number.isInteger(periodo) && previa.period !== periodo);
    let periodTransitionPending = !!(previa && previa.periodTransitionPending);
    if (periodChanged && semanticaPreviaConfirmada) periodTransitionPending = true;
    if (periodTransitionPending && previa) {
      const resetCountdown = previa.semantics === CLOCK_SEMANTICS.PERIOD_REMAINING &&
        observacion.seconds > previa.rawSeconds;
      const continuedElapsed = previa.semantics === CLOCK_SEMANTICS.GAME_ELAPSED &&
        observacion.seconds !== previa.rawSeconds;
      if (resetCountdown || continuedElapsed) periodTransitionPending = false;
    }
    const salida = {
      raw: observacion.raw,
      rawSeconds: observacion.seconds,
      semantics: semantica,
      source: observacion.source || 'heuristic',
      stationary,
      stationaryCount: stationary ? Number(previa.stationaryCount || 0) + 1 : 0,
      periodTransitionPending,
      value: null,
    };
    if (semantica === CLOCK_SEMANTICS.PERIOD_REMAINING) {
      salida.value = formatClock(observacion.seconds);
    }
    return salida;
  }

  /** Candidatos de una raiz, sin decidir nada todavia. */
  function collectCandidates(root, adapter, previous) {
    const anterior = previous || {};
    // Un solo recorrido del arbol para los tres, no uno por cada uno.
    const cache = new Map();
    let estructural = null;
    try {
      const leido = scoreboardLib.readScoreboard(root, adapter);
      if (leido && leido.found) estructural = leido;
    } catch (error) {
      estructural = null;      // el arbol cambio: se sigue con la heuristica
    }
    return {
      structured: estructural ? [estructural] : [],
      clock: findClockCandidates(root, adapter, cache),
      period: findPeriodCandidates(root, adapter, cache),
      score: findScoreCandidates(root, adapter, anterior.score, cache),
    };
  }

  /**
   * Estado del partido segun el DOM, o null en cada campo que no se pueda
   * afirmar. Nunca se rellena a medias con suposiciones.
   */
  function extractGameState(root, adapter, previous) {
    return decide(collectCandidates(root, adapter, previous), previous);
  }

  /**
   * Igual, pero mirando VARIAS raices (documento principal, shadow roots e
   * iframes del mismo origen). El marcador de BetPlay no tiene por que estar
   * en el documento principal, y buscarlo solo alli era quedarse ciego.
   *
   * Los candidatos de todas las raices compiten entre si con la misma vara de
   * medir: si dos raices dicen cosas distintas con la misma confianza, la
   * respuesta es "no se sabe", no "la primera que aparezca".
   */
  function extractGameStateFromRoots(roots, adapter, previous) {
    const todos = { structured: [], clock: [], period: [], score: [] };
    for (const root of roots || []) {
      if (!root) continue;
      let parciales;
      try {
        parciales = collectCandidates(root, adapter, previous);
      } catch (error) {
        continue;      // una raiz rota no deja sin marcador a las demas
      }
      todos.structured.push(...parciales.structured);
      todos.clock.push(...parciales.clock);
      todos.period.push(...parciales.period);
      todos.score.push(...parciales.score);
    }
    return decide(todos, previous);
  }

  /**
   * De todas las lecturas estructurales, la unica utilizable.
   *
   * Si dos raices distintas dicen cosas distintas, no se elige a dedo: se
   * renuncia y manda la heuristica, que ya sabe callarse ante la ambiguedad.
   */
  function elegirEstructural(lecturas) {
    const utiles = (lecturas || []).filter((l) => l && l.found && l.score);
    if (utiles.length !== 1) {
      if (utiles.length > 1) {
        const distintas = new Set(utiles.map((l) => `${l.score.scoreA}-${l.score.scoreB}`));
        if (distintas.size === 1) return utiles[0];    // la misma, duplicada
      }
      return null;
    }
    return utiles[0];
  }

  function decide(candidatos, previous) {
    const anterior = previous || {};

    // ------------------------------------------------ 1. lectura estructural
    //
    // Cuando la casa marca su marcador con semantica —una celda declarada
    // TOTAL por equipo, un bloque de reloj identificable— no hay nada que
    // estimar. Esa lectura MANDA sobre los candidatos genericos, que existen
    // para las casas que no dan esa evidencia.
    const estructural = elegirEstructural(candidatos.structured);

    // ------------------------------------------------------------- 2. cuarto
    // Se resuelve antes del reloj: el contexto de periodo distingue un
    // countdown que se reinicia de un GAME_ELAPSED que sigue acumulando.
    const cuartoHeuristico = pickBest(candidatos.period,
                                      anterior.period ? anterior.period.value : null,
                                      periodValidator, UMBRAL_CONTEXTO);
    const cuarto = estructural && estructural.period !== null &&
                   estructural.period !== undefined
      ? { value: estructural.period, confidence: 1, reason: '',
          raw: `Q${estructural.period}`,
          reasons: ['cuarto leido del bloque de estado del marcador'] }
      : cuartoHeuristico;

    // -------------------------------------------------------------- 3. reloj
    let observacionReloj = null;
    if (estructural && estructural.clock) {
      observacionReloj = { ...estructural.clock, source: 'structural' };
    }
    const relojHeuristico = pickBest(candidatos.clock, anterior.clock,
                                     clockValidator, UMBRAL_CONTEXTO);
    if (!observacionReloj && relojHeuristico.value) {
      observacionReloj = { raw: relojHeuristico.value,
                           seconds: secondsOf(relojHeuristico.value),
                           source: 'heuristic' };
    }
    const reloj = resolveClock(observacionReloj, anterior.clock, cuarto.value);

    // ----------------------------------------------------------- 4. marcador
    let lecturaMarcador;
    if (estructural) {
      lecturaMarcador = {
        value: estructural.score,
        confidence: 1,
        reason: '',
        raw: `${estructural.score.scoreA}-${estructural.score.scoreB}`,
        strong: true,
        structural: true,
        reasons: estructural.reasons,
        warnings: estructural.warnings,
        teams: estructural.teams,
        node: estructural.container || null,
      };
    } else {
      lecturaMarcador = pickBest(candidatos.score, anterior.score, scoreValidator, 0);
    }
    // La estabilizacion se aplica IGUAL a la lectura estructural: leer bien la
    // estructura no autoriza a aceptar un retroceso imposible sin revisarlo.
    const marcador = stabilizeScore(lecturaMarcador, anterior.score);

    const estado = {};
    if (reloj && reloj.value) estado.clock = reloj.value;
    if (reloj && reloj.raw) {
      // UNKNOWN tambien viaja: distingue un reloj realmente ausente de uno
      // observado pero en revision, y evita retener una semantica contradicha.
      estado.clockRaw = reloj.raw;
      estado.clockSemantics = reloj.semantics;
    }
    if (cuarto.value) estado.period = cuarto.value;
    if (estructural && estructural.phase) estado.phase = estructural.phase;
    if (marcador.confirmed && marcador.value) {
      estado.scoreA = marcador.value.scoreA;
      estado.scoreB = marcador.value.scoreB;
    }
    const estructuraPublicable = estructural && marcador.confirmed && marcador.value &&
      marcador.status !== 'UNDER_REVIEW' &&
      marcador.value.scoreA === estructural.score.scoreA &&
      marcador.value.scoreB === estructural.score.scoreB;
    if (estructuraPublicable && estructural.teamA && estructural.teamB) {
      // El contrato conserva scoreA/scoreB para compatibilidad, y anade el
      // scoreboard observado completo. Los ritmos siguen calculandose en Python.
      estado.teamA = estructural.teamA;
      estado.teamB = estructural.teamB;
    }

    return {
      // Un gameState PARCIAL es valido: que no se sepa el marcador no puede
      // bloquear el mercado, y que no se sepa el reloj no puede inventarlo.
      gameState: Object.keys(estado).length ? estado : null,
      // La memoria puede conservar un valor confirmado durante un repintado,
      // pero eso no demuestra que el DOM siga mostrandolo. Solo una lectura
      // encontrada en ESTE recorrido puede renovar la frescura en Python.
      observed: !!(estructural || observacionReloj || cuarto.value || lecturaMarcador.value),
      // Los NODOS van aparte: el diagnostico viaja por `sendResponse` y un
      // nodo del DOM no se puede serializar. Aqui solo se guardan para poder
      // copiar la estructura del marcador desde el popup.
      nodes: { score: lecturaMarcador.node || null },
      structured: !!estructural,
      diagnostics: {
        clock: reloj
          ? { value: reloj.value, raw: reloj.raw, semantics: reloj.semantics,
              source: reloj.source,
              status: reloj.semantics === CLOCK_SEMANTICS.UNKNOWN
                ? 'UNDER_REVIEW'
                : ((estructural && estructural.phase === 'CLOCK_STOPPED') ||
                   reloj.stationaryCount >= 2 ? 'CLOCK_STOPPED' : 'CONFIRMED'),
              stationary: reloj.stationary,
              confidence: reloj.semantics === CLOCK_SEMANTICS.UNKNOWN ? 0 : 1,
              reason: reloj.semantics === CLOCK_SEMANTICS.UNKNOWN
                ? 'semantica del reloj sin determinar' : '' }
          : sinNodo(relojHeuristico),
        period: sinNodo(cuarto),
        score: {
          ...sinNodo(lecturaMarcador),
          status: marcador.status,
          confirmed: marcador.confirmed,
          published: marcador.confirmed ? marcador.value : null,
          candidate: marcador.candidate || null,
          reason: marcador.reason || lecturaMarcador.reason,
        },
        underReview: marcador.status === 'UNDER_REVIEW',
      },
      memory: {
        // Se recuerda el valor CRUDO y su semantica, no solo lo publicado: es
        // lo que permite decidir en la siguiente lectura si el reloj sube
        // (acumulado) o baja (restante).
        clock: reloj
          ? { seconds: reloj.value ? secondsOf(reloj.value) : null, value: reloj.value,
              raw: reloj.raw, rawSeconds: reloj.rawSeconds, semantics: reloj.semantics,
              period: cuarto.value || null, stationaryCount: reloj.stationaryCount,
              periodTransitionPending: reloj.periodTransitionPending }
          : anterior.clock,
        period: cuarto.value ? { value: cuarto.value } : anterior.period,
        score: {
          value: marcador.value,
          confirmed: marcador.confirmed,
          confidence: marcador.confidence,
          streak: marcador.streak,
          candidate: marcador.candidate || null,
          candidateStreak: marcador.candidateStreak || 0,
          pending: marcador.pending || null,
          pendingStreak: marcador.pendingStreak || 0,
        },
      },
    };
  }

  /** Copia sin el nodo del DOM, que no se puede serializar. */
  function sinNodo(lectura) {
    const copia = { ...lectura };
    delete copia.node;
    delete copia.nodes;
    delete copia.container;
    if (copia.rejected) delete copia.rejected.nodes;
    return copia;
  }

  function secondsOf(reloj) {
    const match = String(reloj).match(CLOCK_RE);
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
  }

  return { CLOCK_RE, MAX_SCORE, MAX_JUMP, CLOCK_SEMANTICS, MAX_QUARTER_SECONDS,
           decideClockSemantics, resolveClock, elegirEstructural,
           UMBRAL_INICIAL, UMBRAL_REPETIDO,
           UMBRAL_CONTINUACION,
           REPETICIONES, pareceNombreDeEquipo, periodoDe, continuaDe,
           findClockCandidates, findPeriodCandidates, findScoreCandidates,
           pickBest, stabilizeScore, clockValidator, periodValidator,
           scoreValidator, collectCandidates, findScoreboardContainers,
           extractGameState,
           extractGameStateFromRoots };
});
