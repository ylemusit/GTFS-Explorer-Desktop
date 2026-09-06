# GTFS Explorer Desktop

La fuente y el build del producto se mantienen en este repositorio. La evidencia
histórica y las decisiones de ingeniería se separan respectivamente en los
repositorios hermanos **GTFS Explorer Artifacts** y **GTFS Explorer Engineering**.
Consulta `docs/SESSION_CONTEXT.md` y `docs/CURRENT_STATE.md` para retomar una
tarea con el contexto operativo mínimo.

Aplicación Windows x64, portable y offline-first para explorar GTFS Schedule.

## Estado

Versión `0.2.0`: aplicación Windows x64 portable y offline-first
para importar, explorar, validar, visualizar y exportar GTFS Schedule. El
release queda preparado localmente; la publicación no está iniciada.

Consulta [el checklist de release](docs/RELEASE_CHECKLIST.md), el
[historial de cambios](CHANGELOG.md) y la [matriz de smoke](tests/packaging/SMOKE_MATRIX.md).

Para usar la aplicación, consulta la [guía de usuario](docs/USER_GUIDE.md).
La documentación técnica relacionada está en [rendimiento](docs/PERFORMANCE.md),
[E2E](docs/E2E.md), [accesibilidad](docs/ACCESSIBILITY_CHECKLIST.md) y
[mapas offline](docs/MAPS_OFFLINE.md).

Para continuar el proyecto, usa el [contexto de sesión](docs/SESSION_CONTEXT.md),
el descriptor de tarea y solo la documentación WARM relacionada.

## Desarrollo local

```powershell
uv sync --all-groups
pwsh -NoProfile -File .\tools\check.ps1
```

El comando canónico comprueba, en este orden, formato, lint, tipos y tests. No
modifica archivos ni silencia comprobaciones. Para ejecutar una comprobación
concreta durante el desarrollo:

```powershell
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest
```

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
