# P1-34 — Release Candidate

Fecha de cierre técnico: 2026-08-29. P1-34B permanece corregido y auditado;
este RC se reconstruyó desde el source exacto posterior al fix.

## Identidad y artefactos

- Producto/version: GTFS Explorer Desktop `0.1.0`.
- RC: `0.1.0-rc1`; publicación no iniciada.
- Source: `agent/align-github`, commit `3cfccdba7554ca815f4eff77d3cb376b8eb228da`.
- Worktree: no limpio (`148` modificaciones tracked y `53` archivos no tracked al registrar el build); no se hizo commit, tag, push ni publicación.
- Toolchain: Python `3.12.10`, Nuitka `2.6.9`, NSIS `3.12 Unicode`, PySide6 `6.8.3`, DuckDB `1.1.3`, Shapely `2.1.2`.
- Directorio RC: `dist/rc/P1-34C-20260829/`.

| Artefacto | Bytes | SHA-256 |
|---|---:|---|
| `GTFS-Explorer-Setup-0.1.0-rc1-win-x64.exe` | 100624274 | `a4d4f8212df3263340ea3bbe77e50b1bcb5dd8f9537273bc4207d47dec18d608` |
| `GTFS-Explorer-Portable-0.1.0-rc1-win-x64.zip` | 136075687 | `4d5ff625e649fcac276f683d13825853b67256ce014b3286b2fa6863ed97f667` |

El manifest, `SHA256SUMS.txt`, SBOM CycloneDX 1.5 (incluido Shapely 2.1.2), licencias y avisos fueron
regenerados para este build. Los artefactos anteriores están supersedidos,
separados y no se reutilizaron. Los ZIP/EXE finales no se modificaron después
del cálculo de hashes.

## Gates verificados

- `SOURCE_GATE=PASS`: `tools/check.ps1`, Ruff format/lint, mypy, `git diff --check` y suite `478 passed` en 508,08 s.
- `LOCK_REGRESSION=PASS`: focal locking/workspace/recovery/upgrade `29 passed`; la evidencia post-fix conserva el estrés real de 50 carreras: 50 ganadores, 50 perdedores bloqueados, 0 `PermissionError` crudos, 0 dobles ganadores y 0 locks residuales.
- `E2E_GATE=PASS`: 11 journeys incluidos en la suite.
- `PORTABLE_BUILD=PASS`, `INSTALLER_BUILD=PASS`, `NSIS_BINARY_GATE=PASS`, `UNICODE_GATE=PASS`.
- `METADATA_GATE=PASS`: el EXE portable expone `ProductName=GTFS Explorer Desktop`, descripción correcta, `ProductVersion/FileVersion=0.1.0.0`, `InternalName=GTFS Explorer` y `OriginalFilename=GTFS Explorer.exe`; icono embebido validado por el build de producto.
- `PACKAGE_SMOKE=PASS`, `PORTABLE_SMOKE=PASS`: extracción nueva y runtime smoke con código 0.
- `QWEBENGINE_GATE=PASS`, `MAP_SMOKE=PASS`: `QWebEngineProcess.exe` y recursos presentes; mapa extraído en carpeta temporal sin espacios: `bridge_ready=true`, `package_loaded=true`, 48 píxeles azules, sin errores.
- `HELP_GATE=PASS`: ayuda, índice y búsqueda locales incluidos sin proyecto ni Internet.
- `UPGRADE_GATE=PASS`, `INSTALLED_SMOKE=PASS`, `UNINSTALL_GATE=PASS`, `USER_DATA_PRESERVATION=PASS`: P1-32 → RC, registro/accesos directos, runtime del instalado y limpieza verificados por `tools/upgrade_smoke.ps1`.
- `PRIVACY_PACKAGE_SCAN=PASS`, `FORBIDDEN_FILES=PASS`, `LICENSE_INVENTORY=PASS`, `SBOM=PASS`, `HASH_VERIFICATION=PASS`.

## Estado y aceptación

- `P1_COMPLETE=YES`
- `RC_READY=YES`
- `RELEASE_BLOCKERS=0`
- `PUBLICATION=NOT_STARTED`
- Signing: `UNSIGNED`.
- `PERFORMANCE_GATE=NOT_VERIFIED` para LARGE; no se hizo profiling.
- `MANUAL_SCREEN_READER=PENDING`; no hay certificación NVDA/JAWS/Narrator.

El siguiente paso es la aceptación de Yeison, no una aprobación ya concedida.
Checklist: instalar y revisar About/versión; crear/importar GTFS; rutas, RAW,
validación, mapa OFFLINE, exportación, cierre/reapertura, ayuda y portable.

El primer build local `rc1` quedó históricamente supersedido por P1-34B y no
es candidato válido. No se publicó ningún artefacto.

Propietario y autor: Yeison Arbey Carrillo Lemus. Todos los derechos reservados.
