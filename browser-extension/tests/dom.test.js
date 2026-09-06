/**
 * Regresion del fallo REAL capturado en BetPlay:
 *
 *     Cannot read properties of null (reading 'createTreeWalker')
 *
 * La causa: `element.ownerDocument.createTreeWalker(...)` con `element` siendo
 * un Document, cuyo `ownerDocument` es null POR DEFINICION. Como el escaneo
 * empieza precisamente por el documento principal, la raiz mas importante
 * moria antes de leer un solo mercado.
 *
 * Estas pruebas cubren TODAS las clases de raiz que admite `collectRoots`, mas
 * los casos feos de una pagina viva: iframes que desaparecen, nodos que se
 * desconectan y subarboles reemplazados a mitad del recorrido.
 */
const test = require('node:test');
const assert = require('node:assert');
const dom = require('../src/lib/dom.js');
const { createDocument, el, iframe, FakeDocumentFragment, FakeText,
        FakeElement } = require('./fake_dom.js');

// ------------------------------------------------- reproduccion del fallo real

test('reproduccion: la forma anterior revienta justo con la raiz principal', () => {
  const doc = createDocument();
  // Esto es literalmente lo que hacia extractText antes de la correccion.
  assert.throws(
    () => doc.ownerDocument.createTreeWalker(doc, 0x4),
    /Cannot read properties of null \(reading 'createTreeWalker'\)/);
});

// ------------------------------------------------------------ documentForNode

test('A. el documento principal resuelve a si mismo (ownerDocument es null)', () => {
  const doc = createDocument();
  assert.equal(doc.ownerDocument, null, 'el DOM real tambien lo deja en null');
  assert.equal(dom.documentForNode(doc), doc);
});

test('B. un elemento resuelve a su ownerDocument', () => {
  const doc = createDocument();
  const div = el(doc, 'div', {}, ['texto']);
  doc.body.appendChild(div);
  assert.equal(dom.documentForNode(div), doc);
});

test('C. un shadow root resuelve al documento de su host', () => {
  const doc = createDocument();
  const host = el(doc, 'my-widget');
  doc.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'open' });
  assert.equal(dom.documentForNode(shadow), doc);
});

test('D. un DocumentFragment suelto resuelve a su documento', () => {
  const doc = createDocument();
  const fragmento = new FakeDocumentFragment();
  fragmento.ownerDocument = doc;
  assert.equal(dom.documentForNode(fragmento), doc);
});

test('E. el documento de un iframe del mismo origen resuelve a si mismo', () => {
  const doc = createDocument();
  const { frame, doc: interno } = iframe(doc, 'https://betplay.com.co/widget');
  doc.body.appendChild(frame);
  assert.equal(dom.documentForNode(interno), interno);
});

test('H. una raiz nula no lanza: devuelve null', () => {
  assert.equal(dom.documentForNode(null), null);
  assert.equal(dom.documentForNode(undefined), null);
  assert.equal(dom.documentForNode({}), null);
});

test('un nodo cuyo documento no sabe crear walkers se descarta', () => {
  const roto = { nodeType: 1, ownerDocument: { createTreeWalker: undefined } };
  assert.equal(dom.documentForNode(roto), null);
});

// ----------------------------------------------------------------- extractText

test('A. extractText sobre el Document principal NO lanza y lee el texto', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'section', {}, [
    el(doc, 'h3', {}, ['Total de puntos - Cuarto 4']),
    el(doc, 'div', {}, ['Mas de 44.5', '1.75']),
  ]));
  const texto = dom.extractText(doc);
  assert.match(texto, /Total de puntos - Cuarto 4/);
  assert.match(texto, /1\.75/);
  // Las celdas no se pegan entre si: por eso no se usa textContent a secas.
  assert.match(texto, /Mas de 44\.5\n1\.75/);
});

test('B. extractText sobre un elemento normal', () => {
  const doc = createDocument();
  const div = el(doc, 'div', {}, ['Menos de 44.5', '1.90']);
  doc.body.appendChild(div);
  assert.equal(dom.extractText(div), 'Menos de 44.5\n1.90');
});

