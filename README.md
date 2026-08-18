# Visor UNDER

Aplicación **de escritorio, local y para Windows** que lee en pantalla el estado de un
partido de baloncesto y las líneas que muestra tu casa de apuestas, y calcula en tiempo
real las métricas que importan para una apuesta **UNDER**.

> **Qué NO hace, por diseño:** no apuesta, no inicia sesión en ninguna casa, no pulsa
> botones, no usa APIs privadas ni servicios de pago, y **no predice nada**. No hay
> modelos, ni probabilidades inventadas, ni recomendaciones. Solo lee, valida y calcula.

---

## 1. Qué muestra

```
CAL IRVINE           43
CHINESE TAIPEI       31
TOTAL PARTIDO        74

Q3                05:28
JUGADO DEL CUARTO 04:32

PUNTOS Q3         19  (9 - 10)
PROMEDIO CUARTO   4.19 pts/min
PROMEDIO PARTIDO  3.02 pts/min

MI APUESTA (FIJADA)
UNDER 40.5 @ 1.87
MERCADO ACTUAL: UNDER 42.5 @ 1.82

LÍMITE PARA PERDER      41
FALTAN PARA PERDER
        22 PUNTOS
RITMO NECESARIO PARA PERDER
        4.02 pts/min

PARA EL DESCANSO  YA PASÓ
PARA EL FINAL     15:28
```

Si un dato no se puede leer con seguridad, aparece `--`. **Nunca** un número inventado.

---

## 2. Instalación

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

## 3. Ejecución

```bat
python run.py
```

Modo de prueba con un **partido simulado**, sin necesidad de abrir ninguna casa ni de
configurar regiones (ideal para el primer contacto):

```bat
python run.py --demo
```

---

## 4. Configuración inicial: crear un perfil

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

## 5. Uso durante el partido

1. Elige el perfil y pulsa **INICIAR** (o `F8`).
2. En unos segundos aparecen reloj, cuarto, marcador y las líneas disponibles.
3. Haz clic en la línea UNDER que estás considerando.
4. Pulsa **FIJAR APUESTA** (o `F9`).
5. A partir de ahí, todo se actualiza solo. **La línea fijada ya no cambia** aunque la casa
   mueva la suya: verás a la vez `MI APUESTA` y `MERCADO ACTUAL`.
6. Al terminar, **FINALIZAR PARTIDO** guarda la sesión en la base de datos.

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

## 6. La línea que ves NO es siempre la del cuarto que se juega

Es el error más caro y la aplicación lo evita explícitamente.

El partido puede ir `Q2 00:04` mientras la casa ya muestra `3.er Cuarto - Total de puntos
40.5`. Esa línea pertenece al **Q3** y no debe compararse con los puntos del Q2.

Por eso conviene definir la región **Título del mercado**: cada línea queda atada a su
mercado y sus cálculos usan el acumulador de puntos y el tiempo restante correctos. Si
fijas esa línea del Q3 durante el Q2, el visor te dirá que van 0 puntos y quedan 10:00,
que es la verdad.

---

## 7. Puntos del cuarto al arrancar a mitad

La aplicación **nunca** supone que el marcador que ve al abrirse son los puntos del cuarto.
Los obtiene, por orden de prioridad:

1. **Desglose de la casa**, si has configurado esas regiones.
2. **Historial propio**, si la app estaba abierta cuando empezó el cuarto.
3. **Tú**, pulsando *Introducir marcador al empezar el cuarto*.

Hasta entonces, `PUNTOS Q3` y `PROMEDIO Q3` muestran `--`. El total del partido y las
métricas de mercado de partido sí funcionan desde el primer segundo.

---

## 8. Fiabilidad de las lecturas

- Cada dato pasa de **RAW** a **CONFIRMED** solo tras varias lecturas coherentes.
- Reglas de validación: el marcador no baja, el reloj no sube dentro del cuarto, el cuarto
  no retrocede, las cuotas viven entre 1.01 y 20.00.
- Una cuota leída como `187` se marca como **no confirmada** y se propone `1.87`; nunca se
  corrige a escondidas.
- Un dato confirmado **caduca**: si el OCR se pierde, vuelve a `--` en lugar de congelarse.
- El reloj usa *confianza temporal*: se acepta al instante si es coherente con el tiempo
  real transcurrido, lo que permite refrescarlo segundo a segundo.

La pestaña **Diagnóstico** muestra, para cada lectura: región, OCR bruto, OCR normalizado,
confianza, valor confirmado, estado, motivo del rechazo y milisegundos. Se puede exportar.

---

## 9. Generar el .exe

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

## 10. Solución de problemas de OCR

| Síntoma | Causa habitual | Solución |
|---|---|---|
| Todo en `--` | regiones mal colocadas | *Probar lectura de todas* en la configuración |
| El reloj salta o se queda pegado | el rectángulo incluye texto extra | recórtalo a los dígitos |
| Confunde `0` con `O`, `1` con `l` | fuente pequeña | sube el zoom del navegador y redefine la región |
| Cuotas absurdas (`187`) | el punto decimal no se ve | amplía un poco la región y aumenta el zoom |
| Lee líneas de otro mercado | falta el *Título del mercado* | defínelo |
| Se descuadró todo al mover el navegador | coordenadas desplazadas | define un **Ancla** o vuelve a dibujar las regiones |
| `No hay ningún motor OCR instalado` | falta RapidOCR | `pip install rapidocr-onnxruntime` |
| Va lento / mucha CPU | frecuencia alta o regiones enormes | baja a 2 lecturas/s y recorta las regiones |
| Nada funciona y no sé por qué | — | pestaña **Diagnóstico** → *Exportar log* |

Ajustes útiles en el perfil: **frecuencia de lectura** (2–4/s es lo recomendado),
**confirmaciones exigidas** (más = más lento pero más seguro) y **caducidad de un dato**.

---

## 11. Dónde se guardan las cosas

Todo en tu equipo, en `%APPDATA%\VisorUnder`:

```
visorunder.db      base de datos SQLite (perfiles, historial, apuestas)
settings.json      preferencias
logs\              registro de diagnóstico
```

No hay servidor, ni nube, ni cuenta, ni suscripción.

---

## 12. Desarrollo

```bash
pip install -r requirements-dev.txt
python -m pytest          # 142 tests
```

La arquitectura y las decisiones técnicas están en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

---

## 13. Aviso

Herramienta de **lectura y cálculo**. No garantiza que el OCR lea siempre bien: comprueba
los datos importantes contra la pantalla. Apostar conlleva riesgo de pérdida económica.
