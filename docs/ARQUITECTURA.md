# Arquitectura y decisiones técnicas

Documento de referencia del proyecto. Explica **qué se decidió y por qué**, para que
cualquier ampliación futura no rompa las garantías que hoy tiene la aplicación.

---

## 0. Función principal

El núcleo de la aplicación es **detectar el momento de entrada**, no analizar una apuesta
ya hecha. Mientras no has apostado, el programa evalúa continuamente **todas** las líneas
que la casa ofrece y las convierte en señales comparables. `FIJAR APUESTA` existe, pero es
una función secundaria que se añade encima sin quitar el tablero.

Orden de prioridades del sistema:

1. detectar el estado del partido;
2. leer el mercado actual;
3. calcular señales de entrada en tiempo real;
4. comparar contra la referencia del usuario y contra los ritmos observados;
5. permitir seleccionar y fijar una apuesta;
6. hacer seguimiento de la apuesta fijada.

---

## 0.bis Fuentes de datos

A partir de la integración con la extensión, el mismo dato puede venir de sitios
distintos. La **capa de adquisición** sabe de dónde viene cada uno; el dominio no, y no
debe saberlo.

| Fuente | Aporta | Prioridad |
|---|---|---|
| `BrowserSource` (extensión → puente local) | mercado, líneas, cuotas y, si BetPlay los expone, marcador, nombres, parciales, cuarto y reloj | 1 |
| OCR de pantalla | lo que no llegue por DOM | 2 |
| Manual (ROI, marcador inicial) | último recurso | 3 |

Reglas que no conviene romper:

- **DOM confirmado por encima de OCR confirmado**, porque el DOM viene estructurado de la
  propia página y no de una lectura de imagen. Pero cuando discrepan **no se elige en
  silencio**: queda un `CONFLICTO DE FUENTES` en el log y en el panel.
- **Una región deja de ser obligatoria en cuanto otra fuente entrega ese dato.**
  `AppController.missing_requirements` mira todas las fuentes, no solo el perfil.
- **Sin regiones no se captura pantalla en absoluto**, así que el modo solo-extensión
  funciona aunque el equipo no pueda capturar ni tenga OCR instalado.
- Lo que llega por el puente se convierte a los `MarketKey`, `MarketLine` y
  `MarketSnapshot` que ya existían. **No hay modelo paralelo.**

### El puente

`http.server` de la librería estándar, escuchando **solo en 127.0.0.1**. Va en un único
sentido: extensión → datos → aplicación. No hay ningún endpoint que ejecute comandos, abra
ficheros, apueste ni controle el navegador, y esa ausencia está cubierta por un test.

La cabecera `X-VisorApuestas-Bridge` no es seguridad criptográfica: al ser personalizada
obliga al navegador a hacer *preflight*, de modo que una página cualquiera no puede colar
peticiones sin que el servidor apruebe antes su origen. El CORS devuelve el origen concreto
de la extensión, **nunca `*`**. El ID de una extensión sin empaquetar depende de la ruta de
instalación y no se puede fijar de antemano; por eso se acepta cualquier origen
`chrome-extension://` y se deja `pinned_origin` para cerrarlo del todo una vez instalada.

El protocolo v1 transporta dos ejes independientes dentro del mismo paquete y el mismo
endpoint: `gameState` (marcador, nombres, parciales, periodo y reloj) y
`visibleMarket` + `lines` (mercado y oferta). `visibleMarket: null` con `lines: []` es
un update válido si trae `gameState`; un mercado reconocido también puede viajar con
`lines: []` para indicar que la oferta está suspendida. `BrowserSource` mantiene tiempos
de vigencia separados: un update de marcador no rejuvenece la última cuota, y un update
de mercado no rejuvenece el marcador.

### Lo que el DOM NO puede dar

El experimento real lo dejó claro: **los mercados que dejas de ver desaparecen del DOM**.
No se simulan. La aplicación puede conservar la última línea observada de otro mercado,
pero la presenta como `ÚLTIMA LÍNEA OBSERVADA` con su hora, nunca como línea actual.

---

## 1. Principio rector

> Es preferible mostrar `--` durante 500 ms que mostrar un número incorrecto y calcular
> sobre él.

De ahí salen tres reglas que atraviesan todo el código:

1. **Ningún dato entra en un cálculo sin estar confirmado.** El tipo `Observed` distingue
   `UNKNOWN / RAW / CONFIRMED / MANUAL`, y solo los dos últimos son utilizables.
2. **Nunca se infiere lo que no se sabe.** Si faltan los puntos de un cuarto, el resultado
   es `None`, no `0`.
3. **Ningún dato dudoso se corrige en silencio.** Se marca como sospechoso y se registra.

---

## 2. Estructura de carpetas

