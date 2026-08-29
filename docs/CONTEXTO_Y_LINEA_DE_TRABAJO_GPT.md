# Contexto y línea de trabajo para GPT

Última actualización: 2026-08-27

Este documento es el punto de entrada para otro GPT que vaya a continuar el proyecto. La fuente de verdad sigue siendo el código, los tests y los documentos enlazados; este archivo resume qué debe leer y cuál es el siguiente trabajo autorizado.

## Objetivo del producto

GTFS Explorer Desktop es una aplicación Windows x64, portable y offline-first para importar, explorar, validar, visualizar y exportar GTFS Schedule sin exigir herramientas de desarrollo al usuario final.

El alcance actual incluye importación segura de ZIP, carpeta y CSV compatible, staging y modelo tipado en DuckDB, validación trazable, consultas de rutas, viajes, paradas, horarios y geometría, exportación JSON/GeoJSON/CSV/Mini-GTFS, mapa local MapLibre con PMTiles opcional, ayuda offline, accesibilidad base, diagnóstico local, portable e instalador NSIS por usuario.

GTFS Realtime, cuentas, telemetría y dependencia de red quedan fuera de esta fase.

## Estado comprobado

- La línea base `T000–T096` está terminada según `docs/TASK_STATUS.json`.
- La candidata local actual es `0.1.0-rc1`; está preparada técnicamente, pero no está publicada ni autorizada para distribución.
- `A000` (inventario del trabajo local), `A001` (alcance y versión objetivo) y `A010` (identidad del producto) están terminadas.
- La actualización mantiene como versión objetivo `0.1.0-rc2`, limitada a cambios no contractuales que superen sus pruebas y gates.
- `A030` está completada en `docs/A030_AUDITORIA_VERSIONES_2026-08-23.md`:
  la auditoría no actualizó dependencias y dejó los componentes de mayor riesgo
  como trabajo `PROBAR` acotado.
- `P1-25 + P1-26 — Identidad, metadata y versión visible` están `DONE`: la
  fuente única es `src/gtfs_explorer/product.py` y su identidad alimenta
  runtime, UI/Acerca de, diagnósticos, benchmark, manifiestos y builders
  portable/NSIS. La evidencia y el límite de no construir artefactos nuevos
  están documentados en `docs/CURRENT_STATE.md`.
- `P0-001` está `DONE` con evidencia manual de `P0-001-regression-03`: se
  recuperó `CTM-MiniGTFS-Route-102` legacy sin reimportación, hubo tres ciclos
  `open → close → open` correctos, desaparecieron `UI-0001` y `UI-0003`, y su
  DuckDB conservó SHA-256
  `D4674F72775B05A6E43D6B3B1BD8A732DF051CEE23329AD337DB287296C01182`.
  También se recuperó `CTM-Mallorca-Regression-02` legacy, con cierre y
  reapertura correctos, preservando `IMPORTED / INVALID / 4` incidencias; su
  DuckDB conservó SHA-256
  `B4DE215E398AB316C5CBB52672CD2CFC59CA8A4EA6FD68555EECEC67EBC0E7E6`.
- `P0-002 — DIAG-DEFECT-001` está `DONE`, cerrada con la evidencia final
  `P0-002-regression-05`.
- `P0-003 — Persistencia tras cierre/reapertura` está `DONE` con la evidencia
  final documentada abajo.
- `P0-004 — Cancelación de trabajos` está `DONE` con el artefacto
  `P0-004-regression-01` y la evidencia final documentada abajo.
- `P0-005 — UI-STATE-001` está `DONE` con el artefacto
  `P0-005-regression-01` y la evidencia final documentada abajo. P0-001,
  P0-002, P0-003, P0-004 y P0-005 están todos `DONE`.
- `P1-01 — UX-PROJECT-001 — Identidad visible del proyecto` está `DONE`.
- `P1-02 — UX-IMPORT-001/002` está `DONE`, cerrada con el artefacto
  `P1-02-regression-01` y portable SHA-256
  `7DC96746BC1BC2D04C3684B16F04F1FC93BE890446D9579618FA1D2AE1AAF6EF`.
  La observabilidad runtime muestra feed activo, fase traducida, progreso,
  cancelación y elapsed monotónico, con limpieza al terminar. No hay
  persistencia de duración, ETA, cambio de schema, logging por tick, thread
  adicional ni historial persistente.
