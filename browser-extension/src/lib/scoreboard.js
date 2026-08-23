/**
 * Lectura ESTRUCTURAL del marcador, cuando la casa lo publica con semantica.
 *
 * Por que existe este modulo, con un caso real delante:
 *
 * BetPlay usa la plataforma Kambi, que marca su marcador asi (resumido):
 *
 *     section.KambiBC-scoreboard-container-template[aria-label="Marcador en vivo"]
 *       header ... div.KambiBC-event-match-clock__wrapper
 *                    span "Q4"  span "•"  span "33:52"
 *       section.KambiBC-scoreboard-row
 *         div.KambiBC-scoreboard-team-label  span "Dallas Wings (F)"
 *         div.KambiBC-scoreboard-grid-row
 *           span.KambiBC-scoreboard-grid-item        "18"
 *           span.KambiBC-scoreboard-grid-item        "24"
 *           span.KambiBC-scoreboard-grid-item        "24"
 *           span.KambiBC-scoreboard-grid-item        "10"
 *           span.KambiBC-scoreboard-grid-score
 *                .KambiBC-scoreboard-grid-item       "76"
 *       section.KambiBC-scoreboard-row
 *         ... "Indiana Fever (F)" ... 22 20 19 8     "69"
 *
 * La heuristica general emparejaba numeros CONSECUTIVOS en orden de documento,
 * y el par que cruza las dos filas es (76, 22): el TOTAL de un equipo con el
 * PARCIAL del primer cuarto del otro. Peor: como los dos numeros estaban en un
 * contenedor de marcador y cada uno colgaba de un equipo distinto, la lectura
 * se daba por evidencia fuerte y se publicaba CONFIRMED. El par correcto,
 * (76, 69), no llegaba siquiera a generarse: no son consecutivos.
 *
 * La diferencia decisiva la da la propia pagina:
 *
 *     KambiBC-scoreboard-grid-item    celda generica -> PARCIAL de un cuarto
 *     KambiBC-scoreboard-grid-score   celda marcada  -> TOTAL del equipo
 *
 * Cuando esa evidencia existe no hay nada que estimar: se lee. Este modulo lee
 * esa estructura y NO adivina. Si falta cualquier pieza (no hay celda marcada
 * como total, no hay exactamente dos filas, los nombres coinciden) devuelve
 * `found: false` y quien llame se queda con la heuristica general.
 *
 * Todo aqui es funcion pura sobre el adaptador de arbol: sirve igual para el
 * DOM real y para los arboles de prueba.
 */
