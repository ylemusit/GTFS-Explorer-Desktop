# Session context

## Product

GTFS Explorer Desktop, aplicación Windows local/offline-first para GTFS
Schedule.

## Target

`0.2.1` en `main`.

## Stack

Python 3.12, PySide6/Qt Widgets + WebEngine, DuckDB, MapLibre y PMTiles.

## Non-negotiable rules

- GTFS original y `gtfs_*` inmutables.
- Ediciones con Working Copy, revisiones y ChangeSets.
- `domain` sin UI/DuckDB/filesystem; UI sin SQL.
- Una tarea primaria por chat; tests focales durante desarrollo.
- Validación integrada solo en su gate final.
- Sin publicación ni push remoto; el cierre local de la release se ejecuta solo
  con un descriptor y autorización explícitos.

## Current critical state

GTFS-021 y GTFS-022 están cerrados. La última certificación integrada de fuente
registró 641 passed, 0 failed y 1 skip legítimo. La aceptación ALSA confirmó
36.304 incidencias detectadas y persistidas, 0 omitidas y
`VALID_WITH_NOTICES`; no debe repetirse durante el cierre de release.

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
