/**
 * Resolucion de documentos y lectura de texto, con el DOM real o con un DOM
 * de prueba.
 *
 * Por que existe este modulo:
 *
 *   El escaneo admite varias clases de raiz (el documento principal, shadow
 *   roots abiertos, iframes del mismo origen). El codigo anterior pedia el
 *   TreeWalker siempre asi:
 *
 *       element.ownerDocument.createTreeWalker(...)
 *
 *   y para un Document `ownerDocument` es null POR DEFINICION, asi que la
 *   raiz principal reventaba con
 *
 *       Cannot read properties of null (reading 'createTreeWalker')
 *
 *   y con ella se perdia el escaneo entero de esa raiz: ningun mercado.
 *
 *   La solucion NO es callar el error con un `if (!ownerDocument) return ''`,
 *   porque eso deja de leer justo la raiz que mas importa. Lo que hace falta
 *   es resolver bien el documento segun el TIPO de nodo, y tener un recorrido
 *   de reserva para cuando el arbol se desmonta a mitad de la lectura.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.VDIAG = Object.assign(root.VDIAG || {}, { dom: api });
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  //: Constantes del DOM escritas a mano: en el service worker y en las pruebas
  //: no existe el global `Node`, y son valores fijos de la especificacion.
  const NODE = {
    ELEMENT: 1,
    TEXT: 3,
    CDATA: 4,
    DOCUMENT: 9,
    DOCUMENT_FRAGMENT: 11,
  };

  //: NodeFilter.SHOW_TEXT segun la especificacion. Se usa como ultimo recurso
  //: si no se puede leer el NodeFilter del documento que se va a recorrer.
  const SHOW_TEXT = 0x4;
  const SHOW_ELEMENT = 0x1;

  //: Tope del recorrido manual de reserva. Una pagina normal no llega ni de
  //: lejos; sirve para que un arbol ciclico o gigantesco no bloquee la pestana.
  const MAX_FALLBACK_NODES = 200000;

  function nodeTypeOf(node) {
    try {
      return node && typeof node.nodeType === 'number' ? node.nodeType : null;
    } catch (error) {
      return null;      // proxies muertos de iframes desmontados
    }
  }

  /**
   * Documento al que pertenece un nodo, sea del tipo que sea.
   *
   *   Document              -> el mismo (ownerDocument es null por definicion)
   *   Element / Text        -> ownerDocument
   *   ShadowRoot            -> ownerDocument, o el del host si hiciera falta
   *   DocumentFragment      -> ownerDocument
   *   nodo desconectado     -> su ownerDocument sigue existiendo
   *   iframe ya desmontado  -> null, y quien llame decide que hacer
   *
   * Devuelve null en vez de lanzar: el que decide si eso es un problema es el
   * escaneo, que puede saltarse esa raiz y seguir con las demas.
   */
  function documentForNode(node) {
    if (!node) return null;
    try {
      if (nodeTypeOf(node) === NODE.DOCUMENT) {
        return typeof node.createTreeWalker === 'function' ? node : null;
      }
      const propio = node.ownerDocument;
      if (propio && typeof propio.createTreeWalker === 'function') return propio;
      // Un shadow root siempre tiene ownerDocument, pero si algun dia llega un
      // fragmento raro, el host es el camino de vuelta al documento.
      const host = node.host;
      const delHost = host && host.ownerDocument;
      if (delHost && typeof delHost.createTreeWalker === 'function') return delHost;
      return null;
    } catch (error) {
      return null;
    }
  }

  /**
   * NodeFilter.SHOW_TEXT del documento que se va a recorrer.
   *
   * Importa cuando la raiz esta dentro de un iframe: cada documento trae su
   * propio NodeFilter. El valor es el mismo en todos los navegadores, pero
   * pedirselo al documento correcto evita depender de un global que en el
   * service worker o en las pruebas ni siquiera existe.
   */
  function filtroDe(doc, nombre, porDefecto) {
    try {
      const vista = doc && doc.defaultView;
      if (vista && vista.NodeFilter && typeof vista.NodeFilter[nombre] === 'number') {
        return vista.NodeFilter[nombre];
      }
    } catch (error) { /* iframe de otro origen o ya desmontado */ }
    if (typeof NodeFilter !== 'undefined' && NodeFilter &&
        typeof NodeFilter[nombre] === 'number') {
      return NodeFilter[nombre];
    }
    return porDefecto;
  }

  function showTextFor(doc) { return filtroDe(doc, 'SHOW_TEXT', SHOW_TEXT); }

  function showElementFor(doc) { return filtroDe(doc, 'SHOW_ELEMENT', SHOW_ELEMENT); }

  /**
   * ¿Sigue sirviendo esta raiz?
   *
   * BetPlay es dinamico: entre que `collectRoots` ve un iframe y el escaneo
   * llega a recorrerlo, Angular puede haberlo reemplazado. Una raiz que se
   * quedo sin documento vivo se salta; las demas se recorren igual.
   */
  function isUsableRoot(node) {
    try {
      const tipo = nodeTypeOf(node);
      if (tipo === null) return false;
      if (tipo === NODE.DOCUMENT) {
        // Un documento de iframe desmontado conserva la referencia pero se
        // queda sin ventana: es la senal de que ya no sirve para nada.
        if ('defaultView' in node && node.defaultView === null) return false;
        if (!node.documentElement) return false;
        return typeof node.createTreeWalker === 'function';
      }
      if (tipo === NODE.DOCUMENT_FRAGMENT) return !!documentForNode(node);
      if (tipo === NODE.ELEMENT) {
        if (node.isConnected === false) return false;
        return !!documentForNode(node);
      }
      return false;
    } catch (error) {
      return false;
    }
  }

  /** Recorrido manual, sin TreeWalker. Iterativo para no agotar la pila. */
  function collectTextManually(node) {
    const partes = [];
    let visitados = 0;
    const pila = [node];
    while (pila.length) {
      const actual = pila.pop();
      if (!actual) continue;
      if (visitados > MAX_FALLBACK_NODES) break;
      visitados += 1;
      let tipo = null;
      try { tipo = nodeTypeOf(actual); } catch (error) { continue; }
      if (tipo === NODE.TEXT || tipo === NODE.CDATA) {
        let valor = '';
        try { valor = (actual.nodeValue || '').trim(); } catch (error) { valor = ''; }
        if (valor) partes.push(valor);
        continue;
      }
      let hijos = [];
      try { hijos = Array.from(actual.childNodes || []); } catch (error) { hijos = []; }
      for (let i = hijos.length - 1; i >= 0; i -= 1) pila.push(hijos[i]);
    }
    return partes;
  }

  /**
   * Texto de un subarbol respetando la separacion entre celdas.
   *
   * NO se usa innerText a proposito: innerText devuelve cadena vacia para los
   * elementos ocultos, y precisamente los mercados que no estan a la vista son
   * el objeto de este diagnostico. textContent si los lee, pero pega todo
   * junto ("Mas de 44.51.75"), asi que se recorren los nodos de texto y se
   * unen con salto de linea.
   *
   * Funciona con cualquier raiz admitida y nunca lanza: si el arbol se desmonta
   * a mitad del recorrido, se termina con lo que haya usando el recorrido
   * manual, en vez de tumbar el escaneo entero.
   */
  function extractText(node) {
    if (!node) return '';
    const doc = documentForNode(node);
    if (doc) {
      try {
        const partes = [];
        const walker = doc.createTreeWalker(node, showTextFor(doc));
        let actual = walker.nextNode();
        while (actual) {
          const valor = (actual.nodeValue || '').trim();
          if (valor) partes.push(valor);
          actual = walker.nextNode();
        }
        return partes.join('\n');
      } catch (error) {
        // El arbol cambio debajo del walker (Angular reemplaza subarboles a
        // mitad de un rescaneo). Se reintenta a mano en vez de perder la raiz.
      }
    }
    try {
      return collectTextManually(node).join('\n');
    } catch (error) {
      return '';
    }
  }

  /** Texto de los hijos DIRECTOS de tipo texto, sin bajar al resto del arbol. */
  function ownText(node) {
    if (!node) return '';
    let hijos = [];
    try { hijos = Array.from(node.childNodes || []); } catch (error) { return ''; }
    return hijos
      .filter((n) => nodeTypeOf(n) === NODE.TEXT)
      .map((n) => (n.nodeValue || '').trim())
      .filter(Boolean)
      .join(' ');
  }

  /** Hijos elemento de un nodo, tolerando nodos que ya no existen. */
  function childElements(node) {
    if (!node) return [];
    try {
      return Array.from(node.children || []);
    } catch (error) {
      return [];
    }
  }

  /** Adaptador que usa el escaneo estructural sobre el DOM real. */
  function createAdapter() {
    return {
      children: childElements,
      text: extractText,
      ownText,
    };
  }

  return { NODE, SHOW_TEXT, SHOW_ELEMENT, nodeTypeOf, documentForNode,
           showTextFor, showElementFor, isUsableRoot,
           extractText, ownText, childElements, collectTextManually, createAdapter };
});
