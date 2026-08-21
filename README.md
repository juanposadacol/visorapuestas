# Visor UNDER

Aplicación **de escritorio, local y para Windows** que lee en pantalla el estado de un
partido de baloncesto y las líneas que muestra tu casa de apuestas, y responde en tiempo
real a una sola pregunta:

> **Dada esta línea que ofrece la casa AHORA, los puntos que ya se anotaron y el tiempo
> que queda, ¿qué ritmo tendrían que mantener desde este instante para superarla, y cómo
> se compara con mi referencia y con el ritmo real del juego?**

> **Qué NO hace, por diseño:** no apuesta, no inicia sesión en ninguna casa, no pulsa
> botones, no usa APIs privadas ni servicios de pago, y **no predice nada**. No hay
> modelos, ni probabilidades, ni proyecciones del resultado final, ni recomendaciones de
> apuesta. Solo lee, valida y calcula.

---

## 1. Qué muestra

El modo principal es **BUSCANDO ENTRADA**: un radar con **todos los mercados del partido
a la vez**, cada uno con todas sus líneas, aunque la casa los reparta en pestañas
distintas.

```
Partido - Total de puntos                              RECIENTE · hace 6 s
 LÍNEA  CUOTA U  PUNTOS  RITMO NEC.  VS REF.  VS Q   VS MITAD  VS PARTIDO  SEÑAL
 176.5   2.25      74       4.62      +0.62  +2.38    +2.38      +0.33     EXIGENTE
 180.5   1.91      78       4.88      +0.88  +2.62    +2.62      +0.58     EXIGENTE
 182.5   1.74      80       5.00      +1.00  +2.75    +2.75      +0.71     MUY EXIGENTE

1.ª mitad - Total de puntos                       DESACTUALIZADO · hace 22 s
  78.5   2.25      --        --        --      --       --         --      FALTA MARCADOR INICIAL 1H

Q3 - Total de puntos                                            EN VIVO
  39.5   1.91      31       5.17      +1.17  +2.92    +2.92      +0.88     MUY EXIGENTE
  40.5   1.74      32       5.33      +1.33  +3.08    +3.08      +1.04     MUY EXIGENTE
```

Y a la izquierda, el contexto más la línea enfocada:

```
CAL IRVINE           40      LÍNEA ENFOCADA (SIN FIJAR)
CHINESE TAIPEI       35      UNDER 40.5 @ 1.74
TOTAL PARTIDO        75
                             LÍMITE PARA PERDER          41
Q3                04:00      PUNTOS PARA SUPERAR LA LÍNEA
JUGADO DEL CUARTO 06:00              21 PUNTOS
                             RITMO NECESARIO PARA SUPERARLA
PUNTOS Q3      20 (10-10)            5.25 pts/min
PROMEDIO CUARTO 3.33/min                MUY EXIGENTE
PROMEDIO PARTIDO 2.88/min
MI REFERENCIA   4.00/min     MARGEN VS REFERENCIA (4.00)  +1.25
MI CUOTA OBJETIVO   1.80     MARGEN VS Q3                 +1.92
                             MARGEN VS PARTIDO            +2.37
```

Si un dato no se puede leer con seguridad, aparece `--`. **Nunca** un número inventado.

---

## 2. Uso diario (con la extensión)

Este es el flujo recomendado. **Se instala una vez y luego te olvidas de ella.**

```
1. Abrir VisorApuestas
2. Abrir BetPlay en Chrome o Edge
3. Entrar al partido
   ↓
   BETPLAY CONECTADO ✓
   ↓
   El radar arranca solo
```

**No hay que pulsar INICIAR. No hay que dibujar regiones. No hay que abrir el
popup de la extensión.** Si cambias de partido, la aplicación lo detecta y empieza
una sesión nueva (te pregunta antes si tienes una apuesta fijada).

El panel **CONEXIÓN**, arriba a la izquierda, dice de dónde sale cada dato:

```
EXTENSIÓN              EXTENSIÓN CONECTADA
DATOS DEL DOM          BETPLAY CONECTADO
ÚLTIMO DATO            hace 0.3 s  (120 ms)
MERCADO                DOM ✓
LÍNEAS Y CUOTAS        DOM ✓
MARCADOR               DOM ✓   (o OCR ✓, o --)
CUARTO                 DOM ✓
RELOJ                  DOM ✓
```