```
src/visorunder/
├── domain/          reglas del juego, estado, mercados, apuesta, tiempo, valores
├── calculations/    matemáticas puras: métricas, ámbito por mercado, entrada y señales
├── capture/         ROIs, backends de captura, re-anclaje por imagen
├── ocr/             abstracción de motor, motores concretos, preprocesado, estabilización
├── parsers/         texto OCR → valores tipados y validados
├── pipeline/        ciclo de lectura en vivo, seguimiento de mercado, modo demo
├── storage/         SQLite con migraciones y repositorios
├── ui/              PySide6: panel, mercado, selector de ROI, diagnóstico, atajos
├── config/          perfiles de casa, criterios de entrada, preferencias, rutas
├── diagnostics/     bus de log
├── app.py           controlador (sin Qt: se puede probar sin interfaz)
└── __main__.py      arranque
tests/               142 pruebas, incluida una de la interfaz completa
```

La regla de dependencias es de fuera hacia dentro: `ui → app → pipeline → {ocr, parsers,
capture, storage} → domain`. **`domain` y `calculations` no importan nada del resto**, por
eso se pueden probar de forma aislada.

---

## 3. Motor OCR: por qué RapidOCR

| Candidato | Ventajas | Inconvenientes | Decisión |
|---|---|---|---|
| **RapidOCR (ONNXRuntime)** | local, gratis, `pip install`, **modelos dentro del paquete**, detecta varias líneas por recorte | ~40-90 ms por recorte en CPU | **predeterminado** |
| Tesseract | muy rápido y preciso en dígitos con `whitelist` | exige instalar un binario aparte y configurar PATH → rompe el "un solo .exe" | alternativa |
| EasyOCR / PaddleOCR | buena precisión | pesan cientos de MB y arrastran PyTorch/Paddle | descartados |
| Servicios en la nube | — | de pago y no locales | prohibidos por requisito |

La decisión clave es el **empaquetado**: con RapidOCR el `.exe` funciona en un equipo
limpio sin instalar nada más. Tesseract sigue disponible porque en recortes diminutos de
dígitos (reloj, marcador) es más rápido; el motor se elige por perfil.

**La abstracción es lo que de verdad importa.** Todo el código habla con `OcrEngine`
(`ocr/base.py`), que devuelve un `OcrResult` con texto, confianza, cajas y milisegundos.
Añadir un motor nuevo es implementar la clase y registrarla en `ocr/engine.py`. Existe
además `StubEngine`, que alimenta el pipeline con texto sintético: es lo que permite
probar toda la aplicación sin pantalla ni OCR reales.

---

## 3.bis El motor de entrada

`calculations/entry.py` evalúa cada línea y produce un `LineEvaluation`:

```
puntos que faltan   = floor(línea) + 1 − puntos del ámbito
ritmo necesario     = puntos que faltan / minutos restantes del ámbito
margen vs referencia = ritmo necesario − tu ritmo de referencia
margen vs cuarto     = ritmo necesario − promedio real del cuarto
margen vs partido    = ritmo necesario − promedio real del partido
```

`calculations/signals.py` traduce el margen a la escala `MUY EXIGENTE / EXIGENTE /
NEUTRO / PELIGROSO`, con umbrales configurables, o a `NO EVALUABLE` cuando falta algún
dato confirmado.

Tres decisiones de diseño que conviene no romper:

- **`evaluate_line` se apoya en `compute_bet_metrics`**, no reimplementa la resolución de
  ámbito. El tablero y el seguimiento de una apuesta comparten exactamente el mismo
  cálculo, así que no pueden divergir.
- **Sin heurísticas ocultas.** La clasificación depende solo del margen y de los umbrales.
  Que queden pocos puntos o poco tiempo no la modifica; `TRAMO FINAL` es un indicador
  independiente que solo informa.
- **Vocabulario neutro.** El dominio habla de *superar la línea*, un hecho del partido
  independiente del lado apostado. "Faltan para perder" es una traducción de interfaz que
  solo aparece con una apuesta UNDER fijada. Gracias a eso, soportar OVER más adelante no
  obliga a reescribir el motor.

El **enfoque** de la tarjeta grande se decide por **cuota UNDER objetivo**, no por mayor
margen: un margen más alto suele venir con una cuota bastante peor. La selección manual
del usuario siempre manda sobre el enfoque automático.

---

## 3.ter Radar multi-mercado

`EVENTO -> MERCADOS -> LÍNEAS`, nunca una lista plana. `EventMarkets` indexa un
`MarketState` por `MarketKey`; cada uno guarda su última lectura, `last_seen_at`,
`last_confirmed_at` y si está visible.

**La frescura se deriva, no se almacena.** `MarketState.freshness(criteria, now)` la
calcula de la visibilidad y la antigüedad, así que no puede quedar desincronizada de los
datos que la producen.