- `P1-03 — Estado visible del feed` está `DONE`, cerrada con el artefacto
  `P1-03-regression-01` y portable SHA-256
  `43571FAB01F0091480196F403C30122107959AADE2CCAE5D052A836BAB81949F`.
  Tests focales `38 passed`, suite completa `282 passed`,
  `tools/check.ps1`, Ruff, mypy y `git diff --check`: `PASS`. La regresión
  manual A-F confirmó la separación entre estado técnico de importación y
  resultado de validación, incluyendo sin feed, `IMPORTED + VALID`,
  `IMPORTED + INVALID`, `CANCELLED`, `FAILED` y conservación del feed previo
  tras reimportación cancelada. El `writer.lock` stale observado en un caso
  controlado queda fuera de P1-03 y registrado para Robustez de workspace /
  Recuperación segura.
- `P1-04 — Historial de operaciones` está `DONE`, con auditoría final
  `P1-04-AUDITADO-CERRABLE`. P1-04A/A2/A3/A4, B1, B2, B3 y C están `DONE`.
  Auditoría Tierra: sin RELEASE BLOCKERS. La suite actual de referencia es
  `320 passed`. Portable/NSIS, EXPORT/CANCELLED con exportación async,
  VALIDATION standalone si se incorpora flujo manual y revisión de
  documentación residual quedan como BACKLOG independiente de P1-04.
- `P1-09`, `P1-10`, `P1-11` y `P1-12` quedan `DONE` como bloques técnicos
  consecutivos:
  semántica directa de `arrival_time`/`departure_time` sin inferencias de
  oficialidad, líneas físicas vacías ignoradas como filas lógicas conservando
  `source_row`, y catálogo local completo de Extended GTFS Route Types con
  `715` soportado sin sobrescribir el valor original. P1-12 cerró el contrato
  Mini-GTFS con cierre transitivo, opcionales normalizados filtrados,
  reimportación en proyecto independiente, validación `READY / 0`, manifest
  verificable y fixture versionable. La evidencia de cierre y el detalle de
  archivos están en `docs/CURRENT_STATE.md`. P1-13 y P1-14 están cerradas;
  P1-15–P1-24 y P1-25/P1-26 se encuentran cerradas según ese documento.
- No hay tareas del orquestador Txxx en ejecución.
- El ZIP `examples/ctm-mallorca-es.zip` se conserva localmente, pero está fuera del alcance y no puede entrar en los artefactos ni en el recorrido de ejemplo.

## Arquitectura que debe conservarse

- Python 3.12, PySide6/Qt Widgets y DuckDB por proyecto.
- Capas `domain` → `application` → `infrastructure` → `presentation`.
- La UI no conoce SQL; el dominio no conoce Qt, DuckDB ni filesystem.
- Staging fiel (`stg_*`) y modelo tipado (`gtfs_*`), con derivados regenerables (`drv_*`) y vistas de consulta (`v_*`).
- Horas GTFS conservadas como segundos de servicio y lexema original, incluidos valores superiores a `24:00:00`.
- MapLibre y PMTiles locales, servidos únicamente mediante loopback efímero protegido; nunca escuchar en LAN/WAN ni servir rutas arbitrarias.
- Portable standalone e instalador NSIS por usuario; el workspace debe quedar fuera del directorio de programa y sobrevivir a la desinstalación.

La explicación completa está en `docs/ARCHITECTURE.md` y las decisiones vinculantes en `docs/DECISIONS.md`.

## Restricciones de trabajo

1. Trabajar con una sola tarea principal por sesión.
2. Leer primero `AGENTS.md`, este documento y solo la ficha de la tarea, sus dependencias y los archivos directamente relacionados.
3. No usar el chat histórico como fuente normativa frente al repositorio.
4. No hacer refactors especulativos, cambios cosméticos generales ni introducir dependencias sin justificación.
5. No alterar contratos de importación, validación o exportación sin una nueva decisión explícita.
6. No publicar, distribuir, firmar, comprar servicios ni añadir datos externos sin autorización expresa, licencia, procedencia y atribución verificadas.
7. Conservar el trabajo local inventariado en `docs/INVENTARIO_ACTUALIZACION_A000.md`.

## Orden de trabajo de la actualización

