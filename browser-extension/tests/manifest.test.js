/**
 * El manifest, revisado como lo revisa el navegador.
 *
 * Edge y Chrome mostraban:
 *
 *     Unrecognized manifest key '// permisos'
 *
 * porque el fichero llevaba un pseudo-comentario. JSON no tiene comentarios:
 * una clave que empieza por "//" es una clave inventada, y el navegador la
 * senala. La documentacion de los permisos vive en el README.
 *
 * Estas pruebas tambien vigilan el minimo privilegio: si algun dia aparece un
 * permiso nuevo, tiene que ser una decision consciente que rompa este test.
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const RAIZ = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(RAIZ, 'manifest.json'), 'utf8'));

//: Claves que Chrome/Edge reconocen y que este manifest usa.
const CLAVES_VALIDAS = new Set([
  'manifest_version', 'name', 'version', 'description', 'icons',
  'host_permissions', 'content_scripts', 'action', 'background', 'permissions',
]);

test('no hay pseudo-comentarios ni claves inventadas', () => {
  for (const clave of Object.keys(manifest)) {
    assert.ok(!clave.startsWith('//'),
              `"${clave}" es un comentario disfrazado: JSON no tiene comentarios`);
    assert.ok(CLAVES_VALIDAS.has(clave), `clave no reconocida: "${clave}"`);
  }
});

test('los permisos siguen siendo los minimos', () => {
  assert.deepEqual(manifest.permissions, ['storage'],
                   'storage solo sirve para recordar el puerto elegido');
  assert.ok(!manifest.permissions.includes('alarms'),
            'el latido lo da el content script; no hace falta alarms');
  for (const prohibido of ['tabs', 'cookies', 'history', 'downloads', 'webRequest',
                           'debugger', 'scripting', 'declarativeNetRequest']) {
    assert.ok(!manifest.permissions.includes(prohibido), `sobra el permiso ${prohibido}`);
  }
});

test('los hosts son BetPlay y la aplicacion local, nada mas', () => {
  assert.deepEqual(manifest.host_permissions, [
    'https://*.betplay.com.co/*',
    'http://127.0.0.1/*',
    'http://localhost/*',
  ]);
});

test('el content script solo se inyecta en BetPlay', () => {
  assert.equal(manifest.content_scripts.length, 1);
  assert.deepEqual(manifest.content_scripts[0].matches, ['https://*.betplay.com.co/*']);
});

test('todos los ficheros que declara el manifest existen', () => {
  const declarados = [
    ...manifest.content_scripts[0].js,
    manifest.background.service_worker,
    manifest.action.default_popup,
  ];
  for (const relativo of declarados) {
    assert.ok(fs.existsSync(path.join(RAIZ, relativo)), `falta ${relativo}`);
  }
});

test('el popup carga las mismas librerias que usa', () => {
  const html = fs.readFileSync(path.join(RAIZ, manifest.action.default_popup), 'utf8');
  for (const libreria of ['dom.js', 'errors.js', 'text.js', 'markets.js', 'report.js',
                          'gamestate.js', 'structure.js', 'payload.js']) {
    assert.match(html, new RegExp(`lib/${libreria.replace('.', '\\.')}`),
                 `el popup no carga ${libreria}`);
  }
});

test('el service worker importa todas las librerias del content script', () => {
  const worker = fs.readFileSync(path.join(RAIZ, manifest.background.service_worker), 'utf8');
  const importadas = worker.match(/importScripts\(([\s\S]*?)\);/)[1];
  for (const ruta of manifest.content_scripts[0].js) {
    if (!ruta.includes('/lib/')) continue;
    const nombre = ruta.split('/').pop();
    assert.match(importadas, new RegExp(nombre.replace('.', '\\.')),
                 `el service worker no importa ${nombre}`);
  }
});

test('el popup no pinta en huecos que no existen', () => {
  // Un id mal escrito en popup.js no falla en tiempo de carga: simplemente
  // deja de pintarse ese dato, y el panel miente por omision.
  const js = fs.readFileSync(path.join(RAIZ, 'src', 'popup.js'), 'utf8');
  const html = fs.readFileSync(path.join(RAIZ, manifest.action.default_popup), 'utf8');
  const enHtml = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));

  const usados = new Set([
    ...[...js.matchAll(/\$\('([^']+)'\)/g)].map((m) => m[1]),
    ...[...js.matchAll(/poner\('([^']+)'/g)].map((m) => m[1]),
  ]);
  for (const id of usados) {
    assert.ok(enHtml.has(id), `popup.js escribe en "#${id}", que no existe en el HTML`);
  }
  // Los tres campos del partido se pintan en un bucle, con el nombre como id.
  for (const campo of ['marcador', 'cuarto', 'reloj']) {
    assert.ok(enHtml.has(campo), `falta el hueco de ${campo}`);
  }
});

test('los botones del popup tienen su manejador', () => {
  const js = fs.readFileSync(path.join(RAIZ, 'src', 'popup.js'), 'utf8');
  const html = fs.readFileSync(path.join(RAIZ, manifest.action.default_popup), 'utf8');
  const botones = [...html.matchAll(/<button id="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(botones.includes('copiar-estructura'));
  assert.ok(botones.includes('copiar-scoreboard'));
  for (const boton of botones) {
    assert.match(js, new RegExp(`\\$\\('${boton}'\\)`), `el boton ${boton} no hace nada`);
  }
});
