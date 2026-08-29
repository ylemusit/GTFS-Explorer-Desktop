# Estado actual del proyecto

Última actualización: 2026-08-29

## P1-34C — Release Candidate — DONE

Se reconstruyó el RC local `0.1.0-rc1` después del fix P1-34B, desde el
source `3cfccdba7554ca815f4eff77d3cb376b8eb228da` en `agent/align-github`.
Los artefactos están aislados en `dist/rc/P1-34C-20260829/`; el instalador y
el portable proceden del mismo source y no se publicaron.

Setup: `100624274` bytes, SHA-256
`a4d4f8212df3263340ea3bbe77e50b1bcb5dd8f9537273bc4207d47dec18d608`.
Portable: `136075687` bytes, SHA-256
`4d5ff625e649fcac276f683d13825853b67256ce014b3286b2fa6863ed97f667`.

Gates obligatorios PASS: source (`tools/check.ps1`, 478 tests), locking focal,
E2E, builds portable/NSIS, metadata PE, Unicode, ayuda, QWebEngine, mapa,
portable/installed smoke, upgrade, uninstall, preservación de datos, privacidad,
archivos prohibidos, licencias, SBOM y hashes. `P1_COMPLETE=YES`, `RC_READY=YES`,
`RELEASE_BLOCKERS=0`, `PUBLICATION=NOT_STARTED`.

El primer `rc1` provisional queda supersedido por P1-34B y se conserva separado
como evidencia histórica. Siguiente fase: aceptación del usuario. Performance
LARGE sigue `NOT_VERIFIED`, screen reader manual `PENDING` y signing `UNSIGNED`.

## P1-34B — Carrera Windows de Workspace Lock — FIXED

Se corrigió el release blocker de la adquisición concurrente de
`.writer.lock`. En Windows, durante el bootstrap de un sentinel vacío, un
perdedor podía recibir `PermissionError` en `handle.flush()` cuando otro writer
ya tenía bloqueado el byte inicial; el `close()` de su buffer pendiente podía
enmascarar la conversión a la excepción de dominio. El error de
`msvcrt.locking()` confirmado como contención se normaliza a
`ProjectWriterLockedError`; un `PermissionError` de filesystem sin evidencia
de writer activo sigue siendo distinguible. Se mantienen `ACTIVE`, `STALE` e
`INVALID`, la recuperación tras crash, release idempotente y
`Path.resolve()`.

Evidencia histórica: estrés real de 50 carreras (50 ganadores, 50 perdedores
bloqueados, 0 PermissionError crudos, 0 dobles ganadores y 0 sentinels
residuales), focal locking/recovery/E2E/upgrade `37 passed`, y suites completas
consecutivas `478 passed`. El RC posterior se cerró en P1-34C.

## P1-33 — Upgrade / compatibilidad — DONE

Se añadió `docs/P1_33_UPGRADE.md`, la focal `tests/test_p1_33_upgrade.py` y el
smoke `tools/upgrade_smoke.ps1`. El baseline local y el target P1-32 fueron
verificados por hash; installer→installer, portable, registro, accesos
directos, uninstall y preservación de datos pasaron en temporales. La matriz
schema 8→9 cubre datos, `INVALID`, backup, atomicidad e idempotencia. La suite
completa quedó en `477 passed`, con Ruff, mypy, `git diff --check` y
`tools/check.ps1` en PASS. No se modificó la versión ni se publicó. GUI abierta
no certificada: IMPORTANTE-PERO-NO-BLOQUEANTE; P1-34 no se inicia.

## P1-32 — Packaging real Windows — DONE

Se construyeron desde el mismo estado de código un portable standalone real con
Nuitka/pyside6-deploy y un instalador NSIS Unicode real. La salida aislada está
en `dist/P1-32-packaging-20260828/` e incluye `release-manifest.json`,
`checksums.txt` y sidecars SHA-256. El portable contiene la ayuda exigida por
`docs/HELP_PACKAGING_MANIFEST.json`, licencias/SBOM, MapLibre y Qt/WebEngine;
`tools/package_smoke.ps1` pasa y no detecta archivos de desarrollo prohibidos.

La compilación PE expone identidad canónica: GTFS Explorer Desktop, versión
0.1.0, `InternalName=GTFS Explorer`, `OriginalFilename=GTFS Explorer.exe`,
autor y copyright. El smoke runtime y gráfico del portable pasan
(`bridge_ready=True`, `route_blue_pixels=48`); la instalación, runtime del EXE
instalado, desinstalación y reinstalación limpia pasan. La desinstalación retira
EXE, recursos, accesos directos y registro, preservando proyectos y el sentinel
de `Documents/GTFS Explorer/Projects`.

Evidencia final: tests de packaging/licencias/ayuda `24 passed`, E2E `11 passed`,
suite canónica `473 passed`, `tools/check.ps1: PASS`, Ruff format/lint, mypy y
`git diff --check: PASS`. El binario queda unsigned; screen reader avanzado,
upgrade P1-33, publicación y SmartScreen permanecen fuera de alcance.
`P1-33_READY = YES`.

## A031 — Actualización y revalidación de dependencias — DONE

El 2026-08-28 se actualizaron únicamente PySide6 6.8.2.1 → 6.8.3 y Shapely
2.0.7 → 2.1.2. `pyproject.toml` y `uv.lock` conservan restricciones exactas;
DuckDB 1.1.3, Nuitka 2.6.9, MapLibre/PMTiles, esbuild y las herramientas de
desarrollo se mantienen por compatibilidad y alcance. El entorno limpio Python
3.12.10 instaló correctamente y pasó el smoke de imports/Qt WebEngine/DuckDB/
Shapely/Nuitka. La focal de contratos y E2E quedó en 88 passed antes y 88
passed después. El detalle de decisiones y hallazgos está en
[`docs/A031_DEPENDENCY_UPDATE.md`](A031_DEPENDENCY_UPDATE.md). Ruff/mypy
mantienen sus versiones porque candidatos nuevos introdujeron fallos de gate
en código existente; `makensis` sigue fuera de A031 (`NSIS_BINARY_GATE =
PENDING_P1_32`).

## P1-27 + P1-28 — Windows Unicode/NSIS y diálogos nativos/i18n — DONE

El contrato NSIS productivo usa `installer.nsi` en UTF-8 con BOM y `Unicode
true`; conserva tildes y reutiliza la identidad canónica P1-25/26 para nombre,
versión, metadata Windows, instalador y desinstalador. La revisión de alcance
no encontró mojibake productivo (`Ã`, `Â` o `�`) ni conversiones ASCII evasivas.
Los textos de instalación, desinstalación, Add/Remove Programs, accesos
directos y filtros mantienen Unicode e identidad/versionado coherentes.

Se auditaron los usos productivos de `QFileDialog`, `QMessageBox`,
`QInputDialog` y diálogos propios. Los textos de GTFS Explorer pasan por la
infraestructura i18n existente; los diálogos siguen siendo nativos de Windows
cuando corresponde y no se intenta traducir el texto proporcionado por el SO
o Qt. Se verificaron títulos, filtros actuales, botones estándar cuando ya
aplican, locale, mensajes de error seguros, privacidad, cancelación sin
`FAILED` ni cambios de `last_*_dir`, y paths Unicode sobre la infraestructura
centralizada de P1-24.

Evidencia P1-27/28: formatter aplicado previamente; focal relacionada `70
passed`; regresión relacionada `86 passed`, incluidos los 11 E2E; suite
completa `464 passed`; `tools/check.ps1: PASS`; Ruff format/lint, mypy y
`git diff --check`: `PASS`. El dry-run de configuración es correcto y
`makensis` no está disponible en este entorno: `SKIPPED / TOOL_NOT_AVAILABLE`.
Por tanto `NSIS_BINARY_GATE = PENDING_P1_32`; no se compiló Setup.exe, ZIP
portable ni instalador final. BLOCKERS: ninguno. IMPORTANTE-PERO-NO-BLOQUEANTE:
la compilación/inspección binaria real queda para P1-32. BACKLOG: ninguno
adicional dentro de P1-27/28.

## P1-25 + P1-26 — Identidad, metadata y versión visible — DONE

`src/gtfs_explorer/product.py` es la fuente única de verdad para la versión
del producto (`0.1.0`) y la identidad estable de GTFS Explorer Desktop. El
runtime, `--version`, el generador JSON, el `importer_version`, los informes
de benchmark, los diagnósticos y la metadata de distribución consumen esa
identidad; `gtfs_explorer.__version__` se conserva únicamente como alias de
compatibilidad.

La versión se muestra en el título principal, la bienvenida y el nuevo diálogo
Acerca de. Este último expone producto, versión, build id seguro, edición,
revisión GTFS `2026-04-27`, arquitectura y ubicación local de datos, además de
la atribución de Yeison Arbey Carrillo Lemus y «Todos los derechos reservados».
Los diagnósticos incorporan el mismo contexto de identidad sin aceptar rutas,
secretos ni texto arbitrario del entorno.

El builder portable renderiza una copia efímera del spec con
`ProductName`, `FileVersion`, `ProductVersion`, `CompanyName`, descripción y
copyright para Nuitka. El instalador NSIS declara las mismas claves PE y el
manifiesto portable/NSIS conserva las versiones numéricas. La fuente versionada
no se modifica durante el build.

Evidencia P1-25/26: `tests/test_product_identity.py`, entrypoint, logging,
portable, NSIS y benchmark: `39 passed` en `138,30 s`; el gate final
`tools/check.ps1` pasó formato, Ruff, mypy y `459 passed` en `421,88 s`. El
contrato de metadata se ha comprobado mediante tests y dry-run del builder,
pero no se ha generado un nuevo EXE/ZIP/setup en esta tarea. BLOCKERS: ninguno.
IMPORTANTE-PERO-NO-BLOQUEANTE: la inspección de recursos PE de un binario
recién construido queda para la ejecución con la toolchain Windows/NSIS
disponible. BACKLOG: firma, publicación y matriz final de packaging.

## P1-24 — Directorios predecibles y preferencias locales — DONE

`ApplicationPaths` centraliza las ubicaciones instaladas: proyectos en
`Documents/GTFS Explorer/Projects`, fuentes de importación en `Imports`,
exportaciones e informes en `Exports`, fuentes PMTiles en `Maps` y diagnósticos
en `Diagnostics`. La biblioteca gestionada de mapas conserva
`%LOCALAPPDATA%/GTFS Explorer/maps`; recovery continúa dentro de
`<workspace>/recovery`; logs, settings, caché y temporales permanecen en la
raíz técnica local. El workspace portable existente mantiene sus rutas
relativas.

Los diálogos de proyecto, importación, exportación, PMTiles, diagnóstico,
informe y vista RAW reciben defaults centralizados, crean carpetas de usuario
solo al iniciar la operación y recuerdan únicamente `last_project_dir`,
`last_import_dir`, `last_export_dir`, `last_pmtiles_import_dir` y
`last_diagnostic_dir` en settings local. Una carpeta ausente o inaccesible
vuelve al default o a un padre utilizable; no se mueven fuentes existentes ni
se agregan rutas a DuckDB, historial, recovery, metadata pública o manifests.
La resolución usa `QStandardPaths.DocumentsLocation` con fallback
multiplataforma y no escribe en `Program Files`.