(function (root, factory) {
  const api = factory(
    typeof require === 'function' ? require('./text.js') : root.VDIAG.text
  );
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { scoreboard: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function (text) {
  'use strict';

  const CLOCK_RE = /^(\d{1,2}):([0-5]\d)$/;
  const MAX_SCORE = 250;
  //: Periodos posibles contando prorrogas: no se cierra en 4 para que el
  //: overtime no rompa la lectura.
  const MAX_PERIOD = 9;
  const GAME_PHASES = {
    CLOCK_STOPPED: 'CLOCK_STOPPED',
    PERIOD_END: 'PERIOD_END',
    HALFTIME: 'HALFTIME',
    GAME_OVER: 'GAME_OVER',
  };

  //: Tope de nodos que se inspeccionan dentro de un contenedor de marcador.
  //: La busqueda de filas mira las hojas de cada nodo, asi que si un selector
  //: demasiado generoso llegara a casar con media pagina el coste se
  //: dispararia. Un marcador de verdad tiene decenas de nodos, no cientos.
  const MAX_SCOREBOARD_NODES = 400;

  // ----------------------------------------------------------- vocabulario

  //: El bloque entero del marcador. "scoreboard" o un aria-label explicito.
  const SCOREBOARD_CONTAINER =
    /\bscoreboard\b|score-?board|\bmarcador\b|marcador en vivo|live-?score|match-?score/;

  /**
   * La celda del TOTAL. Es la pieza clave de todo el modulo.
   *
   * OJO con el limite de palabra: en "kambibc-scoreboard-grid-item" la
   * subcadena "score" va seguida de "b", asi que `-score\b` NO casa; en
   * "kambibc-scoreboard-grid-score" si. Esa asimetria es justo lo que separa
   * un parcial de un total.
   */
  const TOTAL_CELL =
    /\bgrid-score\b|\bscore-?total\b|\btotal-?score\b|\bmatch-score\b|\bteam-score\b|\bfinal-score\b|\bscore-value\b|-score\b/;

  //: Celda generica de la rejilla: el parcial de un cuarto.
  const PARTIAL_CELL =
    /\bgrid-item\b|\bgriditem\b|\bperiod-score\b|\bquarter-score\b|\bgrid-cell\b/;

  //: El bloque de reloj/estado dentro del marcador.
  const CLOCK_BLOCK =
    /match-clock|event-clock|game-clock|\bclock\b|\btimer\b|match-time|\bmatch-state\b|\bgame-state\b/;

  //: Palabras que descartan un texto como nombre de equipo.
  const NO_ES_EQUIPO =
    /\b(total|puntos|cuota|apuesta|mercado|mas de|menos de|over|under|handicap|ganador|linea|cuarto|periodo|mitad|prorroga|iniciar|sesion|deposito|saldo|retirar|combinada|acumulada)\b/;

  // ------------------------------------------------------- recorrido comun

  function attrTextOf(node, adapter) {
    if (!adapter || typeof adapter.attrText !== 'function') return '';
    return adapter.attrText(node) || '';
  }

  function walk(node, adapter, visit, chain) {
    const padres = chain || [];
    visit(node, padres);
    for (const hijo of adapter.children(node)) walk(hijo, adapter, visit, [node, ...padres]);
  }

  /** Hojas con texto de un subarbol, con su cadena de padres. */
  function leavesOf(root, adapter) {
    const hojas = [];
    walk(root, adapter, (node, chain) => {
      if (adapter.children(node).length) return;
      const valor = (adapter.text(node) || '').trim();
      if (valor) hojas.push({ node, chain, text: valor });
    });
    return hojas;
  }

  /** De un conjunto de nodos anidados, se queda con los MAS INTERNOS. */
  function innermost(items) {
    return items.filter(
      (uno) => !items.some((otro) => otro !== uno && (otro.chain || []).includes(uno.node)));
  }

  /** ¿Este texto puede ser el nombre de un equipo? */
  function looksLikeTeamName(valor) {
    const crudo = String(valor || '').trim();
    if (crudo.length < 3 || crudo.length > 40) return false;
    if (/^\d/.test(crudo)) return false;
    const letras = (crudo.match(/[a-zA-ZáéíóúñÁÉÍÓÚÑ]/g) || []).length;
    if (letras < 3) return false;
    if (/\d{2,}/.test(crudo)) return false;                 // "Cuota 1.85", "12:34"
    return !NO_ES_EQUIPO.test(text.normalize(crudo));
  }

  // ------------------------------------------------------------- las celdas

  /** ¿Es esta hoja la celda del TOTAL de su fila? */
  function isTotalCell(node, adapter) {
    return TOTAL_CELL.test(attrTextOf(node, adapter));
  }

  /**
   * ¿Es esta hoja una celda PARCIAL?
   *
   * El total manda: la celda de Kambi lleva las dos clases a la vez
   * (`grid-score grid-item`) y tiene que contar como total, no como parcial.
   */
  function isPartialCell(node, adapter) {
    if (isTotalCell(node, adapter)) return false;
    return PARTIAL_CELL.test(attrTextOf(node, adapter));
  }

  function numberOfText(raw) {
    const value = String(raw == null ? '' : raw).trim();
    if (!/^\d{1,3}$/.test(value)) return null;
    const valor = Number(value);
    return Number.isInteger(valor) && valor >= 0 && valor <= MAX_SCORE ? valor : null;
  }

  function numberOf(hoja) {
    return numberOfText(hoja && hoja.text);
  }

  /**
   * Celdas semanticas de una fila, incluidas las vacias.
   *
   * `leavesOf` omite hojas sin texto, que es correcto para nombres y reloj,
   * pero perder una celda vacia desplazaria Q3 a la columna de Q2. Aqui la
   * existencia de la celda es evidencia aunque su valor siga desconocido.
   */
  function scoreCellsOf(root, adapter) {
    const celdas = [];
    walk(root, adapter, (node, chain) => {
      const total = isTotalCell(node, adapter);
      const partial = !total && isPartialCell(node, adapter);
      if (!total && !partial) return;
      celdas.push({ node, chain, total, partial,
                     value: numberOfText(adapter.text(node)) });
    });
    return innermost(celdas);
  }

  function periodLabel(index, regulationPeriods) {
    const regulation = Number.isInteger(regulationPeriods) ? regulationPeriods : 4;
    return index < regulation ? `Q${index + 1}` : `OT${index - regulation + 1}`;
  }

  function periodsFromPartials(partials, regulationPeriods, observedPeriod) {
    const periods = {};
    const regulation = Number.isInteger(regulationPeriods) ? regulationPeriods : 4;
    // Las cuatro primeras columnas de la rejilla son Q1..Q4. Una columna
    // posterior solo puede publicarse como OT si el bloque de estado confirma
    // que ese overtime ya existe. Asi una columna auxiliar de Kambi (mitad,
    // faltas, etc.) nunca se convierte en OT solo por estar en quinta posicion.
    const lastObserved = Number.isInteger(observedPeriod) ? observedPeriod : regulation;
    (partials || []).forEach((value, index) => {
      if (index < regulation) {
        periods[periodLabel(index, regulation)] = value;
        return;
      }
      const absolutePeriod = index + 1;
      if (lastObserved > regulation && absolutePeriod <= lastObserved) {
        periods[periodLabel(index, regulation)] = value;
      }
    });
    return periods;
  }

  // --------------------------------------------------------- filas de equipo

  /**
   * Filas de equipo dentro de un contenedor.
   *
   * Una fila es el nodo MAS INTERNO que contiene exactamente un nombre de
   * equipo y exactamente una celda de total. Definirla asi, y no por el nombre
   * de su clase, evita atarse a `KambiBC-scoreboard-row` y sigue funcionando
   * si la casa renombra sus clases.
   */
  function findTeamRows(container, adapter) {
    const candidatas = [];
    let visitados = 0;
    walk(container, adapter, (node, chain) => {
      visitados += 1;
      if (visitados > MAX_SCOREBOARD_NODES) return;

      const totales = [];
      const parciales = [];
      //: Un Set, y no un contador: la casa puede repetir el nombre del equipo
      //: (version movil y version escritorio en el mismo bloque) y eso sigue
      //: siendo UN equipo. Lo que descalifica la fila es que aparezcan dos
      //: nombres DISTINTOS, porque entonces no es la fila de nadie.
      const nombres = new Set();

      for (const celda of scoreCellsOf(node, adapter)) {
        if (celda.total && celda.value !== null) totales.push(celda.value);
        else if (celda.partial) parciales.push(celda.value);
      }
      for (const hoja of leavesOf(node, adapter)) {
        if (isTotalCell(hoja.node, adapter) || isPartialCell(hoja.node, adapter)) continue;
        if (looksLikeTeamName(hoja.text)) nombres.add(hoja.text);
      }

      if (totales.length !== 1 || nombres.size !== 1) return;
      candidatas.push({ node, chain, name: [...nombres][0],
                        total: totales[0], partials: parciales });
    });
    return innermost(candidatas);
  }

  // ------------------------------------------------------- reloj y periodo

  function periodFromText(valor) {
    const normalizado = text.normalizeOrdinals(valor || '');
    if (!normalizado || normalizado.length > 24) return null;
    const overtime = normalizado.match(/^(?:ot|overtime|prorroga)\s*([1-9])?$/);
    if (overtime) return 4 + Number(overtime[1] || 1);
    const directo = normalizado.match(/^q\s*([1-9])$/) ||
                    normalizado.match(/^([1-9])\s*q$/) ||
                    normalizado.match(/\b([1-9])\s+(?:cuarto|periodo|parcial|quarter)\b/) ||
                    normalizado.match(/\b(?:cuarto|periodo|parcial|quarter)\s+([1-9])\b/);
    if (!directo) return null;
    const periodo = Number(directo[1]);
    return periodo >= 1 && periodo <= MAX_PERIOD ? periodo : null;
  }

  function phaseFromText(valor) {
    const normalizado = text.normalize(valor || '').trim();
    if (!normalizado || normalizado.length > 80) return null;
    if (/^(?:descanso|medio tiempo|half ?time|intermedio|entretiempo)$/.test(normalizado)) {
      return GAME_PHASES.HALFTIME;
    }
    if (/^(?:tiempo muerto|time ?out|pausa|juego pausado)$/.test(normalizado)) {
      return GAME_PHASES.CLOCK_STOPPED;
    }
    if (/^(?:fin(?:al)? (?:del )?(?:cuarto|periodo)|end of quarter|quarter end)$/.test(normalizado)) {
      return GAME_PHASES.PERIOD_END;
    }
    if (/^(?:partido terminado|fin del partido|game over|full time)$/.test(normalizado)) {
      return GAME_PHASES.GAME_OVER;
    }
    return null;
  }

  /**
   * Periodo y reloj del bloque de estado, NO de cualquier sitio del marcador.
   *
   * Importa acotarlo: la rejilla de parciales suele llevar una cabecera con
   * "Q1 Q2 Q3 Q4", y esos textos no dicen en que cuarto va el partido. El
   * bloque del reloj si.
   */
  function readClockBlock(container, adapter) {
    const bloques = [];
    walk(container, adapter, (node, chain) => {
      if (CLOCK_BLOCK.test(attrTextOf(node, adapter))) bloques.push({ node, chain });
    });
    if (!bloques.length) return { period: null, clock: null, phase: null, reasons: [] };

    const vistos = new Set();
    const periodos = new Set();
    const relojes = new Set();
    const fases = new Set();
    for (const bloque of bloques) {
      for (const hoja of leavesOf(bloque.node, adapter)) {
        if (vistos.has(hoja.node)) continue;
        vistos.add(hoja.node);
        const periodo = periodFromText(hoja.text);
        if (periodo !== null) periodos.add(periodo);
        const match = hoja.text.match(CLOCK_RE);
        if (match) relojes.add(hoja.text.trim());
        const fase = phaseFromText(hoja.text);
        if (fase !== null) fases.add(fase);
      }
    }

    const razones = [];
    // Dos valores distintos son una ambiguedad, no una eleccion a dedo.
    let periodo = null;
    if (periodos.size === 1) {
      periodo = [...periodos][0];
      razones.push('cuarto leido del bloque de reloj del marcador');
    } else if (periodos.size > 1) {
      razones.push(`cuarto ambiguo en el bloque de reloj: ${[...periodos].join(', ')}`);
    }

    let reloj = null;
    if (relojes.size === 1) {
      const crudo = [...relojes][0];
      const match = crudo.match(CLOCK_RE);
      reloj = { raw: crudo, seconds: Number(match[1]) * 60 + Number(match[2]) };
      razones.push('reloj leido del bloque de reloj del marcador');
    } else if (relojes.size > 1) {
      razones.push(`reloj ambiguo en el bloque de reloj: ${[...relojes].join(', ')}`);
    }

    let fase = null;
    if (fases.size === 1) {
      fase = [...fases][0];
      razones.push('fase leida del bloque de reloj del marcador');
    } else if (fases.size > 1) {
      razones.push(`fase ambigua en el bloque de reloj: ${[...fases].join(', ')}`);
    }

    return { period: periodo, clock: reloj, phase: fase, reasons: razones };
  }

  // -------------------------------------------------------- lectura completa

  /**
   * Lee el marcador estructural de un arbol.
   *
   * Devuelve siempre un objeto; `found` dice si la lectura es utilizable. Si
   * no lo es, `reasons` explica por que, que es lo que permite entender en el
   * diagnostico si la casa cambio su maquetacion.
   */
  function readScoreboard(root, adapter) {
    const contenedores = [];
    walk(root, adapter, (node, chain) => {
      if (!SCOREBOARD_CONTAINER.test(attrTextOf(node, adapter))) return;
      const filas = findTeamRows(node, adapter);
      if (filas.length !== 2) return;
      contenedores.push({ node, chain, rows: filas });
    });

    if (!contenedores.length) {
      return { found: false, reasons: ['sin marcador estructural reconocible'] };
    }
    const utiles = innermost(contenedores);
    if (utiles.length > 1) {
      // Varios marcadores en pantalla: no se elige uno a dedo.
      return { found: false, container: null,
               reasons: [`${utiles.length} marcadores estructurales a la vez`] };
    }

    const marcador = utiles[0];
    const [filaA, filaB] = marcador.rows;
    const razones = ['marcador estructural: una celda de total por equipo'];
    const avisos = [];

    if (filaA.name === filaB.name) {
      return { found: false, container: marcador.node,
               reasons: ['las dos filas nombran al mismo equipo'] };
    }

    const estado = readClockBlock(marcador.node, adapter);
    const periodsA = periodsFromPartials(filaA.partials, 4, estado.period);
    const periodsB = periodsFromPartials(filaB.partials, 4, estado.period);

    // Coherencia: los parciales deberian sumar el total. Refuerza la lectura,
    // pero NO manda: con prorroga, cuartos incompletos o celdas vacias la suma
    // puede no cuadrar y la clase del total sigue siendo la evidencia buena.
    for (const [fila, periods] of [[filaA, periodsA], [filaB, periodsB]]) {
      const valores = Object.values(periods);
      if (!valores.length) continue;
      if (fila.partials.length > valores.length) {
        razones.push(`${fila.name}: ${fila.partials.length - valores.length} columna(s) ` +
                     'adicional(es) sin identidad de periodo se omitieron');
      }
      if (valores.some((value) => value === null)) {
        razones.push(`${fila.name}: hay parciales todavia desconocidos`);
        continue;
      }
      const suma = valores.reduce((acc, n) => acc + n, 0);
      if (suma === fila.total) razones.push(`${fila.name}: los parciales suman el total`);
      else avisos.push(`${fila.name}: los parciales suman ${suma} y el total dice ${fila.total}`);
    }

    return {
      found: true,
      container: marcador.node,
      rows: [filaA, filaB],
      teams: [filaA.name, filaB.name],
      score: { scoreA: filaA.total, scoreB: filaB.total },
      teamA: { name: filaA.name, total: filaA.total,
               periods: periodsA },
      teamB: { name: filaB.name, total: filaB.total,
               periods: periodsB },
      period: estado.period,
      clock: estado.clock,
      phase: estado.phase,
      reasons: [...razones, ...estado.reasons],
      warnings: avisos,
    };
  }

  return { CLOCK_RE, MAX_SCORE, MAX_PERIOD, MAX_SCOREBOARD_NODES, GAME_PHASES,
           SCOREBOARD_CONTAINER, TOTAL_CELL,
           PARTIAL_CELL, CLOCK_BLOCK, looksLikeTeamName, isTotalCell, isPartialCell,
           findTeamRows, scoreCellsOf, periodLabel, periodsFromPartials,
           periodFromText, phaseFromText, readClockBlock, readScoreboard, leavesOf };
});
