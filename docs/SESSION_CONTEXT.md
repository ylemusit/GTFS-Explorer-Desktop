# Session context

## Product

GTFS Explorer Desktop, aplicación Windows local/offline-first para GTFS
Schedule.

## Target

`0.2.0` en `feature/0.2.0-visual-editor`.

## Stack

Python 3.12, PySide6/Qt Widgets + WebEngine, DuckDB, MapLibre y PMTiles.

## Non-negotiable rules

- GTFS original y `gtfs_*` inmutables.
- Ediciones con Working Copy, revisiones y ChangeSets.
- `domain` sin UI/DuckDB/filesystem; UI sin SQL.
- Una tarea primaria por chat; tests focales durante desarrollo.
- Validación integrada solo en su gate final.
- Sin publicación, commit/tag, distribución ni cambios Defender sin autorización.

## Current critical state

RC1 0.2.0 y su gate de distribución Defender: PASS histórico. La auditoría
independiente pre-release detectó P1/P2; RC1 se conserva como evidencia pero
no es elegible para la versión final. Tras las correcciones se requiere un
nuevo Final Source Gate y una nueva RC. La aceptación humana nativa aún no se
ha realizado.

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