Se añadieron regresiones para defaults, lazy creation, Unicode/Documentos
redirigido, persistencia, fallback por permisos, aislamiento de `Program
Files`, diálogos y exportación. No se modificaron schema, E2E ni packaging.

Evidencia P1-24: `tests/test_p1_24_directories.py`: `7 passed`; focal de
P1-24, exportación, RAW, mapas, workspace, recovery y E2E: `128 passed`; E2E
aislado: `11 passed`; suite completa: `455 passed` en `397,03 s`. Ruff y
mypy focal pasan; `tools/check.ps1`: PASS con formato, Ruff, mypy sobre `src`
y suite `455 passed` en `408,00 s`; `git diff --check`: PASS (solo avisos de
conversión de finales de línea de Git). BLOCKERS: ninguno.
IMPORTANTE-PERO-NO-BLOQUEANTE: no se realiza una prueba visual pixel-perfect
de diálogos nativos; la redirección de Documents se cubre mediante el resolver
inyectable y regresiones de rutas. BACKLOG: rebuild portable/NSIS limpio y
matriz final de packaging.

## P1-23 — Journeys E2E sobre arquitectura productiva — DONE

Se añadió `tests/test_e2e_journeys.py`, una matriz compacta de 11 recorridos
reales con `pytest.mark.e2e`: happy path, feed `INVALID` pero importable,
cancelación inicial, cancelación de reimportación conservando el feed previo,
exportación JSON/CSV/GeoJSON/Mini-GTFS con manifest e historial, aislamiento de
proyectos, cierre/reapertura, lock entre procesos, safe recovery, mapas
offline-first y fallo técnico `FAILED`. Los casos usan fixtures ficticios,
DuckDB file-backed y recursos temporales; no acceden a feeds externos. El
WebEngine offscreen se cubre con un doble funcional limitado al render, sin
convertir la prueba en un assert de píxeles; E2E-10 mantiene la política e
interceptor productivos de red.

La matriz está operativizada en [`docs/E2E.md`](E2E.md), con contratos,
timeouts, limpieza, privacidad y clasificación de hallazgos. Se registró el
marker `e2e` en `pyproject.toml`; no se modificó producción ni se amplió el
alcance a portable, NSIS o la optimización de staging LARGE.

Evidencia P1-23: `pytest -q -m e2e tests/test_e2e_journeys.py`: `11 passed` en
49,15 s; focal afectado: `157 passed` en 140,30 s; `tools/check.ps1`: PASS,
suite completa `448 passed` en 466,29 s; Ruff, mypy y `git diff --check`: PASS.
La fixture happy puede presentar `VALID_WITH_WARNINGS` por advertencias de
calidad no bloqueantes, pero el job es `READY`; `INVALID` sigue siendo distinto
de `FAILED`. BLOCKERS: ninguno. IMPORTANTE-PERO-NO-BLOQUEANTE: el render visual
WebEngine offscreen permanece fuera de esta matriz. BACKLOG: prueba pixel-based
en Windows con renderer disponible y profiling/optimización de staging LARGE.

## P1-22 — Progreso granular y actividad observable — DONE

`ImportProgress` conserva el progreso legado cuando existe un total fiable y
añade `ProgressMode.DETERMINATE`/`INDETERMINATE`, detalle, recuento y unidad.
Las fases de importación sin total real ya no se presentan como porcentajes de
fases. Staging emite actividad por lote coalescida cada 250 ms como máximo,
mostrando solo el basename del archivo y las filas realmente insertadas; no
realiza una segunda pasada. Normalización informa sus grupos reales (core,
shapes y opcionales) y validación informa la regla activa, sin inventar filas
internas de DuckDB.

La UI reutiliza el `QThread`/señales de P1-02, muestra barra indeterminada,
detalle, actividad, elapsed monotónico y `Cancelando…`, y limpia el estado al
terminalizar. No se introducen ETA, schema, framework paralelo, cambios en
P0-004, packaging ni optimización de staging LARGE. Mapas P1-18 conservan su
descarga streaming con progreso/cancelación; recovery no tiene una operación
visible prolongada equivalente en el alcance actual.

Evidencia P1-22: tests focales `36 passed`, suite completa `437 passed`,
`tools/check.ps1: PASS`, Ruff, mypy y `git diff --check: PASS`. Benchmark SMALL
posterior: `75,572 s`, `READY`, 0 incidencias; baseline P1-21 documentada:
`71,892 s`. La diferencia aislada del 5,1 % no es reproducible ni se atribuye
a la instrumentación. P1-21 LARGE sigue clasificado como `TIMEOUT` en staging,
hallazgo técnico pendiente de profiling y no bloqueante para P1-22.
BLOCKERS: ninguno. IMPORTANTE-PERO-NO-BLOQUEANTE: exportaciones productivas
siguen siendo síncronas y no requieren progreso granular mientras no alcancen
duraciones prolongadas acreditadas. BACKLOG: ETA honesta, progreso interno de
exportaciones pesadas y optimización/profiling de staging LARGE.

## P1-20 — Safe Recovery — DONE

La apertura ejecuta primero `inspect_recovery_state(workspace)`, con evaluación
separada de DuckDB canónica, `project.json`, lock, temporales y candidatos de
backup. La clasificación no se persiste en DuckDB y distingue `HEALTHY`,
descriptor recuperable, transitorio recuperable, candidato de restauración y
proyecto irrecuperable. P0-001 sigue gobernando el mismatch legacy conocido y
DuckDB continúa siendo la fuente canónica: un descriptor no sobrescribe la DB.

La reconstrucción del descriptor usa datos canónicos y publicación atómica; si
se reemplaza un archivo existente se conserva antes un snapshot en
`recovery/<id>/`, junto con un informe seguro sin rutas absolutas, usuario,
traceback, secretos ni contenido GTFS adicional. Las copias candidatas se
inventarían con nombre/fecha/tamaño, se abren y validan por schema, identidad y
consultas mínimas antes de ofrecerse. Una restauración requiere elección y
confirmación explícitas, lock exclusivo P1-19, staging, migraciones existentes,
validación completa y publicación atómica; un fallo antes o durante la
publicación conserva el original y no crea datos ficticios.

La UI ofrece reparar un descriptor inválido y restaurar una copia validada sin
mostrar traceback. No se tocan exports, mapas globales ni otros proyectos. Los
temporales inequívocos de importación se aíslan mediante la infraestructura
legacy existente; un `RUNNING` de operaciones sigue derivándose como
`INTERRUPTED` al presentar historial, sin limpiar el ledger automáticamente.

Evidencia P1-20: `tests/test_p1_20_safe_recovery.py` añade 16 regresiones
file-backed de diagnóstico, descriptor, temporales, aislamiento, staging,
publicación, backup, lock, operaciones residuales y reapertura. La suite completa es `429 passed`;
`tools/check.ps1`, Ruff, mypy y `git diff --check` pasan. No se ha creado una
migración, portable ni NSIS. BLOCKERS: ninguno. IMPORTANTE-PERO-NO-BLOQUEANTE:
no existe reparación física de páginas DuckDB ni read-only productivo.
BACKLOG: retención automática de snapshots y restauración de DB sin identidad
canónica inequívoca.

## P1-19 — Robustez del workspace — DONE

Inventario contractual del workspace real: `project.json` es `DERIVED` (mirror
verificable), `data.duckdb` es `CANONICAL`, `.writer.lock` es metadata
`TRANSIENT`, `temp/` contiene staging/temporales `TRANSIENT`, `cache/` contiene
derivados `DERIVED` y `reports/`/exportaciones pertenecen a `USER_ARTIFACT`
cuando el usuario los genera. Los logs de aplicación viven fuera del proyecto,
en el workspace de aplicación (`logs/`); la biblioteca y descargas de mapas
P1-18 son globales y no se copian dentro del proyecto. No hay backups de usuario
gestionados por el workspace; DuckDB puede crear un backup técnico previo a
migración, fuera del flujo de P1-19.

La apertura canonicaliza internamente el directorio con `Path.resolve()` y
mantiene las rutas visibles del usuario sin persistirlas. La exclusividad usa
un lock real del sistema operativo sobre `.writer.lock` (byte-range lock de
Windows; `flock` en desarrollo Unix) y metadata mínima `lock_version`, `pid` y
`created_at`. El sentinel no es la autoridad y no se decide actividad por PID:
si el OS lock falla el estado es `ACTIVE`; si se adquiere un sentinel válido
residual es `STALE`; si la metadata falta o es inválida es `INVALID` y se puede
reemplazar porque ningún proceso posee el lock. Un segundo escritor recibe un
mensaje de proyecto en uso. La adquisición es race-safe y el cierre es
idempotente; el recurso del SO se libera antes de retirar el sentinel.

La creación conserva la política de carpeta vacía y elimina únicamente los
artefactos creados por una tentativa fallida. `project.json` ya se publica con
temporal del mismo directorio, `flush`/`fsync` y `os.replace`; los temporales
stale no se interpretan como corrupción ni provocan reparación de datos.
`DuckDbUnitOfWork` cierra cada conexión antes de que termine el flujo que libera
el lock. No se han introducido read-only productivo ni cambios de schema en
P1-19; la recuperación segura queda cerrada en P1-20.

Evidencia P1-19: `tests/test_workspace_robustness.py` cubre metadata/privacidad,
release idempotente, sentinel inválido y válido stale, doble escritor real en
subprocess, crash y carrera de adquisición; los tests previos cubren creación,
reapertura, A→B, DuckDB y contaminación UI. La suite completa final es
`413 passed`; el análisis focal de Ruff/mypy y `git diff --check` quedan
registrados al cierre de esta tarea. BLOCKERS: ninguno. IMPORTANTE-PERO-NO-
BLOQUEANTE: no existe read-only productivo y la resolución universal de aliases
de filesystem queda fuera de alcance. BACKLOG: retención automática de
snapshots, fuera de P1-20.

## P1-18 — Gestión de mapas offline — DONE

Se resolvió el bloqueo de release: `PMTiles válido` y `basemap renderizable`
son contratos distintos. La biblioteca clasifica el header PMTiles como vector,
raster o desconocido; un vector sin `MapStyleProfile` queda como dataset válido
con estado `Sin estilo compatible`, pero AUTO y el recomendador lo ignoran.
Raster PNG/JPEG/WebP obtiene un estilo local mínimo. Los bundles vectoriales se
validan y publican atómicamente con style/assets locales hasheados, sin URLs
remotas ni `file://`; OFFLINE conserva cero requests externos. El panel Mapas
offline lista y elimina paquetes con confirmación, desactivando el activo antes
de re-resolver AUTO/OFFLINE.

BACKLOG: catálogo público, BBOX_EXTRACT y perfil Protomaps completo con assets.

Documento de traspaso para continuar el proyecto: `docs/CONTEXTO_Y_LINEA_DE_TRABAJO_GPT.md`.

## Actualización operativa P0 — 2026-08-25

