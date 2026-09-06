# DEC-002 — DuckDB como motor único por proyecto

Fecha: 2026-08-11

Estado: Aceptada

## Decisión preservada

Fecha: 2026-08-11

Estado: Aceptada

DuckDB persistirá staging, modelo tipado y derivados. No habrá servidor ni ORM. Se aplicarán paginación, límites de memoria/temporales y conexión por job/thread. Revisar si benchmarks reproducibles incumplen los límites de v1.0.

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
