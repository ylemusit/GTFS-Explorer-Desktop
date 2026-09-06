# Guía de desarrollo

## Entorno

En Windows x64, prepara el entorno con:

```powershell
uv sync --all-groups
```

El proyecto usa el layout `src/`, Python 3.12 y las versiones fijadas en
`pyproject.toml` y `uv.lock`. DuckDB, PySide6 y MapLibre se usan localmente;
el runtime no depende de una base de datos o servicio remoto.

## Límites entre capas

`domain` contiene reglas y contratos puros. `application` orquesta casos de
uso y trabajos. `infrastructure` implementa DuckDB, filesystem, importación,
validación, mapas y exportación. `presentation` contiene Qt y los modelos de
UI. El dominio no conoce Qt, DuckDB ni el filesystem y la UI no ejecuta SQL.

El feed original es inmutable. Las ediciones se expresan mediante Working
Copy, revisiones y ChangeSets; no se modifica silenciosamente `ORIGINAL_GTFS`.

## Comprobaciones

El gate combinado canónico es:

```powershell
pwsh -NoProfile -File .\tools\check.ps1
```

Durante el desarrollo usa checks focales (`ruff`, `mypy` o `pytest` según el
cambio). Las pruebas y fixtures permanentes viven en `tests/`; los harnesses
de una ejecución y la evidencia de gate van a Engineering o Artifacts.

Mantén los cambios pequeños, actualiza la documentación cuando cambie la
verdad actual y conserva las decisiones relevantes en `docs/adr/`. Antes de
cerrar un cambio revisa referencias, `git diff --check` y el estado de Git.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