- **P0-001 — DONE con evidencia manual (`P0-001-regression-03`).** Se recuperó `CTM-MiniGTFS-Route-102` legacy sin reimportación; hubo tres ciclos `open → close → open` correctos, desaparecieron `UI-0001` y `UI-0003`, y el DuckDB Mini-GTFS conservó SHA-256 `D4674F72775B05A6E43D6B3B1BD8A732DF051CEE23329AD337DB287296C01182`. `CTM-Mallorca-Regression-02` legacy también se recuperó; el cierre y la reapertura fueron correctos, se preservó `IMPORTED / INVALID / 4` incidencias y el DuckDB Mallorca conservó SHA-256 `B4DE215E398AB316C5CBB52672CD2CFC59CA8A4EA6FD68555EECEC67EBC0E7E6`.
- **P0-002 — DIAG-DEFECT-001 — DONE** con evidencia final validada en `P0-002-regression-05`.
- **P0-003 — Persistencia tras cierre/reapertura — DONE** con evidencia final
  documentada abajo.
- **P0-004 — Cancelación de trabajos — DONE** con evidencia final
  `P0-004-regression-01`, documentada abajo.
- **P0-005 — UI-STATE-001 — DONE**: reset de estado entre proyectos cerrado
  formalmente con `P0-005-regression-01`.
- **P1-01 — UX-PROJECT-001 — DONE**: identidad visible del proyecto cerrada
  formalmente con evidencia automatizada y manual documentada abajo.
- **P1-02 — UX-IMPORT-001/002 — DONE**: importaciones informativas cerradas
  formalmente con el artefacto `P1-02-regression-01`.
- **P1-03 — Estado visible del feed — DONE**: cierre formal con el artefacto
  `P1-03-regression-01`. La página Proyecto separa importación, validación e
  incidencias sin cambiar schema, persistencia, semántica GTFS ni el contexto
  runtime de P1-02.
- **P1-04 — Historial de operaciones — DONE.** Auditoría final:
  `P1-04-AUDITADO-CERRABLE`. P1-04A/A2/A3/A4, P1-04B1, P1-04B2, P1-04B3 y
  P1-04C quedan cerradas como `DONE`. Auditoría Tierra: sin RELEASE BLOCKERS.
  La suite actual de referencia es `320 passed`.
- **P1-13 + P1-14 — UX de exportación — DONE.** Los cuatro formatos actuales
  proponen basenames deterministas, legibles y seguros para Windows mediante
  un helper central; la selección prioriza ruta y añade viaje/servicio cuando
  procede. El destino final normaliza extensiones duplicadas y el modo CSV,
  mantiene la carpeta elegida y conserva la confirmación de sobrescritura.
  La ayuda compacta se actualiza con formato, selección y nombre propuesto sin
  mostrar rutas absolutas ni persistir contexto adicional.

### P0-002 — estado de implementación

La captura central conserva `error_code`, `operation`, `timestamp`,
`exception_type`, `exception_message`, `traceback`, la causa encadenada cuando
existe, versión y estado de aplicación. Cada frame conserva basename, función y
línea; el ejemplo real validado incluye `main_window.py`, línea 332, función
`_choose_project`, y `open_project.py`, línea 115, función `execute`.

La sanitización no expone rutas absolutas, nombre de usuario, project path,
secretos ni datos GTFS. El diálogo del usuario no muestra traceback. El ZIP de
diagnóstico contiene únicamente `gtfs-explorer.log`.

La evidencia final validada incluye suite completa `262 PASS`, tests específicos
de diagnóstico `PASS`, `tools/check.ps1` `PASS`, portable/NSIS/licencias/SBOM y
smokes `PASS`, regresión manual instalada `PASS` y `git diff --check` `PASS`.
La aparente regresión previa fue causada por ejecutar un EXE stale, no por un
fallo de `P0-002-regression-05`. `build_id=''` permanece fuera de alcance y
queda registrado para A032/versionado.

### P0-003 — Persistencia tras cierre/reapertura

P0-003 queda cerrada formalmente como `DONE`. El nuevo test
`tests/test_project_persistence_reopen.py` añade 3 tests y acredita:

- VALID close/reopen: `PASS`;
- INVALID close/reopen: `PASS`;
- reapertura repetida: `PASS`;
- frontera real de proceso mediante un nuevo intérprete Python: `PASS`;
- coherencia `project.json` / DuckDB: `PASS`.

La evidencia global es: tests específicos `3 passed`, batería relevante
`29 passed`, suite completa `265 passed`, `tools/check.ps1: PASS` y
`git diff --check: PASS`. No hubo cambios de producción y no quedan riesgos
restantes dentro de P0-003.

Contrato documentado: DuckDB es la fuente canónica del estado persistente;
`project.json` es un descriptor/espejo verificable; validación, incidencias y
estadísticas se reconstruyen desde DuckDB; pestañas, filtros y selecciones son
estado transitorio de UI y no pertenecen a P0-003. El mismatch legacy
recuperable de `project.json` sigue gobernado por P0-001. No se ha demostrado
pérdida real de persistencia.

### P0-004 — Cancelación de trabajos

P0-004 queda cerrada formalmente como `DONE` con el artefacto
`P0-004-regression-01`.

Contrato implementado y cubierto por tests: la cancelación persiste
`JobState.CANCELLED` y `FeedStatus.CANCELLED` cuando no existe una importación
completa previa; nunca la convierte en `FAILED`. Una reimportación cancelada
conserva como feed visible el último `IMPORTED`. `INVALID` continúa siendo un
feed importado con incidencias y no se transforma en `FAILED`.

La normalización comprueba el `CancelToken` por lotes de 128 filas y por fases;
la validación conserva un run `CANCELLED` sin presentarlo como resultado final.
El adaptador Qt solo emite el resultado después de `QThread.finished` y de
liberar sus referencias a worker/thread, por lo que `PROJECT_READY` no reactiva
acciones antes de terminar el trabajo anterior. La cancelación repetida es
idempotente porque reutiliza `threading.Event`.

La migración existente permite `started_at` y `finished_at` nulos y el
repositorio tampoco los persiste para estados terminales no cancelados; no se
amplía ese contrato en P0-004.

Evidencia final del artefacto: suite completa `268 passed`; `tools/check.ps1`,
Ruff, mypy, `git diff --check`, portable smoke, smoke gráfico, NSIS y
licencias/SBOM: `PASS`.

Evidencia manual:

1. La primera importación cancelada queda `CANCELLED`, con 0 métricas, sin
   validaciones, sin inventario parcial y nunca `FAILED`.
2. `cancel → close → reopen` conserva `CANCELLED` y deja el proyecto utilizable.
3. Tras `cancel → nuevo trabajo`, la nueva importación termina `IMPORTED` con
   1 agencia, 10.000 paradas, 1 ruta, 10.000 viajes y 500.000 eventos.
4. Una reimportación cancelada sobre un feed importado conserva `IMPORTED`,
   métricas, inventario y validación previos; no genera `FAILED` ni sustituye el
   feed bueno por `CANCELLED`.
5. `reimportación cancelada → close → reopen` conserva `IMPORTED`, métricas,
   periodo y una sola ejecución de validación; el proyecto queda listo y
   reutilizable.

### P0-005 — Reset entre proyectos / UI-STATE-001

El reset central `_reset_project_ui_context()` se ejecuta al cerrar o cambiar
de identidad. Coordina los widgets sin manipular sus controles internos:

- RAW elimina archivo, columna, filtro, selección, paginación, modelo y filas.
- Validación elimina severidad, categoría, página, tabla, detalle y selección.
- Exportación elimina formato, rutas, viajes, servicios, búsquedas, destino,
  opciones y executor/callback del proyecto anterior.
- Exploración elimina selectores route/trip/stop/direction/service, timeline,
  matriz, selección y payload/viewport del mapa. El paquete y atribución global
  del mapa no se tocan.
- Navegación vuelve a Proyecto y la pestaña interna a Exploración; `NO_PROJECT`
  deja la navegación deshabilitada y con estado inicial.

La apertura y creación de un nuevo proyecto reutilizan el mismo camino de
cierre antes de presentar el nuevo contexto. No hay operaciones asíncronas
propias de estos widgets que puedan repoblarlos tardíamente; no se ha añadido
un sistema async artificial.

Regresiones de flujo completo añadidas en `tests/test_main_window.py`:

- A → abrir B mediante `_choose_project()`;
- A → nuevo B mediante `_choose_new_project()`;
- A → destino inválido, que confirma el contrato actual `NO_PROJECT` limpio;
- A → cerrar → reabrir A, conservando `project.json`/DuckDB y perdiendo solo UI
  transitoria;
- cierre directo a `NO_PROJECT`, además de las regresiones unitarias existentes
  de RAW, Validación y Exportación.

Las cinco regresiones P0-005 pasan juntas (`5 passed`). En los flujos de cambio
se comprueba identidad de proyecto, filtros, contexto/destino de exportación,
navegación, pestaña, selectores y la supervivencia de una preferencia visual
global. La inspección de los widgets confirma `NO-ASYNC-LATE-CALLBACK-RISK`:
no mantienen `QThread`, `QTimer` ni repoblación asíncrona propia; el adaptador
asíncrono de importación queda fuera de estos caminos.

P0-005 queda cerrada formalmente como `DONE` con el artefacto manual
`P0-005-regression-01`:

`GTFS-Explorer-Portable-0.1.0-P0-005-regression-01-win-x64.zip`

SHA-256: `B1C4747328A57642146F2D5A685B65DBCD9F823BEE040AD651AF92E36ACA4098`.

Evidencia automatizada: tests P0-005 `5 passed`, batería UI `27 passed`, suite
completa `275 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS`,
`git diff --check: PASS` y `NO-ASYNC-LATE-CALLBACK-RISK`. La producción ya
estaba implementada y no tuvo cambios adicionales durante la fase final de
regresión.

Evidencia manual A — A sucio → abrir B: tras configurar deliberadamente RAW,
Validación, Exportación y la pestaña `Datos raw` en A, al abrir B la aplicación
volvió a `Proyecto`, B fue el único contexto activo, RAW mostró datos propios de
B sin el filtro `TEST_P0_005_A`, Validación volvió a `Todas las severidades` y
`Todas las categorías`, Exportación perdió `R1`, `R2`, destino y formato
personalizado, y no hubo mezcla visual. Resultado: `PASS`.

Evidencia manual B — close → reopen same project: tras dejar `Datos raw`
seleccionada en B, `close B → reopen B → Explorar` volvió a `Rutas, viajes y
paradas`; los selectores se reconstruyeron desde B, los datos persistieron y el
estado transitorio de UI no persistió. Resultado: `PASS`.

Contrato final: se resetean filtros RAW, archivo/columna/contexto RAW,
paginación, filtros y selecciones de Validación, contexto de Exportación,
route/trip/service IDs, destino de exportación, selectores y pestaña interna de
Exploración, navegación contextual y estado de mapa ligado al feed. Se
preservan tema, ajustes visuales, configuración global de mapa y paquete de
mapa cuando corresponda. P0-005 no introduce persistencia de filtros ni
preferencias nuevas.