Tres salvaguardas que no conviene tocar:

1. **Un `MarketTracker` por mercado.** Al ser independientes, la confirmación de un
   mercado no puede alimentarse con lecturas de otro.
2. **Compuerta de transición.** Al cambiar de pestaña el título tarda unas lecturas en
   confirmarse; en ese hueco el título confirmado todavía dice `Q2` mientras el bloque ya
   muestra las líneas de `Partido`. Mientras el título **en bruto** discrepe del
   confirmado, no se publica nada y el mercado anterior conserva intacta su última lectura
   —ni siquiera se refresca su `last_seen_at`—. Sin esto, las líneas acabarían atribuidas
   al mercado equivocado, que es el peor fallo posible de esta herramienta.
3. **Una lectura sin confirmar nunca sustituye a la publicada.** `EventMarkets.observe`
   solo reemplaza el snapshot cuando la lectura está confirmada.

Si la casa retira las líneas, `EventMarkets.mark_suspended` conserva el último snapshot
con su timestamp pero fuerza `STALE`; nunca lo vuelve a presentar como oferta actual. Al
cambiar `event.id`, `BrowserSource` limpia a la vez mercado, líneas, scoreboard,
parciales y tiempos de cada eje antes de aceptar el nuevo evento.

En Kambi, cada nodo semántico `bet-offer-subcategory` es una frontera fuerte de mercado.
`findMarketContainer` procesa esa unidad —título y opciones— y no puede subir a su `ul`
padre, aunque los mercados hermanos (hándicap, ganador, margen) no sean títulos candidatos
del escáner de totales. Para otras casas se conserva el límite genérico por cabeceras.

La detección del mercado visible sigue esta prioridad: título confirmado por OCR →
mercado forzado a mano por el usuario → mercado por defecto del perfil. Si nada resuelve,
no se publica ninguna línea.

---

## 4. Puntos técnicamente delicados

### 4.1 Que la línea visible no es la del cuarto en juego
Cada `MarketLine` lleva un `MarketKey` (tipo de mercado + cuarto o mitad) leído del título
del mercado. `calculations/market_scope.py` traduce ese `MarketKey` en **qué puntos** y
**qué tiempo restante** aplican. Un mercado de Q3 durante el Q2 devuelve `0 puntos` y
`10:00 restantes`, no los puntos del Q2. Añadir un mercado nuevo (mitad, prórroga) es
añadir un caso ahí, sin tocar métricas ni interfaz.

### 4.2 Puntos del cuarto al arrancar a mitad
`PeriodPointsTracker` guarda **marcadores base** por periodo con su procedencia
(`BREAKDOWN` > `HISTORY` > `MANUAL` > `UNKNOWN`). Solo se registra una base cuando es un
**hecho**: se presenció el cambio de cuarto, o el reloj marca el cuarto recién empezado.
Al abrir la app a mitad del Q3 no hay base, y los puntos del cuarto son `--` hasta que el
usuario los introduzca. Esta salvaguarda tiene un test dedicado porque un fallo aquí
corrompe silenciosamente todas las métricas del cuarto.

Con el enfoque de detección de entrada esto pesa más: las líneas de ese cuarto quedan
**NO EVALUABLE** con su motivo visible en la propia fila. El bloqueo es **por línea**, de
modo que un mercado de partido sigue operativo en el mismo tablero.

El desglose estructural del DOM vive en una foto reemplazable separada del OCR y de los
baselines. `scoreboard.js` conserva el orden de todas las celdas semánticas, incluso las
vacías, y transporta por equipo `name`, `total` y `periods` (`Q1`…`Q4`, `OT1`…). Python
reemplaza esa foto en cada lectura: no acumula valores antiguos. `None` significa celda
desconocida y nunca se convierte en cero; un cero solo existe cuando Kambi lo publicó.
Si el parcial del periodo actual está completo, el botón de marcador inicial desaparece;
si falta, siguen disponibles OCR, historial y entrada manual.

`compute_general_metrics` deriva, usando segundos y `GameRules`, el ritmo del cuarto, el
ritmo de la mitad en curso y el ritmo de la primera mitad ya terminada. El radar reutiliza
`LineEvaluation.margin_vs_half_pace = required_pace - half_pace`; no existe una segunda
fórmula de margen en la UI.

### 4.3 Ruido del OCR
`ocr/stabilization.py` implementa `Stabilizer`: N lecturas iguales para confirmar, más un
**validador** por campo que conoce la física del dato. Los valores improbables no se
descartan para siempre: se les exige más insistencia (*confianza temporal*), de modo que
un `86` suelto entre `36` se ignora, pero un salto real acaba aceptándose. Los valores
imposibles (cuarto `0`) se rechazan siempre (`Verdict.forbid`).

