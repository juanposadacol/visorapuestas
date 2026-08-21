# VisorApuestas · DOM Diagnostic

Extensión **local** de Chrome/Edge, **solo de diagnóstico**, para responder a una pregunta
concreta antes de escribir una sola línea de integración:

> Si me quedo mirando el mercado **Q3**, ¿siguen existiendo en el DOM los mercados de
> **Partido**, **1.ª mitad**, **2.ª mitad** y los demás cuartos, con sus líneas? Y si siguen
> ahí, ¿siguen **actualizándose** aunque no estén a la vista?

Si la respuesta es que sí, más adelante podremos leer varios mercados a la vez sin que
tengas que ir cambiando de pestaña. Si es que no, lo sabremos con evidencia y no con
suposiciones.

---

## Qué NO hace

Esto importa tanto como lo que hace:

- **No apuesta ni toca la página.** No hace clic, no navega, no rellena nada, no modifica
  el carrito ni ningún botón. Es estrictamente de lectura.
- **No automatiza la navegación.** Los clics entre mercados los haces tú.
- **No usa Selenium ni Playwright**, ni ninguna forma de automatización del navegador.
- **No lee credenciales, cookies, tokens ni almacenamiento** de ninguna página.
- **No llama a ninguna API de la casa** ni envía nada fuera de tu equipo. El único destino
  es `127.0.0.1`.

### Permisos y por qué

| Permiso | Para qué |
|---|---|
| `https://*.betplay.com.co/*` | leer el DOM del partido que tienes abierto |
| `http://127.0.0.1/*`, `http://localhost/*` | hablar con VisorApuestas en tu propio equipo. Las reglas de coincidencia de Chrome **no incluyen el puerto**, por eso no se puede acotar a 8765 |
| `storage` | recordar el puerto que elijas, nada más |

Sigue sin pedir `cookies`, `history`, `tabs` ni `downloads`. **Tampoco `alarms`**: el
latido que mantiene viva la conexión con la aplicación local lo manda el content script
cada 5 s, y cada mensaje suyo despierta al service worker, así que no hace falta un
temporizador propio del worker ni el permiso que lo habilita.

> Esta tabla es **el único sitio** donde se documentan los permisos. En `manifest.json` no
> hay explicaciones: JSON no admite comentarios, y una clave inventada como `"// permisos"`
> hace que Chrome y Edge muestren `Unrecognized manifest key`. Si añades un permiso,
> actualiza esta tabla y el test `tests/manifest.test.js`, que vigila que la lista no
> crezca por descuido.

### Por qué ahora sí hay service worker

En la versión de diagnóstico no había, y era lo correcto. Ahora sí, por una razón concreta
de seguridad: un `fetch` hecho desde el content script sale con el origen de **BetPlay**, y
para aceptarlo el servidor local tendría que abrir la puerta a esa web entera —con lo que
cualquier script suyo podría hablar con el puente—. Desde el service worker el origen es
`chrome-extension://<id>`, que es justo lo que el servidor acepta. Además centraliza la
reconexión y el latido en un sitio, en vez de una copia por pestaña abierta.

### Diagnóstico estructural

Si el mercado o el marcador vuelven a leerse mal, el popup trae dos botones que
copian la **estructura real** del bloque, saneada:

* `COPIAR ESTRUCTURA DEL MERCADO`
* `COPIAR ESTRUCTURA SCOREBOARD`

Sale la jerarquía con etiquetas, clases, roles y los textos del mercado, que es lo
que permite ajustar el lector contra HTML de verdad en lugar de a ciegas. **No** sale
nada de la cuenta: los bloques de boleto, saldo, login y chat se omiten enteros, los
atributos que huelen a autenticación no se copian ni por su nombre, y los textos
pasan por la misma redacción que enmascara correos, importes e identificadores.

Si el marcador vive en un iframe de otro origen, el informe lo dice y ahí se queda:
el navegador impide leerlo y no se intenta rodear.

### Qué mirar en el popup

