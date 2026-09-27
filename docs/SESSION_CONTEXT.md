# Session context

## Product

GTFS Explorer Desktop, aplicación Windows local/offline-first para GTFS
Schedule.

## Estado vigente

Consultar `docs/CURRENT_STATE.md` para versión, baseline, schemas, aceptación y siguiente fase. Este documento solo fija contexto operativo estable y rutas.

## Stack

Python 3.12, PySide6/Qt Widgets + WebEngine, DuckDB, MapLibre y PMTiles.

## Non-negotiable rules

- GTFS original y `gtfs_*` inmutables.
- Ediciones con Working Copy, revisiones y ChangeSets.
- `domain` sin UI/DuckDB/filesystem; UI sin SQL.
- Una tarea primaria por chat; tests focales durante desarrollo.
- Validación integrada solo en su gate final.
- El commit, tag y publicación remota requieren un descriptor y autorización
  explícitos.

## Authorized task

Leer el descriptor activo. Sin descriptor o autorización expresa, no iniciar
una fase de producto.

## Context routing

- Arquitectura: `docs/ARCHITECTURE.md`; editor: `docs/0.2.0_PRODUCT_ARCHITECTURE.md`.
- Reglas GTFS: `docs/DOMAIN.md`.
- Decisiones: `docs/DECISIONS.md` y ADR concreto en `docs/adr/`.
- Orquestador legado: `docs/TASK_STATUS.json` solo si aplica.
- Histórico/gates: GTFS Explorer Engineering.
- Binarios/manifests/runtime: GTFS Explorer Artifacts.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