**Caso especial del reloj:** a 2-4 lecturas por segundo, un reloj que baja cada segundo
casi nunca se repite; exigirle repeticiones lo dejaría congelado. Por eso tiene una *vía
rápida* (`clock_fast_path`): se acepta al instante si es coherente con el tiempo real
transcurrido. Lo detectó la prueba de interfaz y por eso existe.

### 4.4 ROIs frágiles
Las coordenadas se guardan **normalizadas** (fracciones de un marco de referencia), no en
píxeles absolutos. Así el mismo perfil sirve a 1920×1080 y 2560×1440 y sobrevive al
escalado de Windows. Además, un ROI de **ancla** permite recolocar todo el conjunto por
correlación de imagen (`cv2.matchTemplate`) cuando la página se desplaza. Si la
correlación es baja, **no se corrige nada**: antes sin corrección que con una inventada.

### 4.5 Hilos
El lector vive en un hilo propio; la interfaz **no recibe señales del hilo**, sino que lee
con un temporizador la última fotografía (`reader.last_snapshot`). Elimina toda una clase
de errores de concurrencia con Qt. El `tick()` es síncrono y aislado, lo que permite
probarlo sin interfaz.

### 4.6 Nada modal automático
Un diálogo modal que aparece solo bloquearía el bucle de eventos y congelaría el panel
encima del navegador. La petición del marcador inicial es un **botón visible dentro del
panel**, no una ventana emergente. (Este error existió y lo detectó la prueba de interfaz.)

---

## 5. Modelo de datos (SQLite)

Versión del esquema en `PRAGMA user_version`, migraciones numeradas en
`storage/database.py`.

| Tabla | Contenido |
|---|---|
| `sportsbooks` | casas conocidas |
| `profiles` | perfil completo en JSON + resolución y escala |
| `screen_regions` | una fila por ROI, consultable |
| `events` | partido (equipos, reglas) |
| `sessions` | cada sesión de lectura |
| `ocr_observations` | bruto, normalizado, confianza, valor, estado, motivo, ms |
| `score_snapshots` | reloj, cuarto, marcador y puntos del cuarto |
| `market_snapshots` | una fila por línea: tipo, cuarto, línea, cuotas, contexto |
| `bets` | apuesta fijada con el estado del partido en ese instante |
| `sessions.entry_criteria` | criterios usados en la sesión (migración 002) |
| `market_observations` | cuándo se vio cada mercado por última vez (migración 003) |

`bets` guarda `line` y `odds` **congeladas**: `LockedBet` es una dataclass `frozen`, así
que es imposible mutarla por accidente.

> Detalle de SQLite que costó un fallo: en un `UNIQUE`, dos `NULL` son **distintos** entre
> sí, así que `UNIQUE(session_id, market_type, period, half)` no agrupaba el mercado de
> partido (que lleva `period` y `half` a `NULL`) y creaba una fila por observación. Se
> indexa por expresión con `COALESCE(period, -1)`.

**No se persisten datos derivados.** Márgenes, ritmos necesarios, señales y estados de
frescura no se guardan:
con el marcador, el reloj, las líneas, las cuotas, los timestamps y los criterios de la
sesión se recalculan exactamente igual. Duplicarlos crearía dos versiones de la verdad que
podrían discrepar tras un cambio de fórmula.

---

## 6. Rendimiento

Objetivo: 2-4 lecturas/s. En cada ciclo solo se capturan los rectángulos configurados
(típicamente 5-7 recortes pequeños), nunca la pantalla completa. Costes medidos en el
ciclo: captura ~1-3 ms por ROI con MSS; el OCR domina el resto. Si el equipo va justo, se
baja la frecuencia en el perfil: la prioridad declarada es estabilidad y precisión antes
que velocidad.

---

## 7. Qué queda fuera a propósito

Sin machine learning predictivo, sin predicción de resultado, sin recomendaciones, sin
APIs deportivas, sin automatización de clics, sin Selenium, sin servidores, sin cuentas y
sin pagos. La aplicación es exactamente: **captura → OCR local → estado del partido →
lectura del mercado → cálculo → interfaz**.

---

## 8. Ampliaciones naturales

- Nuevos mercados: añadir un caso en `market_scope.resolve`.
- Nuevos niveles o criterios de señal: `signals.py` y `EntryCriteria`.
- Soporte de OVER: el motor ya es neutro; queda la traducción en la interfaz.
- Más mercados (hándicaps, totales por equipo): un caso en `market_scope.resolve` y una
  entrada en el orden de presentación de `EventMarkets`.
- Nuevos motores OCR: implementar `OcrEngine` y registrarlo.
- Nuevas reglas de juego: crear un `GameRules` (la prórroga ya está contemplada).
- Gráficas del historial: los datos ya están en `market_snapshots` y `score_snapshots`.