```
App local     CONECTADA ✓ (v1.1.0)      <- la conexión con VisorApuestas
BetPlay       DETECTADO ✓               <- el sitio
Escáner       ACTIVO ✓ (13/13 raíces)   <- el recorrido del DOM
Mercados      3 detectado(s), 3 con líneas
Enviando      mercado válido
Marcador      56-69 ✓  Las Vegas Aces / Atlanta Dream
Cuarto        Q3 ✓
Reloj         06:42 ✓
```

Cada línea responde **una** pregunta. `App local` habla solo de la conexión con la
aplicación; `Enviando` habla solo de los datos. Que no haya mercado no significa que
la aplicación esté cerrada.

Si aparece la tarjeta **Errores**, los errores vienen agrupados por causa y raíz con
su cuenta (`createTreeWalker / iframe x43`), no repetidos cuarenta y tres veces.

---

## Instalación

1. Abre **Chrome** (o **Edge**, que funciona igual).
2. Ve a `chrome://extensions` (en Edge, `edge://extensions`).
3. Activa **Modo desarrollador**.
4. Pulsa **Cargar descomprimida**.
5. Selecciona la carpeta `visorapuestas/browser-extension`.

Debe aparecer *VisorApuestas DOM Diagnostic*. Ancla su icono a la barra para tenerlo a mano.

> Si cambias algún archivo, pulsa el botón de recargar de la extensión **y recarga también
> la pestaña de BetPlay**: el content script se inyecta al cargar la página.

---

## Cómo funciona el puente

```
content script  ──►  service worker  ──►  http://127.0.0.1:8765  ──►  VisorApuestas
   (lee el DOM)        (decide y envía)        (solo loopback)
```

- Se envía cuando **cambia** el mercado o una cuota, con un tope de **4 envíos útiles por
  segundo**.
- Se manda un **latido cada segundo** aunque nada cambie: es lo que distingue "la casa no
  movió nada" de "se cortó la conexión".
- Si VisorApuestas no está abierto, **no pasa nada**: la extensión reintenta cada pocos
  segundos (hasta 15 s como máximo) y conecta sola cuando abras la aplicación, **sin
  recargar BetPlay**.
- Nunca se envía una línea sin confianza suficiente: el mercado necesita 0.90, las líneas
  tienen que tener forma `.5` y al menos una cuota.

El puerto se cambia desde el popup si 8765 estuviera ocupado.

---

## El experimento de diagnóstico, paso a paso

Esta es la parte importante. Hazlo con un partido **en directo**, que es cuando las cuotas
se mueven.

**Paso 0.** Abre BetPlay y entra en un partido de baloncesto en vivo. Recarga la pestaña
una vez con la extensión ya instalada.

**Paso 1 — Partido.** Haz clic en el mercado **Partido / Total de puntos**. Espera unos
5 segundos. Abre el popup y comprueba que aparece con sus líneas. Ciérralo.

**Paso 2 — Primera mitad.** Haz clic en **1.ª mitad**. Espera 5 segundos. Abre el popup:
deberían verse **dos** mercados, y *Partido* ya no debería estar marcado como visible.

**Paso 3 — Q3.** Haz clic en el **3.er cuarto**. Espera 5 segundos.

**Paso 4 — No toques nada.** Quédate en Q3 entre **3 y 5 minutos**, con el partido en
juego. No cambies de sección. Puedes cerrar el popup: el observador sigue trabajando.

**Paso 5 — Lee el resultado.** Abre el popup y mira, para *Partido* y *1.ª mitad*:

| Lo que ves | Lo que significa |
|---|---|
| `NO EXISTE EN DOM` | BetPlay destruye el componente al cambiar de sección |
| `EN DOM · OCULTO` + *Última mutación: hace mucho* | el nodo sobrevive pero **congelado** |
| `EN DOM · OCULTO` + *Última mutación: hace pocos segundos* | **el caso bueno**: sigue vivo y actualizándose |