## Cierre documentado: P1-01 — UX-PROJECT-001 — Identidad visible del proyecto

P1-01 queda cerrada formalmente como `DONE`. La identidad global visible se
presenta en la barra de estado y en la página Proyecto, mostrando el nombre
del proyecto y el workspace real; el tooltip conserva la ruta completa. En
`NO_PROJECT` se muestra `Sin proyecto abierto` y `Workspace: —`. El título de
ventana no se modifica.

La implementación no cambia persistencia, `project.json`, DuckDB, IDs ni la
recuperación legacy, y los diagnósticos no incorporan rutas nuevas.

Evidencia automatizada: tests específicos `34 passed`, suite completa
`277 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS` y
`git diff --check: PASS`.

Evidencia manual: `NO_PROJECT`; `open A`; `A → B`; `B → close → NO_PROJECT`;
`close → reopen A`; y apertura de proyecto inválido desde A, todos `PASS`.
En el último flujo se confirmó `UI-0001`, estado final `NO_PROJECT`, ausencia
de identidad residual de A y ausencia de identidad falsa del proyecto
inválido.

Durante la regresión se observó un `.writer.lock` stale asociado a un PID ya
inexistente. No se corrige dentro de P1-01; queda registrado como evidencia
para Robustez de workspace / Recuperación segura en P1 posteriores.

Observación UX menor no bloqueante: en `NO_PROJECT`, la barra inferior puede
mostrar dos veces `Sin proyecto abierto` al coincidir el mensaje operativo con
la identidad global. Queda pendiente para el bloque de observabilidad/UX; no
se modifica código ahora.

## Cierre documentado: P1-02 — UX-IMPORT-001/002 — Importaciones informativas

P1-02 queda cerrada formalmente como `DONE` con el artefacto
`P1-02-regression-01`. El portable validado tiene SHA-256
`7DC96746BC1BC2D04C3684B16F04F1FC93BE890446D9579618FA1D2AE1AAF6EF`.

El contrato final es exclusivamente de observabilidad runtime: nombre del feed
activo, fase traducida, progreso existente, elapsed monotónico, cancelación
visible mientras corresponde y limpieza al terminar. El reloj usa `QTimer` y
un reloj monotónico en memoria; comienza cuando el worker entra en ejecución y
se detiene al liberar el `QThread` con resultado o cancelación. La cancelación
conserva el feed visible hasta la señal terminal, sin cambiar `CANCELLED` a
`FAILED`.

No se modifican `import_jobs`, `project.json`, DuckDB ni migraciones. La
reimportación mantiene separado el feed activo del último feed persistente del
proyecto. No existe persistencia de duración, ETA, cambio de schema, logging
por tick, thread adicional ni historial persistente.

## Cierre documentado: P1-03 — Estado visible del feed

La sección `Estado del feed` de la página Proyecto muestra por separado el
nombre del feed, el estado técnico de importación, el resultado de validación y
el recuento de incidencias. `IMPORTED` se presenta como `Completada`, incluso
cuando la validación es `INVALID`; `CANCELLED` se presenta como `Cancelada` y
`FAILED` como `Fallida`. Una cancelación o un fallo no se presenta como
validación `INVALID`, y los estados sin feed, cancelado o fallido no muestran
métricas como si fueran completas.

La fuente de verdad sigue siendo el resumen reconstruido desde DuckDB mediante
`FeedOverviewQueries`; `project.json` continúa siendo descriptor/espejo. El
feed activo de P1-02 permanece en su contexto runtime separado del feed
persistente mostrado por P1-03. No se introdujeron estados, tablas ni
migraciones nuevas.

P1-03 queda cerrada formalmente como `DONE` con el artefacto
`P1-03-regression-01`. El portable validado tiene SHA-256
`43571FAB01F0091480196F403C30122107959AADE2CCAE5D052A836BAB81949F`.

Evidencia automatizada: tests focales `38 passed`, suite completa `282 passed`,
`tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS` y `git diff --check: PASS`.

Evidencia manual:

- A — Sin feed: `Feed: —`, `Importación: Sin feed importado`,
  `Validación: Sin ejecutar`, `Incidencias: —` y sin métricas falsas (`PASS`).
- B — `IMPORTED + VALID`: `valid_full.zip`, importación `Completada`,
  validación `VALID` e incidencias `1` (`PASS`).
- C — `IMPORTED + INVALID`: `invalid_core.zip`, importación `Completada`,
  validación `INVALID` e incidencias `4`; `INVALID` no se presenta como fallo
  técnico (`PASS`).
- D — Primera importación cancelada: `P0-004-manual-feed-medium.zip`,
  importación `Cancelada`, validación `Sin ejecutar`, incidencias `No
  disponible`, sin métricas completas y no `FAILED` (`PASS`).
- E — Fallo técnico: `failed-feed.zip`, importación `Fallida`, validación e
  incidencias `No disponible`, sin métricas completas, no `INVALID` y no
  `CANCELLED` (`PASS`). Durante la prueba se volvió a observar un `writer.lock`
  stale tras cerrar forzosamente una instancia antigua y se restauró el ACL
  temporal; queda registrado para Robustez de workspace / Recuperación segura,
  fuera de P1-03.
- F — Reimportación cancelada: partiendo de `invalid_core.zip` con
  `IMPORTED / INVALID / 4`, la cancelación conservó feed, importación,
  validación, incidencias, métricas e inventario previos, sin degradar a
  `Cancelada` ni `Fallida` (`PASS`).

Contrato final: la UI distingue explícitamente el estado técnico de
importación del resultado de validación. Quedan semánticamente diferenciados
`IMPORTED + VALID`, `IMPORTED + INVALID`, `CANCELLED`, `FAILED` y sin feed.
P1-02 sigue siendo el contexto runtime de la operación activa y P1-03
representa el estado estable/persistente del feed.

Observación UX no bloqueante: `Métricas no disponibles: la importación no
terminó correctamente` es funcionalmente correcto, aunque una tarea UX futura
podría usar un texto más específico para cancelación voluntaria.

## P1-04A4 — Corrección del índice incompatible con DuckDB 1.1.3

P1-04A4 queda cerrada con schema 9 corregido. La integración productiva de
IMPORT, VALIDACIÓN y EXPORT, junto con el cierre P1-04C, queda registrada como
parte de P1-04 `DONE` en la auditoría final.

La reproducción exacta en DuckDB 1.1.3 confirmó que las tres FKs físicas desde
`operation_import_details.operation_id`,
`operation_validation_details.operation_id` y
`operation_export_details.operation_id` hacia `operations.operation_id`
bloqueaban la transición canónica `RUNNING → terminal`. Esas FKs se retiran de
009, manteniendo las columnas `operation_id VARCHAR PRIMARY KEY`; el repositorio
valida dentro de la misma UoW que la operación existe y corresponde al tipo de
detail esperado.

Las otras seis FKs añadidas por 009 permiten sus mutaciones reales y se
conservan: `operations.project_id → projects.project_id`; los tres `feed_id →
feeds.feed_id`; `operation_import_details.job_id → import_jobs.job_id`; y
`operation_validation_details.validation_batch_id → validation_runs.batch_id`.
También se conservan `UNIQUE job_id` y `UNIQUE validation_batch_id`; los tests
fijan el modelo físico final y rechazan referencias inexistentes.

009 seguía siendo una migración de desarrollo sin seguimiento: no existe RC,
portable o instalador P1-04, ni una base schema 9 durable del repositorio fuera
de temporales de tests. Por ello se corrige 009 directamente, sin backfill y sin
crear una migración 010.

DuckDB 1.1.3 también rechaza la actualización de `operations` de `RUNNING` a
terminal si hay un índice secundario que incluye `started_at`, aunque conserva
la PK `operation_id`. Se elimina por ello
`idx_operations_project_started_at`; no se añade un índice solo por
`project_id`, porque el historial esperado por workspace es de cientos o miles
de operaciones y la consulta paginada por proyecto con ordenación y `LIMIT` no
justifica un índice secundario en esta fase. La suite cubre las transiciones
file-backed con reapertura para `COMPLETED`, `CANCELLED` y `FAILED`, verifica la
supervivencia del detail y consulta `duckdb_indexes()` para impedir que se
reintroduzca un índice de `operations` con `started_at`.

Evidencia automatizada P1-04A4: historial, migraciones y repositorios/UoW
`33 passed`; suite completa `305 passed`; `tools/check.ps1` `PASS`; Ruff
`PASS`; mypy `PASS`; `git diff --check` `PASS`.

## P1-04B1 — Integración atómica de IMPORT

P1-04B1 queda cerrada como `DONE`. `ImportFeed._save()` registra la operación
de importación usando la misma `DuckDbUnitOfWork` que guarda proyecto, feed y
job; no abre una UoW secundaria. La alta inicial crea atómicamente
`operations` y `operation_import_details`. Los checkpoints intermedios solo
actualizan el job y no duplican la operación. El cierre terminal actualiza en
la misma UoW feed, job y operación: `READY` e `INVALID` son
`OperationStatus.COMPLETED`, `CANCELLED` conserva `CANCELLED` y el fallo
técnico conserva `FAILED`. Los códigos de error se normalizan a mayúsculas
únicamente para el ledger; el job conserva su código histórico.

`INVALID` sigue siendo un feed importado con resultado de validación inválido,
no un fallo técnico. La reimportación cancelada y la recuperación P0-004 se
conservan; no se han modificado validación, exportación ni UI.

Evidencia B1: focales de importación e historial `32 passed`; suite aislada de
`tools/check.ps1` `305 passed`; Ruff formato/lint `PASS`; mypy `PASS`; y
`git diff --check` `PASS`. El primer lanzamiento directo de la suite obtuvo
`304 passed` y un fallo intermitente ajeno a B1 en el spike WebEngine del mapa
(`map_loaded=False`); su repetición aislada obtuvo `4 passed` y el control
canónico posterior quedó completamente verde. Incidencia `NON-BLOCKER`, queda
para backlog del spike de mapa.

P1-04B2 queda cerrada y P1-04B3 es la siguiente integración documentada.

## P1-04B2 — Integración de VALIDACIÓN

P1-04B2 queda cerrada como `DONE` sin migración 010. La validación automática
de `ImportFeed` no crea una operación `VALIDATION` adicional: el historial
mantiene una única operación `IMPORT`. La relación se reconstruye de forma
determinista mediante `operation_import_details.job_id` y el convenio actual
`validation_runs.batch_id = job_id || ':structure'`, comprobando también el
`feed_id`.

## P1-04B3 — Integración de EXPORT

P1-04B3 queda cerrada como `DONE` sin migración 010 y sin cambios de UI. Las
exportaciones reales de feed JSON, GeoJSON, CSV y Mini-GTFS pasan por
`FeedExportLifecycle`: cada ejecución crea una única operación `EXPORT/RUNNING`
con detalle inicial (`feed_id`, formato y artefactos nulos) y confirma ese
inicio antes de tocar el filesystem.