Las dos primeras líneas responden **dos preguntas distintas**, y conviene no
confundirlas:

* **EXTENSIÓN** — ¿está ahí la extensión? Lo dice su latido, que llega cada pocos
  segundos aunque no haya ningún mercado que enviar.
* **DATOS DEL DOM** — ¿siguen frescos los datos que manda?

Que todavía no haya mercado **no** significa que la extensión esté caída. Antes una
sola línea mezclaba las dos cosas y decía `EXTENSIÓN DESCONECTADA` con la extensión
perfectamente conectada, lo que llevó una prueba real entera a buscar un problema de
conexión que no existía.

Mientras falte algún dato, el panel dice **qué** falta:

```
Esperando marcador, reloj
```

y no «no se puede iniciar: faltan regiones». Las regiones son el último recurso, no
el camino normal.

Instalación de la extensión: ver [`browser-extension/README.md`](browser-extension/README.md).

### Qué pasa si algo no está

| Situación | Qué ocurre |
|---|---|
| VisorApuestas cerrado | la extensión reintenta sola; al abrir la app conecta sin recargar BetPlay |
| Chrome cerrado | la app abre igual y muestra `EXTENSIÓN DESCONECTADA`; puedes usar OCR, perfil manual o modo demo |
| Extensión conectada, sin mercado aún | `EXTENSIÓN CONECTADA` + `SIN DATOS DEL DOM`, y abajo qué falta. No es un error |
| El DOM no da marcador/reloj | esos campos pasan a OCR si tienes ROIs; si no, aparecen como `--` |
| Dejan de llegar datos | `DATOS DOM DESACTUALIZADOS`, y las líneas dejan de presentarse como actuales |

---

## 3. Instalación

Requisitos: **Windows 10/11** y **Python 3.10 o superior** (recomendado 3.12).

