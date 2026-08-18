# Arquitectura y decisiones técnicas

Documento de referencia del proyecto. Explica **qué se decidió y por qué**, para que
cualquier ampliación futura no rompa las garantías que hoy tiene la aplicación.

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
├── calculations/    matemáticas puras: métricas y resolución de ámbito por mercado
├── capture/         ROIs, backends de captura, re-anclaje por imagen
├── ocr/             abstracción de motor, motores concretos, preprocesado, estabilización
├── parsers/         texto OCR → valores tipados y validados
├── pipeline/        ciclo de lectura en vivo, seguimiento de mercado, modo demo
├── storage/         SQLite con migraciones y repositorios
├── ui/              PySide6: panel, mercado, selector de ROI, diagnóstico, atajos
├── config/          perfiles de casa, preferencias, rutas
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

`bets` guarda `line` y `odds` **congeladas**: `LockedBet` es una dataclass `frozen`, así
que es imposible mutarla por accidente.

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
- Nuevos motores OCR: implementar `OcrEngine` y registrarlo.
- Nuevas reglas de juego: crear un `GameRules` (la prórroga ya está contemplada).
- Gráficas del historial: los datos ya están en `market_snapshots` y `score_snapshots`.