test('C. extractText sobre un ShadowRoot', () => {
  const doc = createDocument();
  const host = el(doc, 'bp-market');
  doc.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'open' });
  shadow.appendChild(el(doc, 'span', {}, ['Mas de 163.5']));
  assert.equal(dom.extractText(shadow), 'Mas de 163.5');
});

test('D. extractText sobre un DocumentFragment', () => {
  const doc = createDocument();
  const fragmento = new FakeDocumentFragment();
  fragmento.ownerDocument = doc;
  fragmento.appendChild(el(doc, 'p', {}, ['fragmento']));
  assert.equal(dom.extractText(fragmento), 'fragmento');
});

test('E. extractText sobre el documento de un iframe del mismo origen', () => {
  const doc = createDocument();
  const { frame, doc: interno } = iframe(doc, 'https://betplay.com.co/live');
  doc.body.appendChild(frame);
  interno.body.appendChild(el(interno, 'div', {}, ['Cuarto 3', '56', '69']));
  assert.equal(dom.extractText(interno), 'Cuarto 3\n56\n69');
});

test('F. un documento de iframe ya desmontado no lanza', () => {
  const doc = createDocument();
  const { frame, doc: interno } = iframe(doc, 'https://betplay.com.co/live');
  doc.body.appendChild(frame);
  interno.body.appendChild(el(interno, 'div', {}, ['algo']));
  interno.destroy();                         // el navegador tira el documento
  assert.equal(dom.isUsableRoot(interno), false);
  assert.doesNotThrow(() => dom.extractText(interno));
});

test('G. un elemento desconectado despues de descubrirlo sigue leyendose sin lanzar', () => {
  const doc = createDocument();
  const div = el(doc, 'div', {}, ['Mas de 44.5']);
  doc.body.appendChild(div);
  div.remove();
  assert.equal(dom.isUsableRoot(div), false, 'como raiz ya no sirve');
  assert.equal(dom.extractText(div), 'Mas de 44.5', 'pero leerlo no puede reventar');
});

test('H. extractText de null devuelve cadena vacia', () => {
  assert.equal(dom.extractText(null), '');
  assert.equal(dom.extractText(undefined), '');
});

test('I. si el DOM se reemplaza a mitad del recorrido se termina a mano', () => {
  const doc = createDocument();
  doc.body.appendChild(el(doc, 'div', {}, ['uno', 'dos', 'tres']));
  doc.breakWalkerAt = 1;                     // el walker revienta en el segundo
  const texto = dom.extractText(doc);
  assert.equal(texto, 'uno\ndos\ntres', 'el recorrido de reserva lee el arbol entero');
});

test('un nodo sin documento resoluble se lee con el recorrido manual', () => {
  const huerfano = new FakeElement('div');
  const texto = new FakeText('sin documento');
  huerfano.appendChild(texto);
  assert.equal(dom.documentForNode(huerfano), null);
  assert.equal(dom.extractText(huerfano), 'sin documento');
});

// ------------------------------------------------------------------ auxiliares

test('showTextFor prefiere el NodeFilter del documento recorrido', () => {
  const doc = createDocument();
  doc.defaultView.NodeFilter.SHOW_TEXT = 999;   // valor inventado a proposito
  assert.equal(dom.showTextFor(doc), 999);
});

test('showTextFor cae en la constante de la especificacion si no hay ventana', () => {
  assert.equal(dom.showTextFor({ defaultView: null }), 0x4);
  assert.equal(dom.showTextFor(null), 0x4);
});

test('ownText lee solo los hijos de texto directos', () => {
  const doc = createDocument();
  const div = el(doc, 'div', {}, ['propio', el(doc, 'span', {}, ['del hijo'])]);
  assert.equal(dom.ownText(div), 'propio');
});

test('isUsableRoot acepta las raices vivas y rechaza las muertas', () => {
  const doc = createDocument();
  const host = el(doc, 'x-host');
  doc.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'open' });

  assert.equal(dom.isUsableRoot(doc), true);
  assert.equal(dom.isUsableRoot(shadow), true);
  assert.equal(dom.isUsableRoot(doc.body), true);
  assert.equal(dom.isUsableRoot(null), false);
  assert.equal(dom.isUsableRoot({ nodeType: 3 }), false);
});
