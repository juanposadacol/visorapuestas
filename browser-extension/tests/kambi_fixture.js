/**
 * Fixture compartido: el scoreboard REAL de BetPlay/Kambi observado en Edge.
 *
 * Vive fuera de los ficheros `*.test.js` a proposito: lo usan varias suites y
 * no debe ejecutarse como una suite mas.
 *
 * Estructura observada (resumida):
 *
 *     section.KambiBC-scoreboard-container-template[aria-label="Marcador en vivo"]
 *       header ... div.KambiBC-event-match-clock__wrapper
 *                    span "Q4"  span "•"  span "33:52"
 *       section.KambiBC-scoreboard-row
 *         div.KambiBC-scoreboard-team-label  span "Dallas Wings (F)"
 *         div.KambiBC-scoreboard-grid-row
 *           span.KambiBC-scoreboard-grid-item   "18" "24" "24" "10"
 *           span.KambiBC-scoreboard-grid-score
 *                .KambiBC-scoreboard-grid-item  "76"
 *       section.KambiBC-scoreboard-row
 *         ... "Indiana Fever (F)" ... 22 20 19 8  "69"
 */
'use strict';

const { createDocument, el } = require('./fake_dom.js');

/** Una fila de equipo tal y como la monta Kambi: parciales + total marcado. */
function filaKambi(doc, equipo, parciales, total, opciones) {
  const o = opciones || {};
  const celdas = parciales.map((n) => el(doc, 'span', {
    class: 'KambiBC-scoreboard-grid-item', role: 'griditem',
  }, [String(n)]));
  if (total !== null && total !== undefined) {
    celdas.push(el(doc, 'span', {
      // La celda del total lleva LAS DOS clases: por eso el total tiene que
      // ganar al parcial, y no al reves.
      class: o.claseTotal || 'KambiBC-scoreboard-grid-score KambiBC-scoreboard-grid-item',
      role: 'griditem',
    }, [String(total)]));
  }
  return el(doc, 'section', { class: 'KambiBC-scoreboard-row' }, [
    el(doc, 'a', { class: 'KambiBC-scoreboard-team-link' }, [
      el(doc, 'div', { class: 'KambiBC-scoreboard-team-label' }, [
        el(doc, 'span', {}, [equipo]),
      ]),
    ]),
    el(doc, 'div', {}, [
      el(doc, 'div', { class: 'KambiBC-scoreboard-grid-row', role: 'gridrow' }, celdas),
    ]),
  ]);
}

/** El scoreboard completo observado en BetPlay el 21/08/2026. */
function scoreboardKambi(doc, opciones) {
  const o = {
    periodo: 'Q4', reloj: '33:52',
    equipoA: 'Dallas Wings (F)', parcialesA: [18, 24, 24, 10], totalA: 76,
    equipoB: 'Indiana Fever (F)', parcialesB: [22, 20, 19, 8], totalB: 69,
    ...(opciones || {}),
  };
  const cabecera = [];
  if (o.periodo || o.reloj) {
    cabecera.push(el(doc, 'header', { class: 'KambiBC-scoreboard-header' }, [
      el(doc, 'div', { class: 'KambiBC-scoreboard-match-info' }, [
        el(doc, 'div', { class: 'KambiBC-event-match-clock__wrapper' }, [
          el(doc, 'div', { class: 'KambiBC-match-clock__inner' }, [
            ...(o.periodo ? [el(doc, 'span', {}, [o.periodo])] : []),
            el(doc, 'span', { class: 'KambiBC-match-clock__divider' }, ['•']),
            ...(o.reloj ? [el(doc, 'span', {}, [o.reloj])] : []),
          ]),
        ]),
      ]),
    ]));
  }
  return el(doc, 'section', {
    class: 'KambiBC-scoreboard-container-template',
    'aria-label': 'Marcador en vivo',
  }, [
    ...cabecera,
    filaKambi(doc, o.equipoA, o.parcialesA, o.totalA, o),
    filaKambi(doc, o.equipoB, o.parcialesB, o.totalB, o),
  ]);
}

/** El marcador de Kambi ya colgado del body de un documento nuevo. */
function documentoConScoreboard(opciones) {
  const doc = createDocument();
  doc.body.appendChild(scoreboardKambi(doc, opciones));
  return doc;
}

module.exports = { filaKambi, scoreboardKambi, documentoConScoreboard };
