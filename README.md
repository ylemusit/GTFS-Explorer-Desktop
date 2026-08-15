# GTFS Explorer Desktop

Aplicación Windows x64, portable y offline-first para explorar GTFS Schedule.

## Estado

Versión candidata local `0.1.0-rc1`: aplicación Windows x64 portable y
offline-first para importar, explorar, validar, visualizar y exportar GTFS
Schedule. La candidata no está publicada ni autorizada para distribución.

Consulta [el checklist de release](docs/RELEASE_CHECKLIST.md), el
[historial de cambios](CHANGELOG.md) y la [matriz de smoke](tests/packaging/SMOKE_MATRIX.md).

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