Tras la publicación atómica del artefacto y su manifiesto, el cierre persiste
basename, SHA-256 en minúsculas y tamaño, y marca `COMPLETED`. Los errores de
preparación se registran como `EXPORT_PREPARE_FAILED`; los errores de escritura
como `EXPORT_WRITE_FAILED`, sin mensajes, tracebacks, rutas ni contenido en el
ledger. Si falla DuckDB después de publicar, el artefacto no se elimina y la
operación permanece `RUNNING`; al reabrir se deriva `INTERRUPTED` sin mutar la
base de datos. No se generan `EXPORT/CANCELLED`, porque la exportación actual
no dispone de una cancelación de usuario realmente iniciable durante la
ejecución síncrona.

`_export_validation_report()` queda fuera: es un informe auxiliar independiente
y no una exportación de feed. La consulta del historial continúa siendo solo
DuckDB y no inspecciona el filesystem. La regresión de integración conserva
los cuatro artefactos, manifiestos, hashes y comportamiento de overwrite
anteriores; IMPORT y VALIDATION no cambian.

Evidencia automatizada B3: `25 passed` en MainWindow y `23 passed` en historial
previo; focales combinados de exportación, operaciones y writers `47 passed`;
suite completa `310 passed`; `tools/check.ps1` `PASS`; Ruff `PASS`; mypy
`PASS`; `git diff --check` `PASS`. No se construyó portable ni NSIS.

`DuckDbOperationRepository.list_operations()` proyecta desde `validation_runs`
el `validation_batch_id`, el estado terminal `VALID`, `INVALID` o `CANCELLED`
y `total_issue_count`. No consulta `validation_issues`, no duplica contadores
en `operations` y no presenta `VALID`/`INVALID` para un run inexistente o
incompleto (`RUNNING`) tras un `FAILED`. La consulta sigue limitada al ledger,
sus detalles y la tabla pequeña de corridas de validación.

No existe actualmente una acción productiva standalone para validar un feed
fuera de IMPORT; no se ha añadido botón ni funcionalidad nueva. `VALID` e
`INVALID` conservan `OperationStatus.COMPLETED`; una cancelación antes de
validar queda `CANCELLED` sin corrida ni resultado; una cancelación durante la
validación conserva el run `CANCELLED`; y un fallo técnico queda `FAILED` sin
resultado de validación ficticio. La relación y sus agregados se reconstruyen
tras cerrar y reabrir el proyecto.

Evidencia B2: focales P1-04/import/validation `63 passed`; `tools/check.ps1`
`307 passed`; Ruff `PASS`; mypy `PASS`; `git diff --check` `PASS`. La suite
directa obtuvo `306 passed` y un fallo no bloqueante ya conocido en
`test_map_loopback_spike.py` (`map_loaded=False`); el control canónico quedó
completamente verde.

Tests añadidos en `tests/test_operations_history.py` y
`tests/test_import_feed.py`: import VALID/INVALID con una sola operación,
relación derivada, agregados de `validation_runs`, cancelación antes y durante
validación, fallo sin resultado ficticio, reapertura y ausencia de operación
`VALIDATION` adicional.

La verificación standalone de VALIDATION queda fuera del alcance actual y se
registra como backlog independiente de P1-04.

## P1-04 — Cierre documental final

Auditoría final: `P1-04-AUDITADO-CERRABLE`.

- P1-04A/A2/A3/A4 = `DONE`.
- P1-04B1 = `DONE`.
- P1-04B2 = `DONE`.
- P1-04B3 = `DONE`.
- P1-04C = `DONE`.
- Auditoría Tierra: sin RELEASE BLOCKERS.
- Suite actual de referencia: `320 passed`.

Backlog independiente, no pendiente de P1-04:

- Verificación portable/NSIS.
- EXPORT/CANCELLED cuando exista exportación async.
- VALIDATION standalone si se incorpora flujo manual.
- Revisión de documentación residual.

## Estado

T015_COMPLETED — T016_COMPLETED — T017_COMPLETED — T018_COMPLETED — T020_COMPLETED — T021_COMPLETED — T022_COMPLETED — T023_COMPLETED — T024_COMPLETED — T030_COMPLETED — T031_COMPLETED — T032_COMPLETED — T033_COMPLETED — T034_COMPLETED — T035_COMPLETED — T040_COMPLETED — T041_COMPLETED — T042_COMPLETED — T043_COMPLETED — T044_COMPLETED — T045_COMPLETED — T046_COMPLETED — T050_COMPLETED — T051_COMPLETED — T052_COMPLETED — T053_COMPLETED — T054_COMPLETED — T057_COMPLETED — T060_COMPLETED — T061_COMPLETED — T062_COMPLETED — T063_COMPLETED — T064_COMPLETED — T073_COMPLETED — T074_COMPLETED — T075_COMPLETED — T076_COMPLETED — T080_COMPLETED — T081_COMPLETED — T090_COMPLETED — T091_COMPLETED — T092_COMPLETED — T093_COMPLETED — T094_COMPLETED — T095_COMPLETED — T096_COMPLETED

## Objetivo actual

Construir GTFS Explorer Desktop como aplicación Windows x64, portable y offline-first para importar, explorar, validar, visualizar y exportar GTFS Schedule sin exigir herramientas de desarrollo al usuario final.

## Actualización posterior a 0.1.0-rc1

- A000 está completada: el trabajo local previo está inventariado en
  `docs/INVENTARIO_ACTUALIZACION_A000.md` sin modificarlo ni eliminarlo.
- A001 está completada: DEC-017 fija `0.1.0-rc2` como candidata local y limita
  su alcance a cambios no contractuales que superen sus tareas y pruebas.
- A010 está completada: `gtfs_explorer.product.IDENTITY` centraliza nombre,
  edición, autor, copyright y aviso de derechos. La aplicación, la ayuda, los
  metadatos de exportación y los scripts de empaquetado lo reutilizan; las
  pruebas de metadatos, i18n, superficies Qt e instalador han pasado.
- El comportamiento de presentación inicial y la experiencia completa del
  instalador siguen diferidos a A011 y A013, respectivamente.
- `examples/ctm-mallorca-es.zip` queda fuera del alcance de la actualización y
  de los artefactos; no se auditará ni se incorporará mediante una tarea.
- A030 está completada en `docs/A030_AUDITORIA_VERSIONES_2026-08-23.md` sin
  modificar dependencias; PySide6/Qt WebEngine, DuckDB, Shapely, Nuitka,
  MapLibre y el cotejo GTFS quedan como pruebas acotadas de A031.
- La línea de trabajo consolidada para otro GPT, con el orden de lectura y la
  siguiente tarea, está en `docs/CONTEXTO_Y_LINEA_DE_TRABAJO_GPT.md`.
- Se ha corregido el registro GTFS 2026-04-27 para que `pickup_type` y
  `drop_off_type` acepten declarativamente `0`; las prohibiciones condicionadas
  por ventanas continúan en `timetable.py` y cuentan con cobertura de la ruta
  genérica `ValidationRuleRegistry` → `FieldValidationRule`.

## Hechos comprobados

- El repositorio contiene una aplicación ejecutable avanzada, sus tests de capas/entrypoint y la documentación de definición, actualización y empaquetado.
- El `GTFS_COMPLETO_DEMO_ASTURIAS.zip` citado en el chat no está presente en este repositorio.
- Se ha creado `docs/PLAN_MAESTRO_CONSTRUCCION.md` con arquitectura, contratos, costes, riesgos, roadmap y tareas secuenciales.
- T000, línea base documental, está completada.
- Existe un orquestador local para ejecutar una sola tarea `READY` por sesión de Codex, exigir evidencia estructurada y detenerse ante bloqueos.
- El orquestador recupera locks y estados huérfanos de forma explícita, registra PID/heartbeat, aplica timeout configurable, conserva logs incrementales y reejecuta el flujo canónico antes de aceptar `DONE`.
- Cada sesión del orquestador usa el ejecutor registrado en `docs/TASK_STATUS.json`; el piloto actual está fijado en `gpt-5.6-terra` con razonamiento `medium`.
- T001 está completada: stack x64 fijado en `pyproject.toml`/`uv.lock` y smoke técnico ejecutado correctamente en Windows 11 x64.
- T002 está completada: esqueleto por capas, CLI mínima y pruebas de límites de dependencia disponibles.
- T003 está completada: formato, lint, tipos y tests se ejecutan con `tools/check.ps1`.
- T004 está completada: fixtures GTFS ficticios, deterministas y verificables disponibles para las pruebas.
- T005 está completada: rutas instalada/portable explícitas y settings relativos validados.
- T010 está completada: contrato de fuentes y manifiestos deterministas sin rutas locales serializadas.
- T011 está completada: ZIPs inventariados y extraídos de forma confinada con cuotas y errores tipados.
- T012 está completada: directorios y CSV parciales se inventarían sin modificar la fuente y con raíz estricta.
- T013 está completada: el lector tabular conserva texto y filas, aplica UTF-8/UTF-8 con BOM en GTFS estricto, exige confirmación del formato compatible y comunica los rechazos con su fila física.
- T020 está completada: cada proyecto dispone de DuckDB con migraciones transaccionales, backup previo, límites configurables, temporal controlado y conexiones cerrables con afinidad de thread.
- T021 está completada: los puertos de unidad de trabajo, proyecto, feed y paginación aíslan la aplicación de SQL; DuckDB los implementa y traduce sus errores a dominio.
- T022 está completada: DuckDB persiste metadatos de proyecto, feed y job; `project.json` es un descriptor verificable, se regenera si falta y rechaza divergencias o referencias no relativas.
- T023 está completada: la apertura del proyecto coordina escritura local exclusiva y una caché local descartable, versionada y atómica; borrar la caché no elimina los datos importados.
- T024 está completada: al abrir se detectan jobs interrumpidos, se marca el proyecto para recuperación y los temporales de importación se ponen en cuarentena; su borrado exige confirmación y solo acepta rutas verificadas dentro del workspace.
- T015 está completada: staging DuckDB por lotes conserva texto, fila y archivo fuente, columnas extra e inventario de desconocidos; la carga completa revierte ante error o cancelación.

## Alcance de v1.0

- GTFS Schedule; GTFS Realtime queda para una fase posterior.
- Importación segura de ZIP/carpeta y modo compatible explícito para CSV parcial.
- DuckDB, validación interna, consultas, JSON, GeoJSON, CSV y Mini-GTFS dentro de la matriz de cobertura.
- UI PySide6, mapas MapLibre con overlay GTFS local, PMTiles opcional y proveedor
  online interactivo allowlisted.
- Portable, instalador, manual, licencias y pruebas en Windows limpio.

## Trabajo en curso

