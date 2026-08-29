# P1-33 — Upgrade y compatibilidad

Estado: DONE técnico local. No se ha publicado ningún artefacto ni se ha cambiado la versión `0.1.0`.

## Baseline y target

- Baseline local verificable: `dist/GTFS-Explorer-Setup-0.1.0-win-x64.exe`, `0.1.0-rc1`, SHA-256 `1149d67ff41dd73d67be24e53576cf80b209b742631c5c22240cb4ed3d61892f`.
- Provenance: artefacto local conservado en `dist/`; sin commit fuente histórico verificable y no presentado como release pública.
- First-release: `0.1.0` está documentada como primera versión instalable prevista; el upgrade histórico público es `NOT_APPLICABLE / FIRST_RELEASE`. Se ejecutó, además, installer→installer contra el candidato local anterior.
- Target installer P1-32: `GTFS-Explorer-Setup-0.1.0-P1-32-packaging-20260828-win-x64.exe`, SHA-256 `54297c2695327697a6e1091bf36b42f2f34ef588bf8b93a8c027eb9ca71735ec`.
- Target portable: `GTFS-Explorer-Portable-0.1.0-P1-32-packaging-20260828-win-x64.zip`, SHA-256 `8450d974df386ff6d1b1d852febbf9bb78e031493c5246be5e44e3d46232f050`.
- Los hashes coinciden con `release-manifest.json`; los artefactos P1-32 no se modificaron.

## Installer, portable y datos

`tools/upgrade_smoke.ps1` ejecutó en temporales baseline→target sobre la misma carpeta, runtime smoke de ambos, comprobación de executable path, registro HKCU, accesos directos, uninstall y preservación de datos. También extrajo el portable en carpeta nueva y pasó su runtime smoke. No quedaron procesos vivos ni instalaciones temporales.

Projects, Exports, Diagnostics, recovery, settings y mapas están fuera de `$INSTDIR`. OFFLINE, ayuda y Qt/WebEngine del target quedaron cubiertos por los packaging/runtime smokes. No se usaron proyectos, mapas ni Documents reales.

La instalación soportada requiere cerrar la aplicación. No se ha añadido detección/matanza de procesos; el escenario GUI abierta no se certifica como upgrade soportado y queda como IMPORTANTE-PERO-NO-BLOQUEANTE para una futura protección explícita.

## Proyectos y migraciones

`tests/test_p1_33_upgrade.py` cubre schema 8→9 con proyecto/feed, preservación de identidad y `IMPORTED`, un job `INVALID` que no se convierte en `FAILED`, backup `.pre-migration.bak`, atomicidad ante SQL roto, idempotencia y hashes de artefactos. El schema actual es 9 y no se backfillea historial de operaciones. `project.json`, `source_row`, exports, Mini-GTFS, recovery y locking se cubren mediante la regresión existente relacionada; no se inventa provenance legacy.

## Verificación y clasificación

- Tests P1-33: `4 passed`; regresión DuckDB/recovery/locking/P1-33: `32 passed`.
- Upgrade smoke real: `UPGRADE_SMOKE=PASS`.
- E2E: `11 passed`; suite completa: `477 passed` en `498.09 s`.
- Ruff format, Ruff lint, mypy, `git diff --check` y `tools/check.ps1`: `PASS`.
- BLOCKERS: ninguno.
- IMPORTANTE-PERO-NO-BLOQUEANTE: GUI anterior abierta no certificada; no existe release pública N-1 aplicable.
- BACKLOG: protección explícita frente a aplicación abierta y validación manual en VM limpia.
- Artifacts changed/rebuilt: ninguno; hashes sin cambios.
- `P1-34_READY = NO`; no se inicia P1-34 ni se autoriza publicación.

P1-33-UPGRADE-DONE