```text
A000 DONE → A001 DONE → A010 DONE
                         ├→ A011 → A012 ─┐
                         ├→ A013          ├→ A040 → A041 → A042 → A043 → A044
                         ├→ A030 → A031? ─┤
                         └→ A021? ────────┘
```

`A021` solo se ejecuta si se autoriza un fixture o feed de ejemplo. `A031` solo se ejecuta si `A030` aprueba actualizaciones concretas. A040 no puede empezar hasta cerrar o descartar explícitamente las ramas que formen parte de la versión.

## Cierre documentado: P0-002 — DIAG-DEFECT-001

P0-002 conserva `error_code`, `operation`, `timestamp`, `exception_type`,
`exception_message`, `traceback`, causa encadenada cuando existe, versión,
estado de aplicación y basename, función y línea de cada frame. El ejemplo real
validado contiene `main_window.py:332` en `_choose_project` y
`open_project.py:115` en `execute`.

La evidencia final de `P0-002-regression-05` es: suite completa `262 PASS`,
tests específicos de diagnóstico `PASS`, `tools/check.ps1` `PASS`,
portable/NSIS/licencias/SBOM y smokes `PASS`, regresión manual instalada `PASS`
y `git diff --check` `PASS`. El ZIP de diagnóstico contiene únicamente
`gtfs-explorer.log`; no se exponen rutas absolutas, nombre de usuario, project
path, secretos ni datos GTFS, y el diálogo no muestra traceback. La aparente
regresión previa fue causada por ejecutar un EXE stale, no por un fallo de
Regression-05.

`build_id=''` permanece fuera de alcance y queda registrado para A032/versionado.

## Cierre documentado: P0-004 — Cancelación de trabajos

P0-004 queda cerrada formalmente como `DONE` con el artefacto
`P0-004-regression-01`. El contrato implementado añade `FeedStatus.CANCELLED`,
evita clasificar la cancelación voluntaria como `FAILED`, conserva `CANCELLED`
en la primera importación cancelada y conserva el último feed consistente
`IMPORTED` en una reimportación cancelada. La normalización consulta la
cancelación cooperativa por lotes; una validación cancelada no deja resultado
parcial final; `ImportJobAdapter` espera la finalización y liberación real de
`QThread`/worker antes de devolver la UI a la lista; y la doble cancelación es
segura. `started_at` y `finished_at` siguen `NULL` según el contrato global
actual.

La evidencia final es: suite completa `268 passed`; `tools/check.ps1`, Ruff,
mypy, `git diff --check`, portable smoke, smoke gráfico, NSIS y licencias/SBOM:
`PASS`.

La evidencia manual confirma: primera importación cancelada con `CANCELLED`, 0
métricas, sin validaciones, sin inventario parcial y sin `FAILED`; `cancel →
close → reopen` conserva `CANCELLED`; `cancel → nuevo trabajo` termina
`IMPORTED` con 1 agencia, 10.000 paradas, 1 ruta, 10.000 viajes y 500.000
eventos; una reimportación cancelada conserva `IMPORTED`, métricas, inventario y
validación previos; y la reimportación cancelada seguida de cierre/reapertura
conserva estado, métricas, periodo, una sola validación y reutilización del
proyecto.

## Cierre documentado: P0-003 — Persistencia tras cierre/reapertura

El nuevo test `tests/test_project_persistence_reopen.py` añade 3 tests y
demuestra VALID close/reopen `PASS`, INVALID close/reopen `PASS`, reapertura
repetida `PASS`, frontera real de proceso mediante un nuevo intérprete Python
`PASS` y coherencia `project.json` / DuckDB `PASS`. La evidencia final es:
tests específicos `3 passed`, batería relevante `29 passed`, suite completa
`265 passed`, `tools/check.ps1: PASS` y `git diff --check: PASS`. No hubo cambios
de producción y no quedan riesgos restantes dentro de P0-003.

El contrato es: DuckDB es la fuente canónica del estado persistente;
`project.json` es un descriptor/espejo verificable; validación, incidencias y
estadísticas se reconstruyen desde DuckDB; pestañas, filtros y selecciones son
estado transitorio de UI y no pertenecen a P0-003. El mismatch legacy
recuperable de `project.json` sigue gobernado por P0-001. No se ha demostrado
pérdida real de persistencia.

## Cierre documentado: P0-005 — Reset entre proyectos / UI-STATE-001

P0-005 queda cerrada formalmente como `DONE` con el artefacto manual
`P0-005-regression-01`:

