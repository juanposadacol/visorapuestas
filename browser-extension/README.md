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
- **No llama a ninguna API** de la casa ni envía nada a ningún servidor. Todo se queda en
  la memoria de tu navegador.
- **No se conecta todavía con la aplicación Python.** Eso es la etapa siguiente, y solo si
  este diagnóstico dice que merece la pena.

### Permisos que pide

Solo `https://*.betplay.com.co/*`. Ni un dominio más, y **ningún permiso adicional**: sin
`cookies`, sin `storage`, sin `history`, sin `tabs`, sin `downloads`. La descarga del JSON
se hace con un blob generado en el propio popup, precisamente para no pedir ese permiso.

No hay service worker en segundo plano: no hace falta, y menos superficie es mejor.

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

## El experimento, paso a paso

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
node --test tests/*.test.js     # 57 tests, sin dependencias
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
| `scan.js` | parte pura del recorrido (cabecera más interna, no invadir vecinos) |
| `report.js` | informe legible, JSON y **redacción de datos personales** |

`src/content.js` es lo único que toca el DOM; `src/popup.*` solo pinta.
