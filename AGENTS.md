# Guía del repositorio

## Arquitectura

- Aplicación local de Windows en Python 3.10+ y PySide6, con código en `src/visorunder/`.
- Extensión BetPlay Manifest V3 sin dependencias npm en `browser-extension/`.
- Flujo DOM: `scoreboard.js` → `gamestate.js` → `payload.js` → puente HTTP local → `bridge/schema.py` y `bridge/converter.py` → `BrowserSource` → `LiveReader` → dominio/cálculos → UI.
- El puente escucha solo en `127.0.0.1`; no se deben ampliar permisos, orígenes ni endpoints sin necesidad explícita.
- DOM aporta observaciones; Python conserva la única lógica de datos derivados.

## Rama e integración

- Rama productiva: `main`.
- La integración de extensión y puente se desarrolla en `claude/browser-python-bridge` y corresponde al PR #3.
- No trabajar directamente en `main`, no fusionar el PR #3 y no hacer force-push.

## Verificación

```powershell
python -m pytest
Set-Location browser-extension
node --test tests/*.test.js
```

- Dependencias Python: `requirements.txt` y `requirements-dev.txt`; `pytest-qt` se instala en el entorno de pruebas cuando se ejecuta la suite UI.
- No existe build JavaScript: la extensión carga directamente los archivos declarados en `manifest.json`.
- Antes de publicar, revisar `git diff`, `git status` y que el manifiesto siga referenciando archivos existentes.

## Reglas sensibles

- Desconocido es `None`/`null`/`--`; nunca convertirlo en cero.
- Los totales del marcador Kambi salen de `scoreboard-grid-score`; los parciales, de `scoreboard-grid-item`. La semántica estructural manda sobre heurísticas.
- Mantener OCR y marcador inicial manual como fallback cuando el DOM no aporte desglose fiable.
- `GameRules` decide duraciones FIBA/NBA y overtime; no codificar diez minutos en cálculos.
- Reutilizar `GeneralMetrics.half_pace` y `LineEvaluation.margin_vs_half_pace`; no duplicar fórmulas de ritmo o margen.
- El cambio de event ID debe iniciar estado/sesión nuevos sin conservar equipos, parciales ni métricas del partido anterior.
- `gameState` y `visibleMarket`/`lines` son ejes independientes del mismo protocolo: un update de uno no rejuvenece ni borra silenciosamente el otro.
- Una observación `lines=[]` conserva la última línea solo como histórica y debe marcar el mercado `STALE`; nunca actualizar su timestamp de confirmación.
- Un ancestro semántico `bet-offer-subcategory` es una frontera física: el escáner no puede subir al contenedor de submercados hermanos.

## Publicación y prueba real

- Publicación: commit(s) acotados, push a `origin/claude/browser-python-bridge` y actualización del PR #3; no merge.
- No hay CI/CD ni despliegue de servidor configurados. El artefacto publicado es la rama remota.
- Smoke test real: ejecutar `python run.py`, recargar la extensión desempaquetada desde `browser-extension/`, abrir un partido BetPlay y comprobar actualización DOM sin entrada manual.
- Rollback: revertir el commit afectado en la rama de integración y volver a cargar la extensión; la app no aplica migraciones ni infraestructura para esta fase.