```bat
git clone <este-repositorio>
cd visorapuestas

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

O simplemente haz doble clic en **`ejecutar.bat`**, que crea el entorno e instala todo la
primera vez.

### Dependencias y por qué

| Paquete | Para qué | ¿Obligatorio? |
|---|---|---|
| `PySide6-Essentials` | interfaz | sí |
| `mss` | captura de pantalla | sí |
| `opencv-python-headless` + `numpy` | preprocesado de imagen | sí |
| `rapidocr-onnxruntime` | motor OCR local, **con los modelos incluidos** | sí |
| `pynput` | atajos de teclado globales (F8/F9/F10) | recomendable |
| `pytesseract` + Tesseract | motor OCR alternativo | opcional |
| `dxcam` | captura más rápida en Windows | opcional |

---

## 4. Ejecución

```bat
python run.py
```

Modo de prueba con un **partido simulado**, sin necesidad de abrir ninguna casa ni de
configurar regiones (ideal para el primer contacto):

```bat
python run.py --demo
```

---

## 5. Configuración manual de regiones (solo si hace falta)

> **Esto ya no es el flujo normal.** Con la extensión conectada, el mercado, las
> líneas y las cuotas llegan solos, y el marcador, el cuarto y el reloj también si
> BetPlay los expone en el DOM. Dibuja regiones **solo** para lo que no llegue por
> ahí, o si no quieres usar la extensión.

Al pulsar INICIAR, la aplicación comprueba qué falta contando **todas** las
fuentes. Si un dato ya lo entrega el DOM, su región deja de ser obligatoria.

Un **perfil** guarda dónde mirar en tu pantalla para una casa concreta. Vienen preparados
los nombres de Sportium, BetPlay, Wplay, RushBet y Codere, pero **las regiones las dibujas
tú**, porque cada casa y cada resolución colocan las cosas en sitios distintos.

1. Abre la casa de apuestas en Chrome o Edge y deja visible el partido en directo.
2. Abre la aplicación y pulsa **Nuevo perfil**. Ponle un nombre descriptivo que incluya la
   resolución, por ejemplo `Sportium 1080` o `BetPlay 1440`.
3. En la ventana de configuración, selecciona una región de la lista y pulsa
   **Definir región seleccionada**. La pantalla se congela y arrastras el ratón sobre la
   zona. **ESC** cancela.
4. Repite con todas las regiones que quieras. Las marcadas con `*` son imprescindibles:

   | Región | Qué encuadrar |
   |---|---|
   | **Reloj** \* | solo los dígitos `MM:SS`, sin texto alrededor |
   | **Cuarto** \* | `Q3`, `3er cuarto`, `3`… |
   | **Marcador (ambos equipos)** \* | los dos números; o usa las dos regiones separadas |
   | **Bloque de líneas y cuotas** \* | el recuadro con las líneas y sus cuotas OVER/UNDER |
   | Título del mercado | `3.er Cuarto - Total de puntos` (**muy recomendable**, ver §6) |
   | Nombre equipo A / B | opcional, solo estético |
   | Desglose por cuartos | si la casa lo muestra, evita tener que teclear nada (ver §7) |
   | Ancla de referencia | un elemento fijo; permite recolocar todo si mueves el navegador |

5. Pulsa **Probar lectura de todas**: verás el texto exacto que saca el OCR de cada
   región. Ajusta los rectángulos hasta que el texto salga limpio. Este paso ahorra
   muchísimos disgustos después.
6. **Guardar**.

Consejos para que el OCR acierte:

- Encuadra **justo** el dato, con un par de píxeles de margen. Sobra de todo lo demás.
- No incluyas iconos, escudos ni bordes de colores dentro del rectángulo.
- Usa el zoom del navegador (`Ctrl` + `+`) para agrandar los números pequeños; después
  vuelve a dibujar las regiones con ese zoom y **no lo cambies** durante el partido.
- Si cambias de resolución o de escala de Windows, crea un perfil aparte.

---

## 6. Durante el partido

1. Elige el perfil y pulsa **INICIAR** (o `F8`).
2. En unos segundos aparecen reloj, cuarto, marcador y **todas** las líneas evaluadas.
3. Observas el tablero hasta que una línea te interesa. La tarjeta grande enfoca sola la
   línea cuya cuota UNDER está más cerca de tu **cuota objetivo**; si haces clic en otra,
   manda tu elección (*Enfoque automático* vuelve al criterio de la cuota).
4. Cuando decides entrar, pulsas **FIJAR APUESTA** (o `F9`).
5. A partir de ahí sigues viendo el tablero **y** el seguimiento de tu apuesta. **La línea
   fijada ya no cambia** aunque la casa mueva la suya.
6. Al terminar, **FINALIZAR PARTIDO** guarda la sesión en la base de datos.

### Mercados soportados

| Mercado | Puntos que usa | Tiempo que le queda |
|---|---|---|
| **Partido** | total del partido | resto del cuarto + cuartos sin jugar |
| **1.ª mitad** | Q1 + Q2 | lo que falte de la primera mitad |
| **2.ª mitad** | Q3 + Q4 | lo que falte de la segunda mitad |
| **Q1 … Q4** | puntos de ese cuarto | lo que quede de ese cuarto |

Cada línea se calcula **contra su propio mercado**. Una línea del Q3 nunca se compara con
los puntos del Q2, y una de 1.ª mitad nunca acaba mezclada con las del partido.

### Varios mercados a la vez y frescura

La aplicación lee **la pantalla**, así que solo puede observar la pestaña que la casa está
mostrando. Los demás mercados conservan su última lectura, **con su antigüedad siempre a
la vista**:

| Estado | Significa |
|---|---|
| **EN VIVO** | visible ahora y confirmado |
| **RECIENTE** | no visible, leído hace pocos segundos |
| **DESACTUALIZADO** | hace demasiado que no se observa |
| **EN REVISIÓN** | visible, con una lectura nueva pendiente de confirmar |
| **NO DISPONIBLE** | sin datos suficientes |

Los umbrales (5 s y 15 s por defecto) se configuran en **CRITERIOS**.

**Limitación inherente, dicha sin rodeos:** un mercado que no está visible **no puede
considerarse actualizado**. La aplicación nunca lo disimula. Para refrescar un mercado
desactualizado basta con **volver a mostrar su pestaña** en el navegador unos segundos.

### Navegación entre pestañas

Navegas **tú**, a mano. No hay automatización de clics, ni Selenium, ni lectura del DOM.
La aplicación detecta qué mercado estás viendo por el ROI del **título del mercado**; si tu
casa no muestra un título legible, elígelo en el desplegable **Mercado visible**.

Durante el cambio de pestaña, mientras el título nuevo aún no está confirmado, la
aplicación **no atribuye ninguna línea a ningún mercado** y lo avisa. Es la salvaguarda
que impide que las líneas del Partido acaben registradas como si fueran del Q2.

### Los dos modos

| Modo | Cuándo | Qué muestra |
|---|---|---|
| **BUSCANDO ENTRADA** | todavía no has apostado | todas las líneas con sus señales; es el modo principal |
| **APUESTA FIJADA** | tras pulsar `F9` | lo mismo **más** el seguimiento de tu línea congelada |

Tu apuesta queda atada a **su** mercado: si fijas `Partido UNDER 180.5` y luego te vas a
mirar el Q3, la apuesta se sigue calculando contra el mercado de partido. El mercado
visible y la apuesta fijada son cosas distintas.

### Tus criterios (botón **CRITERIOS**)

| Parámetro | Inicial | Para qué |
|---|---|---|
| Ritmo de referencia | 4.00 pts/min | con qué comparas el ritmo necesario |
| Cuota UNDER objetivo | 1.80 | qué línea se enfoca sola en la tarjeta grande |
| Umbrales de señal | +1.00 / +0.30 / −0.30 | dónde empieza cada nivel de la escala |
| Tramo final | 60 s | aviso independiente; **no** altera ningún cálculo |
| Frescura | 5 s / 15 s | cuándo un mercado pasa a RECIENTE y a DESACTUALIZADO |
| Colores | verde/amarillo/rojo | paleta invertible; la etiqueta de texto siempre se muestra |

Ninguno está escrito a fuego. El ritmo de referencia es **tu** criterio operativo, no una
constante del baloncesto.

### Cómo leer la señal

`margen = ritmo necesario − tu referencia`

| Señal | Significa |
|---|---|
| **MUY EXIGENTE** | superar la línea exigiría un ritmo muy superior a tu referencia |
| **EXIGENTE** | exigiría un ritmo superior |
| **NEUTRO** | el ritmo necesario está cerca de tu referencia |
| **PELIGROSO** | la línea se superaría con un ritmo inferior al de tu referencia |
| **NO EVALUABLE** | faltan datos confirmados; se indica el motivo |

No afirma que una apuesta vaya a ganar: es una escala matemática sobre tus parámetros.
Y no hay correcciones ocultas: que queden pocos puntos o poco tiempo **no** cambia la
clasificación; si quedan 5 puntos en 00:30, verás 10.00 pts/min y margen +6.00 tal cual,
con el aviso `TRAMO FINAL` aparte.

### Atajos de teclado

| Tecla | Acción |
|---|---|
| `F8` | iniciar / pausar la lectura |
| `F9` | fijar la apuesta seleccionada |
| `F10` | mostrar / ocultar el panel |
| `F11` | finalizar partido |
| `ESC` | cancelar la selección de una región |

Funcionan aunque el foco esté en Chrome (gracias a `pynput`). Si no se instaló, siguen
funcionando cuando la ventana del visor tiene el foco.

---

## 7. La línea que ves NO es siempre la del cuarto que se juega

Es el error más caro y la aplicación lo evita explícitamente.

El partido puede ir `Q2 00:04` mientras la casa ya muestra `3.er Cuarto - Total de puntos
40.5`. Esa línea pertenece al **Q3** y no debe compararse con los puntos del Q2.

Por eso conviene definir la región **Título del mercado**: cada línea queda atada a su
mercado y sus cálculos usan el acumulador de puntos y el tiempo restante correctos. Si
fijas esa línea del Q3 durante el Q2, el visor te dirá que van 0 puntos y quedan 10:00,
que es la verdad.

---

## 8. Puntos del cuarto al arrancar a mitad

La aplicación **nunca** supone que el marcador que ve al abrirse son los puntos del cuarto.
Los obtiene, por orden de prioridad:

1. **Desglose de la casa**, si has configurado esas regiones.
2. **Historial propio**, si la app estaba abierta cuando empezó el cuarto.
3. **Tú**, pulsando *Introducir marcador al empezar el cuarto*.

Hasta entonces, las líneas de ese cuarto aparecen como **NO EVALUABLE — FALTA MARCADOR
INICIAL Q3**, sin puntos ni ritmo inventados. El bloqueo es **por línea**: un mercado de
partido sigue funcionando con normalidad en el mismo tablero.

---

## 9. Fiabilidad de las lecturas

- Cada dato pasa de **RAW** a **CONFIRMED** solo tras varias lecturas coherentes.
- Reglas de validación: el marcador no baja, el reloj no sube dentro del cuarto, el cuarto
  no retrocede, las cuotas viven entre 1.01 y 20.00.
- Una cuota leída como `187` se marca como **no confirmada** y se propone `1.87`; nunca se
  corrige a escondidas.
- Un dato confirmado **caduca**: si el OCR se pierde, vuelve a `--` en lugar de congelarse.
- Cuando la casa cambia de línea, el tablero avisa con **LÍNEA EN REVISIÓN** mientras la
  confirma, en vez de seguir enseñando la anterior como si fuera vigente.
- El reloj usa *confianza temporal*: se acepta al instante si es coherente con el tiempo
  real transcurrido, lo que permite refrescarlo segundo a segundo.

La pestaña **Diagnóstico** muestra, para cada lectura: región, OCR bruto, OCR normalizado,
confianza, valor confirmado, estado, motivo del rechazo y milisegundos. Se puede exportar.

---

## 10. Generar el .exe

```bat
construir_exe.bat
```

o a mano:

```bat
pip install -r requirements-dev.txt
python -m pytest
python -m PyInstaller visorunder.spec --noconfirm
```

El resultado queda en `dist\VisorUnder\VisorUnder.exe`. Hay que **copiar la carpeta
entera**, no solo el .exe, porque incluye los modelos del OCR.

---

## 11. Solución de problemas

| Síntoma | Causa habitual | Solución |
|---|---|---|
| Todo en `--` | regiones mal colocadas | *Probar lectura de todas* en la configuración |
| El reloj salta o se queda pegado | el rectángulo incluye texto extra | recórtalo a los dígitos |
| Confunde `0` con `O`, `1` con `l` | fuente pequeña | sube el zoom del navegador y redefine la región |
| Cuotas absurdas (`187`) | el punto decimal no se ve | amplía un poco la región y aumenta el zoom |
| Lee líneas de otro mercado | falta el *Título del mercado* | defínelo |
| Se descuadró todo al mover el navegador | coordenadas desplazadas | define un **Ancla** o vuelve a dibujar las regiones |
| `No hay ningún motor OCR instalado` | falta RapidOCR | `pip install rapidocr-onnxruntime` (no hace falta si usas solo la extensión) |
| `EXTENSIÓN DESCONECTADA` con Chrome abierto | la extensión no está cargada, o el puerto no coincide | recarga la extensión en `chrome://extensions`; comprueba el puerto en su popup |
| El puente no arranca | el puerto 8765 está ocupado | cambia `bridge.port` en `settings.json` y el puerto en el popup de la extensión |
| Va lento / mucha CPU | frecuencia alta o regiones enormes | baja a 2 lecturas/s y recorta las regiones |
| Nada funciona y no sé por qué | — | pestaña **Diagnóstico** → *Exportar log* |

