# Fase 2 — Release readiness

Fecha de ejecución: 2026-09-01.

## FASE 3 — RC2 local

RC2 queda preparado localmente con Portable, Setup, manifests y hashes
coherentes. `package_smoke`, portable runtime smoke, map smoke del build y
upgrade/installed smoke pasan. El gate final source pasó E2E `11 passed`, full
suite `526 passed`, `tools/check.ps1`, Ruff, mypy y `git diff --check`.

Artefactos: `dist/GTFS-Explorer-Portable-0.1.0-rc2-win-x64.zip` con SHA-256
`b99060d6201fe4459292ecd4bf1b0b72a92140500fbacbe4597af71f01ca79bd`, y
`dist/GTFS-Explorer-Setup-0.1.0-rc2-win-x64.exe` con SHA-256
`314545b35d7c965f2a1e3865c5801d427c6fa1b064f9fd86cc04f823ca60d20f`.

CTM fresh en Portable/Installed RC2 y aceptación visual nativa siguen
`NOT VERIFIED`; el round-trip Mini-GTFS acreditado es el E2E de source. No se
publica ni se hace push.

## Estado

`PHASE2_RELEASE_READINESS_STATUS = PHASE2-RELEASE-READY`

La Fase 2 se considera cerrada para preparar RC2. La evidencia de los
artefactos RC2 se registrará por separado después del build; esta ficha no
anticipa claims de CTM o smokes que todavía no se hayan ejecutado sobre RC2.

## CTM_FEED

- Path: `C:\Users\yeiso\Downloads\ctm-mallorca-es.zip`
- SHA256: `60CD4FCB34F95DD11BE3DF39BEA772AE643A18D28042B7CCA080A7CB0E08E794` — PASS
- El feed no se copia al repositorio ni se incluye en artefactos.

## CTM_SOURCE

- Import: `READY`; `import_job=READY`, fase `COMMITTING`; feed `IMPORTED`.
- Duración observada: aproximadamente 39m53s (incluida la configuración del harness).
- Validación: 0 incidencias; `VALID` equivalente del flujo de importación.
- Conteos: routes 79, trips 4.306, stops 789, stop_times 62.800,
  shapes 338.845.
- Progreso observable continuo en staging, normalización y validación; no hang.

## CTM_PORTABLE / CTM_INSTALLED

`NOT VERIFIED` para importación CTM fresca, validación, conteos y navegación
funcional en los binarios P2A exactos. La aceptación Windows comunicada por el
responsable permanece PASS para extracción, startup, maximización/taskbar,
resize, MapWindow, instalador, abrir aplicación y guía/README; no sustituye
esta regresión CTM empaquetada.

Artefactos P2A comprobados por hash:

- Portable: `2ce6e2e7c645587c99fab3fd85863cc19a18ecffbcf8f8474a48735e05b2b13f`
- Setup: `3193d19091217a6ac5f8e105d04b7140214095573a3bfd6059b621318bbca99b`

## EXPORT_PACK / FORMATS / MINI_GTFS_ROUNDTRIP

`NOT VERIFIED` en esta ejecución sobre CTM empaquetado. Queda pendiente la
selección multi-ruta, al menos dos servicios cuando proceda, resumen de
dependencias, exportación real y comprobación de IDs seleccionados. También
quedan pendientes los artefactos JSON, CSV, GeoJSON y Mini-GTFS y el
round-trip Mini-GTFS fresco (importación terminal, validación, conteos y
autocontención).

## HARNESS

Se corrigió únicamente `tools/package_smoke.ps1`: la comprobación de archivos
prohibidos usa rutas relativas al root extraído, por lo que una carpeta padre
llamada `ctm` ya no altera el resultado. Regresión `tests/test_package_smoke.py`:
PASS (`1 passed`). Ejecución real con salida `dist\ctm-harness-regression`:
`PACKAGE_SMOKE=PASS`, con ambos hashes P2A esperados.

## PERFORMANCE

`PRODUCT FUNCTIONAL = PASS` para Source. `CTM PERFORMANCE = SLOW`; la duración
observada excede el rango histórico comunicado y debe revisarse en backlog
post-0.1.0 si se reproduce. No se realizó optimización especulativa.

## TESTS

- E2E: incluido en la suite canónica, PASS.
- Full suite / `tools/check.ps1`: PASS, 524 tests, 482,14 s.
- Ruff format/check: PASS.
- mypy: PASS.
- `git diff --check`: PASS; solo avisos de normalización CRLF de Git.

## Blockers y backlog diferido

Blocker reproducible de cierre: faltan CTM fresh import/validation en Portable e
Installed P2A y el Export Pack/Mini-GTFS round-trip nativo correspondiente.

Backlog post-0.1.0: investigar la duración Source si vuelve a superar el rango
histórico. No se añaden features, KML/KMZ, cambios de mapa ni optimizaciones en
esta tarea.

Todos los derechos reservados.

Propietario y autor: Yeison Arbey Carrillo Lemus.
