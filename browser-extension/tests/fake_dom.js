/**
 * DOM de juguete para las pruebas, sin dependencias externas.
 *
 * No pretende ser un navegador: implementa exactamente lo que el codigo de la
 * extension usa (nodeType, ownerDocument, childNodes, children, host,
 * isConnected, defaultView.NodeFilter y createTreeWalker) para poder reproducir
 * en `node --test` los fallos REALES que aparecieron en BetPlay, incluidos los
 * casos feos: documento de iframe que se desmonta, subarbol reemplazado a
 * mitad del recorrido y nodos desconectados.
 */
'use strict';

const NODE = { ELEMENT: 1, TEXT: 3, DOCUMENT: 9, DOCUMENT_FRAGMENT: 11 };

class FakeNode {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.childNodes = [];
    this.parentNode = null;
    this.ownerDocument = null;
  }

  get children() {
    return this.childNodes.filter((n) => n.nodeType === NODE.ELEMENT);
  }

  get isConnected() {
    let actual = this;
    while (actual) {
      if (actual.nodeType === NODE.DOCUMENT) return true;
      if (actual.nodeType === NODE.DOCUMENT_FRAGMENT && actual.host) {
        actual = actual.host;
        continue;
      }
      if (!actual.parentNode) return false;
      actual = actual.parentNode;
    }
    return false;
  }

  appendChild(hijo) {
    hijo.parentNode = this;
    hijo.ownerDocument = this.nodeType === NODE.DOCUMENT ? this : this.ownerDocument;
    propagarDocumento(hijo, hijo.ownerDocument);
    this.childNodes.push(hijo);
    return hijo;
  }

  remove() {
    if (!this.parentNode) return;
    const indice = this.parentNode.childNodes.indexOf(this);
    if (indice !== -1) this.parentNode.childNodes.splice(indice, 1);
    this.parentNode = null;
  }
}

function propagarDocumento(node, doc) {
  for (const hijo of node.childNodes) {
    hijo.ownerDocument = doc;
    propagarDocumento(hijo, doc);
  }
}

class FakeText extends FakeNode {
  constructor(valor) {
    super(NODE.TEXT);
    this.nodeValue = valor;
  }
}

class FakeElement extends FakeNode {
  constructor(tagName, atributos) {
    super(NODE.ELEMENT);
    this.tagName = String(tagName || 'div').toUpperCase();
    this.attributes = { ...(atributos || {}) };
    this.shadowRoot = null;
    this.contentDocument = null;
  }

  getAttribute(nombre) {
    return Object.prototype.hasOwnProperty.call(this.attributes, nombre)
      ? this.attributes[nombre] : null;
  }

  hasAttribute(nombre) {
    return Object.prototype.hasOwnProperty.call(this.attributes, nombre);
  }

  attachShadow() {
    const shadow = new FakeShadowRoot(this);
    shadow.ownerDocument = this.ownerDocument;
    this.shadowRoot = shadow;
    return shadow;
  }
}

class FakeDocumentFragment extends FakeNode {
  constructor() { super(NODE.DOCUMENT_FRAGMENT); }
}

class FakeShadowRoot extends FakeDocumentFragment {
  constructor(host) {
    super();
    this.host = host;
  }
}

/** Recorre en orden de documento y devuelve los nodos de texto. */
function textNodesOf(root) {
  const salida = [];
  const visitar = (node) => {
    if (node.nodeType === NODE.TEXT) { salida.push(node); return; }
    for (const hijo of [...node.childNodes]) visitar(hijo);
  };
  visitar(root);
  return salida;
}

class FakeDocument extends FakeNode {
  constructor() {
    super(NODE.DOCUMENT);
    this.ownerDocument = null;          // como en el DOM real
    this.defaultView = { NodeFilter: { SHOW_TEXT: 0x4, SHOW_ELEMENT: 0x1 } };
    this.documentElement = null;
    this.body = null;
    //: Si se pone a true, el walker lanza a mitad del recorrido: sirve para
    //: simular que Angular reemplaza el subarbol mientras se esta leyendo.
    this.breakWalkerAt = null;
  }

  createTreeWalker(root, whatToShow) {
    if (whatToShow !== undefined && whatToShow !== 0x4) {
      throw new Error(`whatToShow no soportado: ${whatToShow}`);
    }
    const nodos = textNodesOf(root);
    const limite = this.breakWalkerAt;
    let i = 0;
    return {
      nextNode() {
        if (limite !== null && limite !== undefined && i === limite) {
          throw new Error('El nodo ya no pertenece al documento');
        }
        return i < nodos.length ? nodos[i++] : null;
      },
    };
  }

  /** Simula que el iframe se desmonta: el documento se queda sin ventana. */
  destroy() {
    this.defaultView = null;
  }
}

/** Crea un documento con `<html><body>` listo para colgarle cosas. */
function createDocument() {
  const doc = new FakeDocument();
  const html = new FakeElement('html');
  doc.appendChild(html);
  doc.documentElement = html;
  const body = new FakeElement('body');
  html.appendChild(body);
  doc.body = body;
  return doc;
}

/**
 * Azucar para construir arboles:
 *   el(doc, 'div', { class: 'x' }, [ el(doc,'span',{},['Mas de 44.5']) ])
 * Las cadenas se convierten en nodos de texto.
 */
function el(doc, tagName, atributos, hijos) {
  const nodo = new FakeElement(tagName, atributos);
  nodo.ownerDocument = doc;
  for (const hijo of hijos || []) {
    if (typeof hijo === 'string') {
      const texto = new FakeText(hijo);
      texto.ownerDocument = doc;
      nodo.appendChild(texto);
    } else {
      nodo.appendChild(hijo);
    }
  }
  return nodo;
}

/** Un iframe del mismo origen con su propio documento. */
function iframe(doc, src) {
  const marco = el(doc, 'iframe', { src: src || 'about:blank' });
  const interno = createDocument();
  marco.contentDocument = interno;
  return { frame: marco, doc: interno };
}

module.exports = { NODE, FakeNode, FakeText, FakeElement, FakeDocument,
                   FakeDocumentFragment, FakeShadowRoot,
                   createDocument, el, iframe };