- T014 está completada: el registro versionado de GTFS Schedule 2026-04-27 codifica 32 archivos y 226 campos, con IDs de regla, fuentes, tipos, enums, referencias y requisitos condicionales validados.
- T015 está completada: la carga staging DuckDB es fiel, transaccional y por lotes; no materializa el feed completo en memoria Python.
- T030 está completada: el contrato independiente de UI resuelve servicios por fecha, aplica add/remove de `calendar_dates.txt` sobre `calendar.txt`, admite feeds solo con excepciones y expone el periodo global declarado sin usar zona horaria.
- T016 está completada: la normalización core persiste tablas tipadas y lexemas fuente, conserva horas como segundos de servicio, registra conversiones o valores obligatorios inválidos y revierte de forma transaccional.
- T017 está completada: shapes, frequencies, transfers, feed_info y attributions se normalizan a tablas tipadas y trazables; las transferencias no infieren reglas avanzadas.
- T018 está completada: el comando invocable sin UI orquesta preflight, staging, normalización y validación; persiste fase/progreso, admite cancelación cooperativa, no marca READY ante problemas y limpia extracciones ZIP temporales.
- T024 está completada: la reapertura tras un crash deja el proyecto en `RECOVERY_REQUIRED`, permite identificar los jobs a reintentar y conserva los temporales en cuarentena hasta una limpieza confirmada.
- T030 está completada: la consulta DuckDB de calendario usa la fecha GTFS, no la zona horaria, y devuelve los servicios activos y sus límites globales.
- T031 está completada: las consultas DuckDB encadenan ruta, servicio, `direction_id` y viaje sin inferir ida/vuelta; el timeline paginado conserva IDs y tiempos de servicio, incluidos valores superiores a 24:00:00.
- T032 está completada: el inspector reconstruye el contexto de una parada o estación con un número fijo de consultas DuckDB, devuelve rutas, servicios y eventos programados paginados, e incorpora la fecha GTFS opcional sin presentar el horario como tiempo real.
- T033 está completada: la matriz de horarios agrupa solo viajes con el mismo patrón de paradas, conserva loops, horas ausentes y valores superiores a 24:00:00; limita las columnas de la vista e informa el alcance para exportación completa sin materializar todos los viajes.
- T034 está completada: la consulta de trip/shape ordena puntos, construye longitud geodésica, bbox consciente del antimeridiano y distancia parada-shape mediante proyección azimutal equidistante local; las unidades y los métodos constan en el DTO y los datos geométricos inválidos se devuelven como incidencias sin interrumpir la consulta.
- T035 está completada: el inspector raw consulta staging con columnas validadas contra el manifiesto, filtros estructurados contains/igualdad/rangos tipados, ordenación segura y token de página opaco; la UI no recibe SQL ni conoce DuckDB y cada respuesta queda limitada a 500 filas.
- T040 está completada: el framework registra códigos únicos, ejecuta reglas de forma determinista y cancelable, aísla fallos de cada regla y persiste lotes, problemas localizables y recuentos deduplicados sin puntuación numérica.
- T041 está completada: valida el contenedor, los archivos obligatorios y las cabeceras contra el registro versionado; conserva extensiones como avisos y distingue explícitamente el CSV compatible del GTFS oficial.
- T042 está completada: valida en staging valores obligatorios, tipos, rangos, enums declarados y referencias GTFS por conjuntos, conservando archivo, fila física y campo de origen en cada incidencia.
- T043 está completada: valida horarios de servicio sin convertirlos a fechas civiles, detecta secuencias duplicadas y retrocesos temporales reales, aplica requisitos condicionales de stop_times y comprueba rangos de frequencies.
- T044 está completada: valida shapes degenerados y secuencias duplicadas; las distancias parada-shape se calculan únicamente en el contexto inequívoco del viaje, con método, unidad y umbral configurables visibles en cada aviso.
- T045 está completada: recomendaciones locales trazables para paradas sin uso y viajes sin shape se mantienen separadas de la validez formal; los informes JSON/HTML atómicos permiten filtros, resumen por severidad y escapan todo contenido HTML.
- T050 está completada: el escritor de salida publica artefactos y manifiestos laterales con hash SHA-256 de forma atómica, cancelable y con sobrescritura explícita; los destinos bajo raíces internas protegidas se rechazan.
- T051 está completada: `gtfs-explorer.bundle` 1.0.0 tiene JSON Schema draft 2020-12, ejemplos mínimo y completo, y pruebas de contrato semántico; los cambios incompatibles requieren 2.0.0.
- T052 está completada: el exportador JSON publica bundles 1.0.0 atómicos y deterministas por rutas, con restricción opcional de viajes/servicios, cierre de dependencias, opcionales en metadata, avisos de omisión, streaming por lotes y cancelación.
- T053 está completada: el exportador GeoJSON publica paradas y shapes originales seleccionados como RFC 7946, con coordenadas longitud/latitud finitas, procedencia por feature, bbox opcional, cancelación y salida atómica.
- T054 está completada: el exportador CSV publica datos UTF-8 con coma y quoting determinista en streaming; el modo fiel conserva los lexemas y el modo seguro para hoja de cálculo neutraliza fórmulas de forma explícita, con nombre y manifiesto que identifican el modo.
- T055 está completada: el motor Mini-GTFS core calcula y documenta el cierre transitivo de rutas, viajes, paradas y ancestros, servicios, calendarios y agencias; rechaza antes de escribir una salida cualquier selección vacía, ambigua o con referencias core rotas.
- T056 está completada: la matriz de cierre Mini-GTFS publica una política explícita para los 32 archivos GTFS conocidos; filtra shapes y relaciones opcionales ya soportadas, incluye la metadata global y excluye de forma declarada los opcionales complejos hasta su tarea específica.
- T057 está completada: el escritor Mini-GTFS genera ZIPs de raíz deterministas desde tablas ya cerradas, conserva `feed_info.txt` y `attributions.txt`, reimporta y valida internamente antes de publicar el ZIP y su manifiesto; MobilityData queda registrado como no disponible cuando no hay sidecar local.
- T046 está completada: el adaptador opcional de MobilityData requiere Java y JAR sidecar locales con versión fijada, ejecuta la CLI sin shell, maneja timeout/cancelación y conserva `report.json`, `report.html` y `system_errors.json` separados del informe interno.
- T060 está completada: el shell Qt tiene navegación y ajustes visuales de base; una única máquina de estados habilita las acciones y el cierre durante un trabajo solicita cancelación cooperativa antes de permitir cerrar la ventana.
- T061 está completada: la UI abre proyectos existentes, admite ZIP/CSV/carpeta mediante diálogo o arrastre, confirma la importación, muestra progreso por fases y ejecuta el orquestador en un worker Qt con cancelación cooperativa y errores visibles. El comando y sus conexiones DuckDB se crean en el worker.
- T062 está completada: el resumen consulta DuckDB para mostrar métricas normalizadas, periodo de servicio GTFS, inventario de archivos y estado de validación. Un archivo no cargado se indica como tal y no se confunde con uno cargado sin filas; el acceso a incidencias navega a Validación.
- T063 está completada: el inspector raw usa un modelo Qt paginado reutilizable, filtros y ordenación estructurados, recupera tokens inválidos, copia la selección y exporta la vista cargada como CSV fiel sin exponer SQL a la UI.
- T064 está completada: el explorador Qt sincroniza ruta, servicio, `direction_id` y viaje, reinicia los filtros descendientes de forma determinista, presenta timeline e inspector de parada con nombre+ID y muestra una matriz de horarios por patrón. Los valores superiores a 24:00:00 se muestran literalmente y `direction_id` nunca se etiqueta como ida/vuelta.
- T065 está completada: la vista de validación filtra y pagina incidencias, muestra origen de regla y separa visualmente MobilityData; permite abrir el origen raw, identifica la ayuda local y exporta el informe HTML o JSON con los filtros activos, sin autocorrección ni puntuación.
- T066 está completada: el asistente de exportación conecta JSON, GeoJSON, CSV y Mini-GTFS con el proyecto abierto; previsualiza el alcance, confirma el artefacto final antes de sobrescribirlo, comunica hash y avisos, y conserva los shapes referenciados para que la revalidación interna Mini-GTFS sea correcta.
- T070 está completada con decisión GO revisada: MapLibre 6.3.0 y PMTiles 4.5.0 funcionan mediante un servidor HTTP efímero limitado a `127.0.0.1`, con token/puerto aleatorios, allowlist, CSP y monitor sin tráfico exterior. El spike y el standalone demuestran `206`, render de ruta/parada y QWebChannel bidireccional.
- T071 está completada: MapLibre/PMTiles se compilan desde el lock npm a recursos Qt estáticos, con hashes SHA-256 estables, licencia de MapLibre copiada y escaneo que rechaza URLs remotas nuevas. Node/npm quedan solo en el flujo de desarrollo y CI offline documentado.
- T072 está completada: el bridge del mapa usa DTOs JSON v1 con límite de 16 KiB, cola FIFO de 32 navegaciones hasta `mapReady`, secuencia estricta de eventos y errores tipados sin crash. La API pública solo intercambia eventos y comandos de cámara; no expone filesystem ni SQL.
- T073 está completada: el explorador muestra en MapLibre local, sin basemap, el shape GeoJSON y las paradas del viaje seleccionado; sanea colores GTFS, omite la línea si falta o es insuficiente, ajusta la extensión y sincroniza clicks de parada. Los popups usan texto DOM, sin interpretar contenido del feed como HTML.
- T074 está completada: el selector de Ajustes valida paquetes PMTiles v3 locales (manifiesto, hashes, bbox, zooms, licencia, atribución y estilo sin URL remota), los sirve por loopback con token, CORS restringido a la página local y rangos HTTP, mantiene la atribución visible y conserva el fondo neutro ante rechazo o ausencia de paquete. Al cambiar el estilo se reinstalan las fuentes y capas GTFS y se reaplica el último payload para conservar rutas y paradas sobre el mapa base.
- T075 está completada: el mapa limita cada actualización visual a 2.000 paradas y 4.000 puntos de shape, filtra por viewport, agrupa paradas, conserva la selección durante pan/zoom, descarta actualizaciones antiguas y cachea hasta 32 viewports. La medición reproducible local se publica en `docs/PERFORMANCE.md`.
- T076 está completada: `tools/build_map_package.py` extrae y verifica PMTiles regionales con un CLI local, exige licencia, atribución y referencia de fuente, bloquea URLs remotas sin confirmación explícita y no serializa rutas locales. El paquete resultante contiene estilo/assets locales y hashes; `docs/MAPS_OFFLINE.md` documenta la revisión humana de licencia y el proceso reproducible.
- T080 está completada: manual integrado offline versionado y buscable, con ayuda contextual para las reglas de validación y contenidos sobre importación, conceptos GTFS, horas superiores a 24:00, exportación y mapas. El contenido se presenta escapado y no exige enlaces de red.
- T081 está completada: catálogo de interfaz español empaquetado con comprobación de claves y pseudo-localización; acciones principales con atajos, orden de foco explícito y nombres o descripciones accesibles en navegación, filtros, tablas y exportación. El checklist manual de contraste y lector de pantalla está en `docs/ACCESSIBILITY_CHECKLIST.md`.
- T090 está completada: el diagnóstico local usa logs rotatorios con contexto permitido y redacción de secretos, conserva el stack solo en modo debug y permite previsualizar y exportar bajo consentimiento únicamente esos logs en un ZIP local.
- T091 está completada: `tools/build_portable.py` usa `pyside6-deploy`/Nuitka para publicar el ZIP Windows x64 standalone, con ejecutable, `portable.flag`, recursos locales de ayuda y mapa, manifiesto interno y SHA-256 lateral. El build ejecuta el propio EXE y exige que WebEngine active el bridge y dibuje al menos 20 píxeles azules de una ruta sintética; la matriz en VM limpia corresponde a T094.
- T092 está completada: el instalador NSIS 3.12 por usuario se construye desde el ZIP portable verificado, instala sin elevación en `%LOCALAPPDATA%\Programs\GTFS Explorer`, mantiene el workspace fuera del directorio de programa y publica setup, manifiesto y SHA-256 coincidentes. El smoke local verificó instalación, reinstalación y desinstalación en una ruta Unicode; la matriz completa en VM limpia y el upgrade real desde N-1 corresponden a T094.
- T093 está completada: el portable y el instalador se generan con `LICENSES/`, `THIRD_PARTY_NOTICES.html` y `SBOM.cdx.json` CycloneDX 1.5. `tools/check_licenses.py` compara el contenido del portable con un catálogo cerrado y falla si aparece un binario no inventariado. Java/MobilityData y datos de mapa no se distribuyen por defecto; la revisión jurídica de LGPL/Qt WebEngine queda pendiente antes de venta o publicación.
- T094 está completada: el responsable confirmó la matriz manual con los artefactos fijados. Portable e instalador funcionan offline y quedaron validados importación, validación, consultas, mapa PMTiles con rutas y paradas, exportaciones JSON/CSV, ayuda local, rutas con caracteres especiales y persistencia del workspace tras desinstalar. I03 se omite justificadamente en 0.1.0 porque no existe una versión instalable N-1; deberá ejecutarse en la siguiente versión. No quedan bloqueadores de severidad alta.
- T095 está completada: `tools/benchmark_feed.py` genera perfiles sintéticos deterministas pequeño, medio y RNF-006 y mide importación/validación, consulta, exportación, mapa, RAM, disco y cancelación. Solo el perfil pequeño se ha ejecutado y publicado; RNF-006 sigue sin acreditar y no se presenta como límite soportado.
- **P1-21 — rendimiento formal reproducible — DONE.** `src/gtfs_explorer/performance.py` y `tools/benchmark.py` generan y miden feeds SMALL/MEDIUM/LARGE/XL con fases, timeout aislado, conteos, privacidad, almacenamiento y throughput. La baseline formal acredita SMALL y MEDIUM; MEDIUM `import` termina `READY` en 459,612 s y LARGE se clasifica como `TIMEOUT` de staging a 300 s. El cuello es lineal en inserciones DuckDB 1.1.3, sin defecto funcional ni N² observado; el hallazgo de coste pesado queda registrado y separado en P1-22. Las exportaciones SMALL (CSV, JSON, GeoJSON y Mini-GTFS con reimportación) pasan. El detalle reproducible está en `docs/PERFORMANCE.md`.
- T096 está completada: la RC local `0.1.0-rc1` reúne changelog, checklist, manifiesto de release, SBOM, avisos y hashes verificados de portable e instalador. No se ha publicado ni distribuido; la autorización expresa y la revisión jurídica LGPL siguen pendientes.
- **P1-06 — RAW — Origen exacto de fila — DONE.** El lector y staging
  conservan `source_row` como la primera línea física del registro CSV,
  empezando en 1. Las líneas vacías consumidas, BOM, LF/CRLF y comas dentro de
  campos quoted no alteran ni pierden la numeración; un registro quoted
  multilínea queda asociado a su línea física inicial. RAW lo presenta como la
  columna metadata `Fila fuente`, estable frente a filtros, ordenación y
  paginación, y no la incluye en la exportación CSV fiel. No se ha creado
  migración: se reutiliza la columna `source_row` ya existente en staging.
