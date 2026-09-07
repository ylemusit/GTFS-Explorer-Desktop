# GTFS Explorer Desktop

La fuente y el build del producto se mantienen en este repositorio. La evidencia
histórica y las decisiones de ingeniería se separan respectivamente en los
repositorios hermanos **GTFS Explorer Artifacts** y **GTFS Explorer Engineering**.
La documentación canónica de desarrollo y estructura está en `docs/`.

Aplicación Windows x64, portable y offline-first para explorar GTFS Schedule.

## Estado

Versión `0.2.1` (no publicada): aplicación Windows x64 portable y offline-first
para importar, explorar, validar, visualizar y exportar GTFS Schedule. El
release queda preparado localmente; la publicación no está iniciada.

Consulta [el checklist de release](docs/RELEASE_CHECKLIST.md), la [estructura
del repositorio](docs/REPOSITORY_STRUCTURE.md), el
[historial de cambios](CHANGELOG.md) y la [matriz de smoke](tests/packaging/SMOKE_MATRIX.md).

Para usar la aplicación, consulta la [guía de usuario](docs/USER_GUIDE.md).
La documentación técnica y de desarrollo está en la [guía de desarrollo](docs/DEVELOPER_GUIDE.md),
[arquitectura](docs/ARCHITECTURE.md), [build y release](docs/BUILD_AND_RELEASE.md),
[rendimiento](docs/PERFORMANCE.md),
[E2E](docs/E2E.md), [accesibilidad](docs/ACCESSIBILITY_CHECKLIST.md) y
[mapas offline](docs/MAPS_OFFLINE.md).

Para desarrollar y probar, consulta la [guía de desarrollo](docs/DEVELOPER_GUIDE.md)
y [testing](docs/TESTING.md). El contexto operativo interno está en
`docs/SESSION_CONTEXT.md`.

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