`GTFS-Explorer-Portable-0.1.0-P0-005-regression-01-win-x64.zip`

SHA-256: `B1C4747328A57642146F2D5A685B65DBCD9F823BEE040AD651AF92E36ACA4098`.

La evidencia automatizada es: tests P0-005 `5 passed`, batería UI `27 passed`,
suite completa `275 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS`,
`git diff --check: PASS` y `NO-ASYNC-LATE-CALLBACK-RISK`. La producción ya
estaba implementada y no tuvo cambios adicionales durante la fase final de
regresión.

Evidencia manual A — A sucio → abrir B: se configuraron deliberadamente en A
RAW (`routes.txt`, columna `route_id`, filtro `TEST_P0_005_A`), Validación
(`ERROR`), Exportación (GeoJSON, rutas `R1`, viajes `R2`) y la pestaña `Datos
raw`. Al abrir B, la aplicación volvió a `Proyecto`, B fue el único contexto
activo, RAW mostró sus datos propios sin el filtro de A, Validación volvió a
`Todas las severidades` y `Todas las categorías`, Exportación no conservó R1,
R2, destino ni formato personalizado, y no hubo mezcla visual. Resultado:
`PASS`.

Evidencia manual B — close → reopen same project: tras `close B → reopen B →
Explorar`, la pestaña volvió a `Rutas, viajes y paradas`; `Datos raw` no
permaneció seleccionada, los selectores se reconstruyeron desde B, los datos
persistieron y el estado transitorio de UI no persistió. Resultado: `PASS`.

Contrato final: se resetean filtros RAW, archivo/columna/contexto RAW,
paginación, filtros y selecciones/incidencias de Validación, contexto de
Exportación, route/trip/service IDs, destino de exportación, selectores de
Exploración, pestaña interna, navegación contextual y estado de mapa ligado al
feed. Se preservan tema, ajustes visuales, configuración global de mapa y
paquete de mapa cuando corresponda. P0-005 no introduce persistencia de
filtros ni preferencias nuevas.

## Cierre documentado: P1-01 — UX-PROJECT-001 — Identidad visible del proyecto

P1-01 queda cerrada como `DONE`. La identidad global aparece en la barra de
estado y en la página Proyecto con nombre y workspace real; el tooltip conserva
la ruta completa. `NO_PROJECT` muestra `Sin proyecto abierto` y `Workspace: —`.
El título de ventana no se modifica.

La implementación no altera persistencia, `project.json`, DuckDB, IDs ni
recuperación legacy, y los diagnósticos no incorporan rutas nuevas.

Evidencia automatizada: tests específicos `34 passed`, suite completa
`277 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS` y
`git diff --check: PASS`.

Evidencia manual `PASS`: `NO_PROJECT`; `open A`; `A → B`; `B → close →
NO_PROJECT`; `close → reopen A`; y apertura de proyecto inválido desde A. Este
último flujo confirmó `UI-0001`, estado final `NO_PROJECT`, sin identidad
residual de A y sin identidad falsa del proyecto inválido.

Se encontró un `.writer.lock` stale asociado a un PID ya inexistente. No se
corrige dentro de P1-01 y se registra como evidencia para Robustez de workspace
/ Recuperación segura en P1 posteriores. Observación UX menor no bloqueante: en
`NO_PROJECT` puede aparecer dos veces `Sin proyecto abierto` en la barra
inferior; queda pendiente para observabilidad/UX y no se modifica código.

## Cierre documentado: P1-02 — UX-IMPORT-001/002 — Importaciones informativas

La evidencia automatizada es: tests específicos P1-02 `4 passed`, suite
completa `281 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS` y
`git diff --check: PASS`.

La regresión manual utilizó `P0-004-manual-feed-medium.zip`, con 10.000
paradas, 10.000 viajes y 500.000 stop_times/eventos. Se confirmó el inicio
con proyecto `P1-02-Manual-Import`, workspace, feed activo, `Carga`, 20 % y
elapsed `00:04`; el avance posterior a `00:27`; y las fases `Carga 20 %` →
`Normalización 40 % / 16:14` → `Validación 60 % / 24:42` sin reiniciar el
elapsed. Tras completion desaparecieron los datos transitorios, se detuvo el
timer, se deshabilitó `Cancelar trabajo`, el proyecto quedó listo y el feed
persistente permaneció `IMPORTED` con sus métricas. La cancelación mostró el
diálogo y mensaje de cancelación limpia, sin error técnico, limpió el contexto
runtime y conservó el feed previo `IMPORTED`, sus métricas y la validación.