- **P1-07 — Selectores buscables — DONE.** Los selectores de rutas, servicios,
  sentidos y viajes son combos editables con `QCompleter` incremental,
  coincidencia `contains` sin distinguir mayúsculas y preservación del objeto
  real seleccionado mediante `currentData()`. El cambio de una selección
  reinicia sus dependientes; `clear()` limpia texto, modelos y selección al
  cambiar feed/proyecto o cerrar. La cobertura focal incluye teclado, listas
  vacías, un elemento y 10.000 opciones. Suite completa: `332 passed`.
- **P1-08 — Presentación profesional de validación — DONE.** La vista usa una
  tabla compacta paginada de 100 incidencias, con scroll, selección y
  ordenación estable. Presenta `FATAL`, `ERROR`, `WARNING` y `NOTICE`, además
  de categoría y origen; conserva el `rule_code` real, `file_name`, `field_name`,
  la fila física `row_number` como `Fila fuente`, entidad y mensaje existente.
  Una incidencia sin ubicación muestra `Alcance global` y `Sin fila física`,
  nunca el índice visual de la tabla. El detalle seleccionado expone solo el
  contexto disponible en el DTO, en texto plano y con redacción de rutas
  locales, traceback y claves privadas.
- P1-08 añade filtro exacto por archivo, búsqueda textual sin distinguir
  mayúsculas sobre regla/mensaje/campo/archivo y mantiene el filtro de
  severidad/categoría existente. La consulta se acota al feed persistente
  actual para no mezclar reimportaciones históricas; el resumen reutiliza
  `validation_runs`/`FeedOverview` y no afirma ausencia de incidencias cuando
  existen avisos `NOTICE`. El reset P0-005, cambio de proyecto, cierre,
  reapertura y finalización de importación refrescan el contexto correcto.
  La preparación para RAW conserva el callback existente de archivo/campo/
  entidad; no se implementó navegación nueva.
- Evidencia P1-08: `8 passed` de validación focal, `96 passed` en la batería
  focal de validación, P1-06, P1-03, P1-04 y persistencia; suite completa
  `337 passed`; `tools/check.ps1: PASS`; Ruff, mypy y `git diff --check`:
  `PASS`. El caso sintético grande verifica que la UI materializa solo la
  página recibida, no 100.000 widgets. No se construyó portable/NSIS.
- BACKLOG P1-08: navegación RAW ampliada, fuzzy/búsqueda avanzada,
  agrupaciones y pulido visual menor; la comprobación manual de GUI empaquetada
  no forma parte de esta sesión.
- **P1-09 — Compatibilidad y semántica GTFS real — DONE.** La exploración de
  horarios usa directamente los lexemas `arrival_time` y `departure_time` de
  `gtfs_stop_times`; los segundos de servicio solo se derivan para ordenación y
  validación. Se conservan los viajes antes de medianoche, las horas
  `>=24:00:00`, la diferencia entre llegada y salida de la primera parada y la
  ausencia permitida de `departure_time`, sin inferir una publicación oficial ni
  un tiempo real. La matriz identifica ambos campos por su nombre GTFS y el
  Mini-GTFS se comunica como salida GTFS Schedule validada localmente, no como
  certificación del proveedor.
- **P1-10 — Líneas físicas completamente vacías — DONE.** El lector consume
  todas las líneas físicas y mantiene `source_row`, pero staging ignora solo la
  fila CSV completamente vacía (`row.values == ()`) como fila lógica: no crea un
  registro ficticio, no altera los recuentos válidos y no genera `WARNING`,
  `NOTICE`, `ERROR` o `FATAL`. Una fila explícita como `,,` sigue siendo una fila
  lógica y conserva la validación existente de campos obligatorios. Las filas
  posteriores mantienen su número físico y RAW las muestra; la política no
  convierte el trabajo en `FAILED`.