En el bloque **Historial de la sesión** la señal decisiva tiene esta pinta:

```
18:40:10.520  GAME_TOTAL (OCULTO) cambia 158.5: 1.8/1.82 -> 1.8/1.9
```

Una línea así, con `(OCULTO)`, significa que BetPlay **actualiza un mercado que no estás
mirando**. Es exactamente lo que necesitamos saber.

**Paso 6 — Envíame el resultado.** Marca **Mostrar debug**, pulsa **COPIAR DIAGNÓSTICO** y
pégamelo. Si prefieres, **DESCARGAR JSON** genera el fichero
`visorapuestas-dom-diagnostic-AAAAMMDD-HHMMSS.json`.

### Qué señales mirar

1. **Existe / oculto / no existe**, que son tres cosas distintas y el popup las separa.
2. **Última mutación** de los mercados ocultos: es la respuesta a la pregunta central.
3. **Líneas encontradas** en los mercados que no estás mirando.
4. **Historial**: entradas `marketDisappeared` (se destruye) frente a `visibilityChanged`
   (solo se oculta).
5. **Entorno**: si aparecen iframes de otro origen o virtualización, cambia el plan.
6. **Debug → selector**: los marcados como `FRAGIL` dependen de clases generadas y no
   servirán para una integración estable.

---

## Cómo leer el popup

- **Mercado visualmente activo** — el que la extensión cree que estás mirando.
- **Existe en DOM / Visible** — separados a propósito. `display:none`, `visibility:hidden`,
  el atributo `hidden` y `aria-hidden` ocultan, pero **no** borran. Estar fuera del
  viewport **no** cuenta como oculto y se indica aparte.
- **UNKNOWN** — la extensión ha visto algo que parece un mercado pero no tiene confianza
  suficiente. Muestra su candidato y el texto original en vez de clasificarlo a ciegas.
- **candidatos brutos → líneas** — cuántos números vio antes y después de deduplicar.

---

## Limitaciones conocidas, dichas de frente

- **Iframes de otro origen**: el navegador impide leerlos, y no se intenta rodear esa
  protección. Si el mercado vive ahí, el popup lo indicará y habrá que replantear.
- **Shadow DOM cerrado**: no es accesible. Los abiertos sí se recorren.
- **Virtualización de listas**: si BetPlay recicla nodos, un mercado puede desaparecer del
  DOM solo por haber hecho scroll. Se detectan indicios, no certezas.
- **Detección de framework**: solo por atributos reales del DOM. El mundo aislado de una
  extensión no ve las variables internas de la página, y no se inyecta código para
  saltarse esa separación.
- **El estado se pierde al recargar** la pestaña: el historial vive en memoria.

---

## Desarrollo

```bash
cd browser-extension
node --test tests/*.test.js     # 286 tests, sin dependencias
```

Se usa el runner incorporado de Node (18+), así que **no hay `node_modules`, ni
`package.json`, ni nada que instalar**, y el proyecto Python no se toca.

La lógica pura vive en `src/lib/` para poder probarla sin navegador:

| Archivo | Responsabilidad |
|---|---|
| `text.js` | normalización de mayúsculas, tildes, espacios y ordinales |
| `markets.js` | identificación del mercado **con nivel de confianza** |
| `lines.js` | extracción de líneas y cuotas |
| `dedupe.js` | fusión de duplicados y comparación entre lecturas |
| `visibility.js` | existe / oculto / no existe |
| `scan.js` | recorrido completo: cabeceras, contenedor por mercado, frontera con el vecino |
| `options.js` | emparejamiento **OVER/UNDER por estructura** del árbol |
| `gamestate.js` | descubrimiento de marcador, cuarto y reloj con validación fuerte |
| `payload.js` | **contrato** con Python: construcción y validación del envío |
| `bridge_client.js` | política de envío: cambios, latido, reintento |
| `report.js` | informe legible, JSON y **redacción de datos personales** |

`src/content.js` es lo único que toca el DOM; `src/popup.*` solo pinta.