`Cancelando…` no pudo capturarse manualmente porque el worker terminó antes de
la captura; los tests y el contrato P0-004 lo cubren de forma determinista y no
es blocker.

## Cierre documentado: P1-03 — Estado visible del feed

P1-03 queda cerrada formalmente como `DONE` con `P1-03-regression-01`. La
sección `Estado del feed` separa el estado técnico de importación del resultado
de validación y sus incidencias. `IMPORTED + VALID`, `IMPORTED + INVALID`,
`CANCELLED`, `FAILED` y sin feed quedan semánticamente diferenciados; P1-02
continúa siendo el contexto runtime de la operación activa.

La evidencia automatizada es: tests focales `38 passed`, suite completa
`282 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy `PASS` y
`git diff --check: PASS`. El portable validado tiene SHA-256
`43571FAB01F0091480196F403C30122107959AADE2CCAE5D052A836BAB81949F`.

La evidencia manual A-F pasó en los casos sin feed, `IMPORTED + VALID`,
`IMPORTED + INVALID`, primera importación cancelada, fallo técnico y
reimportación cancelada. Esta última conservó el feed `invalid_core.zip`, su
estado `IMPORTED / INVALID`, sus 4 incidencias, métricas e inventario previos.
La observación UX sobre el texto genérico de métricas en cancelación es no
bloqueante y queda para una tarea futura. Durante el caso `FAILED` se observó
un `writer.lock` stale tras el cierre forzoso controlado de una instancia
antigua; se restauró el ACL temporal y la incidencia queda registrada para
Robustez de workspace / Recuperación segura, fuera de P1-03.

## Estado histórico de P0-001

La reparación solo admite un descriptor JSON válido, DuckDB legible y con la
versión vigente, identidad/nombre/referencias locales coherentes y una
divergencia limitada a `status`, `feed.feed_id` y
`feed.manifest_sha256`. DuckDB es canónico únicamente para esos campos
operativos. Un `project_id`, nombre, referencias, esquema o patrón de feed no
reconocido se rechaza sin alterar `project.json`.

El descriptor corregido se publica en el mismo directorio mediante temporal,
flush, `fsync` y reemplazo atómico; DuckDB no se modifica. La regresión manual
`P0-001-regression-03` queda cerrada con la evidencia resumida arriba. No
modificar esta implementación durante P0-002 salvo necesidad estricta y
demostrada.

## Criterios de cierre

Una candidata nueva solo se considera preparada cuando pasa las pruebas específicas, `tools/check.ps1`, build reproducible portable/instalador, matriz Windows limpio y upgrade N-1; además, documentación, versión, SBOM, licencias, manifiestos y hashes coinciden. La revisión jurídica LGPL/Qt WebEngine, la licencia propia y la autorización de publicación siguen siendo gates humanos.

## Lectura recomendada para GPT

1. `AGENTS.md`
2. `docs/CURRENT_STATE.md`
3. `docs/CONTEXTO_Y_LINEA_DE_TRABAJO_GPT.md`
4. `docs/PLAN_ACTUALIZACION_HERRAMIENTA.md`
5. `docs/ARCHITECTURE.md` y `docs/DECISIONS.md` si la tarea lo requiere
6. `docs/INVENTARIO_ACTUALIZACION_A000.md` para el trabajo local diferido
7. `docs/TASK_STATUS.json` y los tests/archivos de la tarea concreta

## Instrucción de arranque para GPT

> Trabaja sobre el repositorio actual de GTFS Explorer Desktop. Lee primero
> `AGENTS.md`, `docs/CURRENT_STATE.md` y este documento. P0-001, P0-002,
> P0-003, P0-004, P0-005 y P1-01 ya están `DONE` con sus evidencias
> documentadas. P1-02 y P1-03 están `DONE` con sus regresiones automatizadas y
> manuales. P1-04 está documentada como `DONE`. No inicies P1-05, A031 o una
> mejora UX adicional sin una tarea autorizada.

Al terminar cualquier sesión, registrar archivos modificados, comprobaciones ejecutadas, evidencia real, riesgos y el siguiente estado. No declarar una tarea terminada solo porque el código parezca correcto.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