- **P1-11 — Extended GTFS Route Types — DONE.** `domain/route_types.py` aloja
  el catálogo estático de los 81 códigos extendidos documentados por [Google
  Transit](https://developers.google.com/transit/gtfs/reference/extended-route-types),
  separado del enum core del schema y sin acceso de red en runtime. `715` se
  presenta como `Demand and Response Bus Service (Google Transit extended)` y
  otro valor conocido, como `1301`, sigue siendo extensión; ningún valor se
  convierte automáticamente a `3`. Los códigos desconocidos, por ejemplo
  `999`, conservan la validación correspondiente y su lexema RAW; los valores
  conocidos conservan el original en la revalidación y exportación Mini-GTFS.
- **P1-12 — Contrato y validación de Mini-GTFS — DONE.** La unidad de selección
  real es una o varias rutas, opcionalmente restringidas por viajes y servicios;
  no existe selección autónoma de `trip_id` o `service_id`. El cierre core
  conserva agencia, rutas, viajes, paradas y ancestros `parent_station`,
  `stop_times`, servicios de `calendar`/`calendar_dates` y shapes referenciadas.
  El modelo actual añade, solo cuando existen filas cerradas, `frequencies`,
  `transfers`, `feed_info` y `attributions`; opcionales no soportados, `project.json`,
  DuckDB, staging, manifiestos internos y rutas absolutas quedan fuera.
- El escritor exige todas las tablas core requeridas por los servicios seleccionados,
  rechaza tablas core vacías y valida antes de publicar. Conserva IDs y lexemas
  originales, `route_type=715`, UTF-8, horas `>=24:00:00`, secuencia y repeticiones
  de `stop_times`; no deduplica por `stop_id`, no regenera IDs ni estrecha fechas de
  `feed_info`. Las relaciones a ruta B y sus filas exclusivas se excluyen, mientras
  que las paradas compartidas y ancestros necesarios permanecen.
- La regresión `tests/test_mini_gtfs_contract.py` importa un fixture completo,
  exporta ruta A, cierra las conexiones de origen, reimporta el ZIP en otra DuckDB,
  valida `READY / 0`, comprueba reapertura, manifest SHA-256/tamaño y determinismo.
  `calendar_dates` admite servicios definidos únicamente por excepciones incluso
  cuando coexiste `calendar.txt`.
- Evidencia P1-12: focal ampliada `55 passed`; suite completa `346 passed`;
  `tools/check.ps1: PASS`; Ruff, formato, mypy y
  `git diff --check`: `PASS`. Este bloque no construyó portable/NSIS ni modificó
  schema, mapas, KML/KMZ, historial o edición P2, y no incluyó ni ejecutó el ZIP CTM.
- BACKLOG P1-12: soporte de opcionales GTFS no normalizados (por ejemplo
  `translations`, `pathways`, tarifas y reglas de reserva), una regresión CTM
  externa cuando se autorice y proporcione el artefacto, y revisión GUI empaquetada.
  No son bloqueadores de P1-12.
- Evidencia P1-13 + P1-14: tests focales de exportación, naming, ayuda,
  P1-04B3, P1-12 y UI `93 passed`; suite completa `362 passed`;
  `tools/check.ps1: PASS`; Ruff format/lint, mypy y `git diff --check`:
  `PASS`. No se modificaron los escritores, el contenido exportado, schema,
  historial, mapas, KML/KMZ ni packaging; no se construyó portable/NSIS.
- BACKLOG P1-13 + P1-14: variantes avanzadas de naming/ayuda y revisión GUI
  empaquetada. No son bloqueadores del bloque actual.
- **P1-15 — Suite integral de regresión de exportaciones — DONE.** Se añadió
  `tests/test_export_regression.py` con ocho regresiones sobre el flujo
  productivo de JSON, GeoJSON, CSV y Mini-GTFS, y
  `tests/helpers/export_contract.py` con la matriz cerrada de capacidades.
  El fixture común conserva rutas compartidas y exclusivas, varios servicios,
  shapes, `route_type` extendido `715`, horas `>=24:00:00`, repetición de
  parada y Unicode. La suite cubre selección, naming, publicación atómica,
  manifest, SHA-256/tamaño, historial, privacidad, determinismo, reapertura,
  fallos antes/durante/después de publicar y reimportación independiente del
  Mini-GTFS. No se añadieron formatos ni cambios de producción.
- Evidencia P1-15: focal nueva `8 passed`; suite completa `370 passed`;
  `tools/check.ps1: PASS`; Ruff format/lint, mypy y `git diff --check`:
  `PASS`. No se ejecutó CTM (opcional y sin artefacto autorizado), ni se
  construyó portable/NSIS. No hay bloqueadores de P1-15.
- **P1-16 — Mapas — Privacidad y política offline-first — DONE.** Se formalizó
  `AUTO`, `OFFLINE` y `ONLINE` con estado visible `local/offline`, `online` o
  `no disponible`. `AUTO` es el default de sesión y conserva la experiencia
  actual: prioriza el PMTiles local validado y, al no existir proveedor online,
  mantiene el fondo neutro cuando no hay paquete. `OFFLINE` bloquea cualquier
  origen exterior; `ONLINE` queda explícito pero sin proveedor operativo, por
  lo que no intenta red.
- El inventario runtime queda cerrado en recursos `file:///` y
  `qrc:///qtwebchannel/qwebchannel.js`, más el loopback efímero
  `127.0.0.1` protegido de DEC-016 para `style.json`, PMTiles y assets
  verificados. No hay proveedor, CDN, descarga, API key, token persistente,
  tracking, analytics ni telemetría. El interceptor no conserva URLs
  bloqueadas; la frontera de futuras teselas externas solo admite `z/x/y` y
  rechaza query, credenciales, bbox e identificadores GTFS.
- El cambio de proyecto conserva la preferencia global y limpia únicamente el
  contexto de viaje; P0-005 sigue siendo contractual. No se ha creado caché
  nueva: se mantiene la caché de viewport existente y el `no-store` del
  loopback. La gestión de paquetes offline queda para P1-18.
- Evidencia P1-16: `tests/test_map_policy.py` `12 passed`; focal mapa,
  paquete, capas y WebEngine `27 passed`; regresiones P0-005 `5 passed`; suite
  completa `383 passed`; `tools/check.ps1: PASS`; Ruff format/lint, mypy y
  `git diff --check`: `PASS`. No se construyó portable/NSIS.
- `BLOCKERS`: ninguno. `BACKLOG`: la intermitencia histórica del spike
  WebEngine/Chromium, si reaparece sin romper el contrato de privacidad y
  fallback, requiere una tarea posterior independiente.
- **P1-17 — Mapa híbrido PMTiles/online con overlay GTFS local — DONE.** La
  arquitectura separa basemap, overlay GTFS y política de fuente. El proveedor
  central actual es `OpenStreetMap Standard` por HTTPS, solo para teselas
  interactivas y con atribución visible `© OpenStreetMap contributors`; no hay
  API key, token ni selección de múltiples proveedores.
- `AUTO` compara la envolvente local de `routes/shapes/stops` con el `bbox` del
  manifiesto PMTiles y usa el paquete cuando cubre el overlay completo; fuera de
  cobertura, o sin paquete compatible, usa online. `OFFLINE` mantiene cero
  requests remotos y conserva el overlay sobre fondo neutro fuera de cobertura.
  `ONLINE` fuerza el proveedor remoto aunque exista PMTiles.
- El cambio runtime de basemap no modifica DuckDB, IDs, shapes, selección,
  `route/trip/service` ni el overlay; mantiene razonablemente center, zoom,
  bearing y pitch. Cambiar de proyecto limpia el overlay anterior mediante el
  contrato P0-005. Los fallos DNS/HTTP/timeout/tesela/estilo se reducen a estado
  neutral sin crash; `ONLINE` no hace fallback automático a `OFFLINE`.
- El interceptor permite recursos locales, loopback validado y únicamente el
  hostname del proveedor activo. Las teselas externas solo contienen `z/x/y`;
  no salen IDs, nombres, shapes, GeoJSON, paths, workspace, historial,
  selección ni tokens del GTFS. Se mantiene la caché normal de WebEngine/HTTP y
  no se añade prefetch, downloader ni caché offline nueva.
- La base queda preparada para P1-18 mediante bounds del overlay y del paquete,
  sin catálogo regional ni gestión/descarga inteligente de PMTiles.
- Evidencia P1-17: `tests/test_map_hybrid.py` y focales de política/capas/paquete,
  `40 passed`; suite completa `400 passed`; `tools/check.ps1: PASS`; Ruff
  format/lint, mypy y `git diff --check`: `PASS`. No se construyó portable/NSIS.
- `BLOCKERS`: ninguno. `IMPORTANTE-PERO-NO-BLOQUEANTE`: la validación de
  disponibilidad real del proveedor y el gate visual WebEngine requieren una
  sesión manual autorizada. El smoke local `--map-runtime-smoke` se intentó en
  Qt offscreen y quedó impedido por la ausencia de un contexto GLES/WebGL2 en
  Chromium; los tests usan stubs y no Internet real.
- `BACKLOG`: selección de más proveedores, catálogo/descarga de regiones,
  prefetch, caché offline avanzada, generación de PMTiles, satélite, geocoding y
  routing; la intermitencia histórica WebEngine/Chromium sigue siendo posterior.
- No hay ninguna tarea del orquestador en ejecución.

## P1-30 — Documentación de usuario y ayuda integrada (2026-08-27)

P1-30 queda implementada. [`docs/USER_GUIDE.md`](USER_GUIDE.md) consolida los
journeys productivos actuales: proyectos, importación y estados VALID/INVALID,
validación, rutas, RAW, mapas AUTO/OFFLINE/ONLINE, exportaciones, historial,
directorios, recovery, diagnósticos, accesibilidad y privacidad. La ayuda local
buscable se amplió con el mismo contrato y sigue disponible desde Ayuda/F1 sin
proyecto ni conexión. [`docs/HELP_PACKAGING_MANIFEST.json`](HELP_PACKAGING_MANIFEST.json)
deja identificados los archivos que P1-32 deberá incluir en portable e
instalador. README enlaza la guía sin duplicarla.

El GATE TIERRA pre-release está cerrado en
[`docs/P1_PRE_RELEASE_GATE.md`](P1_PRE_RELEASE_GATE.md): no halló RELEASE
BLOCKERS y libera A031 sin ejecutarla. P1-32 packaging, `NSIS_BINARY_GATE`,
P1-33 upgrade y P1-34 RC siguen pendientes. No se cambió el schema ni se
construyeron artefactos.

Evidencia P1-30: tests focales de documentación/ayuda, identidad, i18n y
accesibilidad; 11 E2E; suite completa; `tools/check.ps1`; Ruff format/lint,
mypy y `git diff --check` ejecutados al cierre. El finding `TIMEOUT` de LARGE
en staging sigue siendo técnico, aislado y no bloqueante. La revisión manual
con lector de pantalla y el gate visual del WebEngine siguen pendientes.

### P1 PRE-RELEASE GATE SUMMARY

- P1-01 → P1-30 y GATE TIERRA: completados.
- `CORE_FREEZE_READY = YES`; `A031_UNFREEZE = YES`; A031 no se ha iniciado.
- `PACKAGING_READY_AFTER_A031 = YES`; packaging y `NSIS_BINARY_GATE` siguen
  pendientes en P1-32.
- P1-33 Upgrade y P1-34 RC: no iniciados.
- RELEASE BLOCKERS: ninguno.
- IMPORTANTE-PERO-NO-BLOQUEANTE: revisión manual de lector de pantalla,
  smoke visual WebEngine y revisión legal/publicación.
- BACKLOG: screenshots mantenibles, profiling/optimización de LARGE y mejoras
  futuras de documentación.
- Performance: `LARGE staging TIMEOUT` permanece como finding técnico, no como
  error universal de feeds grandes.
- Pruebas manuales pendientes: lector de pantalla, foco visual final y gates
  binarios de packaging.

## Próximo paso autorizado por el plan

- **A031**, si se aplican componentes aprobados por A030, antes de P1-32
  Packaging, P1-33 Upgrade y P1-34 RC.
- La rama F100 — Motor de simulación queda fuera de la actualización `0.1.0-rc2` y no debe iniciarse sin una nueva autorización de fase.
- La publicación o distribución de cualquier RC seguirá requiriendo autorización explícita de Yeison.

## Problemas y decisiones abiertas

- El smoke de T001 se ha validado en Windows 11 x64; el Windows mínimo exacto de producto queda pendiente de la validación de compatibilidad prevista en el plan.
- El servidor loopback del mapa deberá conservar en producción las restricciones demostradas en DEC-016; no se autoriza escuchar en LAN/WAN ni servir rutas arbitrarias.
- Falta validar usuarios, comprador y disposición a pagar antes de gastos o publicación.
- Firma de código, mapas comerciales y licencia Qt comercial son opcionales y requieren autorización.

## Para retomar el proyecto

1. Lee `../AGENTS.md`.
2. Lee este documento.
3. No inicies F100 ni otra fase futura sin una nueva autorización; A031 está
   habilitada por el gate, pero no iniciada.
4. Lee únicamente la ficha autorizada, sus dependencias y archivos relacionados.
5. No uses el chat histórico como fuente normativa frente al código, tests o referencia oficial GTFS.

El orquestador se controla con `tools/plan_orchestrator.ps1`; su registro de estados es `docs/TASK_STATUS.json` y los bloqueos se documentan en `docs/TAREAS_PENDIENTES.md`.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## P1-29 — Accesibilidad y navegación por teclado (2026-08-27)

P1-29 queda implementada sobre la base accesible previa. Se auditaron las
superficies Qt principales: ventana y navegación, proyecto/resumen,
importación/progreso/cancelación, RAW, explorador relacional, validación,
exportación, mapas y gestor de paquetes offline, historial, recovery, About y
ayuda. Los formularios relevantes asocian sus labels mediante `buddy`; filtros,
tablas, selectores, paginación y acciones compactas exponen nombres accesibles,
tooltips o descripciones cuando aportan contexto. Se conserva el orden lógico de
tabulación existente y el comportamiento nativo de Qt para flechas, completer,
Enter, Escape, Space, selección y tablas.

Los estados de progreso, mapas, errores y paginación mantienen representación
textual; las acciones que requieren proyecto siguen deshabilitadas en
`NO_PROJECT`. Escape se garantiza en los diálogos propios sin convertirlo en una
acción destructiva. Las cadenas nuevas pasan por el catálogo i18n español.

Regresión focal P1-29 y superficies relacionadas: `82 passed`. No se cambió el
schema ni se inició A031 o packaging. P1-30 queda cerrado en la sección de
documentación anterior. BACKLOG: accesibilidad cartográfica
avanzada del lienzo MapLibre/WebGL y prueba manual con lector de pantalla; no se
promete certificación NVDA/JAWS/Narrator.