Ajustes útiles en el perfil: **frecuencia de lectura** (2–4/s es lo recomendado),
**confirmaciones exigidas** (más = más lento pero más seguro) y **caducidad de un dato**.

---

## 12. Dónde se guardan las cosas

Todo en tu equipo, en `%APPDATA%\VisorUnder`:

```
visorunder.db      base de datos SQLite (perfiles, historial, apuestas)
settings.json      preferencias y tus criterios de entrada
logs\              registro de diagnóstico
```

Se guardan los datos **originales**: marcador, reloj, líneas y cuotas **por mercado**,
timestamps, cuándo se observó cada mercado por última vez, y los criterios usados en la
sesión. Los márgenes, las señales y los estados de frescura **no** se guardan: son datos
derivados y se recalculan exactamente igual a partir de lo anterior.

No hay servidor, ni nube, ni cuenta, ni suscripción.

---

## 13. Desarrollo

```bash
pip install -r requirements-dev.txt
python -m pytest                              # 336 tests de Python
cd browser-extension && node --test tests/*.test.js   # 288 tests de JavaScript
```

La arquitectura y las decisiones técnicas están en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

---

## 14. Aviso

Herramienta de **lectura y cálculo**. No garantiza que el OCR lea siempre bien: comprueba
los datos importantes contra la pantalla. Apostar conlleva riesgo de pérdida económica.
