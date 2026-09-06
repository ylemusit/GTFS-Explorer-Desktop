# Plan de actualización de GTFS Explorer Desktop

Fecha de creación: 2026-08-18
Última revisión: 2026-08-25

Estado: **P0-001, P0-002, P0-003, P0-004, P0-005, P1-01, P1-02, P1-03 y P1-04 DONE con evidencia validada; no iniciar P1-05**

## 1. Objetivo

Preparar la siguiente versión de GTFS Explorer Desktop a partir del estado actual,
resolviendo primero los bloqueadores de ciclo de vida, diagnóstico, persistencia,
cancelación y estado entre proyectos, y después consolidando UX, validación,
mapas, exportaciones, robustez, dependencias y release sin degradar las funciones
GTFS ya verificadas ni alterar sus contratos públicos.

Este documento define trabajo futuro. A000, A001 y A010 constan como cerradas
en sus evidencias y en `docs/CURRENT_STATE.md`; las demás tareas `Axxx` no se
consideran implementadas, probadas ni aprobadas. El resumen operativo para
traspaso operativo está en `docs/SESSION_CONTEXT.md`; el documento histórico
equivalente está preservado en GTFS Explorer Engineering.

El backlog priorizado de la sección 9 es la fuente operativa para continuar la
mejora del producto. Las tareas `Axxx` conservan el marco de actualización,
empaquetado y gates humanos; se ejecutarán solo cuando sus dependencias y la
prioridad del backlog lo permitan.

## 2. Línea base comprobada

- `0.1.0-rc1` es una candidata local; no está autorizada para publicación o
  distribución.
- Las tareas `T000`--`T096` aplicables a la primera candidata constan como
  completadas en `docs/TASK_STATUS.json`.
- La aplicación importa, explora, valida, visualiza y exporta GTFS Schedule de
  forma local y offline-first.
- Existen portable e instalador Windows x64 verificados para la candidata
  actual.
- El upgrade real desde una versión N-1 (`I03`) no se pudo ejecutar en la
  primera candidata y será obligatorio en la siguiente versión instalable.
- Permanecen como gates externos la revisión jurídica de LGPL/Qt WebEngine, la
  decisión de licencia propia y la autorización expresa para distribuir.

## 3. Cambios locales que deben preservarse y revisar

Al crear este plan existen cambios sin integrar en:

- `packaging/nsis/installer.nsi`;
- `src/gtfs_explorer/presentation/desktop/main_window.py`;
- `src/gtfs_explorer/presentation/desktop/overview/widget.py`;
- `src/gtfs_explorer/presentation/desktop/startup_intro.py`.

Estos cambios son trabajo del usuario y no se consideran terminados por estar
presentes. La actualización deberá inventariarlos, comprobar su procedencia y
validarlos antes de incorporarlos a una versión.

El ZIP externo `examples/ctm-mallorca-es.zip` queda fuera del alcance de la
actualización y no forma parte de ninguna tarea. No se incorporará a Git, al
portable, al instalador ni al recorrido de ejemplo.

## 4. Restricciones

- Conservar la arquitectura PySide6, DuckDB, MapLibre local y empaquetado
  standalone/NSIS existentes.
- Mantener el funcionamiento local, offline-first, sin cuentas ni telemetría.
- No cambiar contratos de importación, validación o exportación salvo tarea y
  decisión explícitas.
- No introducir dependencias nuevas sin necesidad demostrada.
- No incluir un feed, mapa u otro dato externo sin procedencia, licencia,
  atribución y autorización verificadas.
- No publicar, distribuir, comprar, firmar código ni usar datos no autorizados
  como parte de estas tareas.
- Mantener los créditos a Yeison Arbey Carrillo Lemus y la mención “Todos los
  derechos reservados”.
- Ejecutar una sola tarea `Axxx` por sesión y respetar sus dependencias.

## 5. Definición de terminado de la actualización

La actualización estará preparada cuando:

1. todos los cambios incluidos tengan pruebas automáticas o evidencia manual
   reproducible;
2. la aplicación siga superando el flujo canónico de comprobaciones;
3. portable e instalador se reconstruyan desde fuentes y dependencias fijadas;
4. el upgrade N-1 conserve los proyectos y ajustes que deban persistir;
5. changelog, estado, ayuda, licencias, SBOM, hashes y manifiestos coincidan con
   los artefactos construidos;
6. no existan bloqueadores críticos o altos conocidos;
7. cualquier publicación quede separada detrás de sus autorizaciones.

## 6. Secuencia de tareas

### Fase A0 — Alcance y control de cambios

#### A000 — Inventariar y aislar el trabajo local existente

- **Estado:** `DONE` el 2026-08-18. Evidencia en
  `docs/INVENTARIO_ACTUALIZACION_A000.md`.

- **Objetivo:** determinar exactamente qué resuelve cada cambio local y evitar
  mezclar trabajo ajeno o incompleto.
- **Dependencias:** ninguna.
- **Alcance:** revisar el diff, clasificar cada archivo como incluido, diferido o
  descartado y registrar riesgos y pruebas faltantes.
- **Fuera de alcance:** reescribir o completar las funcionalidades.
- **Criterios de aceptación:** ningún cambio local queda atribuido a la nueva
  versión sin una decisión; el ZIP de ejemplo se mantiene fuera de artefactos.
- **Verificación:** `git status --short`, `git diff --check` y registro de alcance
  sin modificar ni eliminar trabajo existente.
- **Terminado:** existe una línea base reproducible para iniciar la actualización.

#### A001 — Fijar alcance y número de la siguiente versión

- **Estado:** `DONE` el 2026-08-18. Decisión: DEC-017.

- **Objetivo:** decidir si el resultado será otra candidata `0.1.0-rcN`, un
  parche o una versión menor.
- **Dependencias:** A000.
- **Alcance:** clasificar los cambios visibles y de comportamiento, comprobar si
  hay contratos públicos afectados y definir los entregables de la versión.
- **Fuera de alcance:** modificar todavía números de versión o artefactos.
- **Criterios de aceptación:** versión, alcance incluido, fuera de alcance y
  criterios de rollback constan en una decisión breve.
- **Verificación:** coherencia con SemVer, `CHANGELOG.md` y DEC-008.
- **Terminado:** todas las tareas posteriores usan una única versión objetivo.

### Fase A1 — Identidad y experiencia inicial

#### A010 — Centralizar identidad, créditos y textos legales

- **Objetivo:** evitar textos divergentes entre aplicación, ayuda e instalador.
- **Dependencias:** A001.
- **Alcance:** definir una fuente mantenible para nombre, edición, autor,
  copyright y aviso de derechos; reutilizarla donde técnicamente proceda.
- **Fuera de alcance:** decidir una licencia comercial o sustituir avisos de
  terceros.
- **Criterios de aceptación:** no hay contradicciones de nombre, año, versión o
  autor; los textos traducibles no quedan ocultos en estilos o imágenes.
- **Pruebas:** comprobaciones unitarias de metadatos y catálogo i18n.
- **Terminado:** identidad consistente y cubierta por pruebas.

#### A011 — Validar la presentación de inicio

- **Objetivo:** ofrecer una bienvenida clara sin bloquear ni degradar el
  arranque normal.
- **Dependencias:** A010.
- **Alcance:** diálogo inicial, política de cuándo se muestra, cierre por teclado,
  foco, escalado, lectores de pantalla y comportamiento ante errores de inicio.
- **Fuera de alcance:** tutorial completo o telemetría de adopción.
- **Criterios de aceptación:** la ventana principal puede abrirse en pruebas y en
  uso normal; la presentación se puede cerrar con ratón y teclado; no aparece en
  ejecuciones no interactivas que no la requieran.
- **Pruebas:** tests Qt del diálogo y smoke de arranque normal/portable.
- **Terminado:** presentación accesible, no bloqueante y con política explícita.

#### A012 — Mejorar el estado vacío y la orientación inicial

- **Objetivo:** indicar con claridad cómo crear o abrir un proyecto sin interferir
  con el resumen de un feed cargado.
- **Dependencias:** A010.
- **Alcance:** bloque de bienvenida, acción siguiente, estados sin proyecto/sin
  feed/con feed y adaptación a tamaños razonables de ventana.
- **Fuera de alcance:** rediseño general de navegación o paneles GTFS.
- **Criterios de aceptación:** el mensaje inicial se oculta al mostrar datos y
  reaparece al cerrar el proyecto; no duplica acciones ni induce a pérdida de
  datos.
- **Pruebas:** ampliar `tests/test_feed_overview.py` y la prueba de ventana.
- **Terminado:** todos los estados quedan diferenciados y verificados.

#### A013 — Actualizar la experiencia del instalador

- **Objetivo:** presentar producto, autor y alcance de instalación de forma
  coherente antes de copiar archivos.
- **Dependencias:** A010.
- **Alcance:** páginas MUI2, idioma español, bienvenida, directorio, progreso,
  confirmación de desinstalación y textos legales propios.
- **Fuera de alcance:** firma de código, elevación a administrador o publicación.
- **Criterios de aceptación:** instalación por usuario, actualización y
  desinstalación conservan el workspace; el instalador compila sin advertencias
  relevantes y no pierde funciones ya verificadas.
- **Pruebas:** tests del generador, compilación NSIS y smoke instalado.
- **Terminado:** instalador coherente con la aplicación y regresión I01/I02
  superada.

### Fase A2 — Recorrido de ejemplo opcional

#### A021 — Incorporar un recorrido de ejemplo seleccionado expresamente

- **Objetivo:** permitir que un usuario nuevo compruebe el flujo principal con
  datos autorizados.
- **Dependencias:** A011 y A012.
- **Alcance:** acceso explícito al ejemplo, copia a workspace, importación,
  validación, exploración, mapa y retirada/restablecimiento seguro.
- **Fuera de alcance:** descarga automática o dependencia de red.
- **Criterios de aceptación:** el original empaquetado es inmutable; cada usuario
  trabaja sobre una copia; licencia y atribución son visibles; los fallos dejan
  el workspace recuperable.
- **Pruebas:** flujo end-to-end offline desde portable e instalación.
- **Terminado:** demostración reproducible sin afectar proyectos reales.
- **Condición:** solo se ejecuta si se selecciona expresamente un fixture
  sintético o un feed cuya incorporación haya sido autorizada; el ZIP CTM local
  queda excluido de esta tarea.

### Fase A3 — Mantenimiento técnico controlado

#### A030 — Auditar especificación y dependencias fijadas

**Estado:** `DONE` el 2026-08-23. Evidencia: `docs/A030_AUDITORIA_VERSIONES_2026-08-23.md`.

- **Objetivo:** detectar actualizaciones necesarias por compatibilidad, seguridad
  o vigencia normativa sin actualizar por inercia.
- **Dependencias:** A001.
- **Alcance:** Python, PySide6/Qt WebEngine, DuckDB, Shapely, Nuitka, herramientas
  de desarrollo, MapLibre, PMTiles, esbuild, NSIS y revisión GTFS Schedule.
- **Fuera de alcance:** aplicar todas las versiones encontradas.
- **Criterios de aceptación:** cada componente tiene versión actual, versión
  candidata, motivo, riesgo, compatibilidad y decisión `MANTENER`, `PROBAR` o
  `ACTUALIZAR` basada en fuentes oficiales.
- **Verificación:** informe fechado y enlaces a documentación o avisos oficiales.
- **Terminado:** solo quedan propuestas justificadas y acotadas.

#### A031 — Aplicar actualizaciones técnicas aprobadas

- **Objetivo:** actualizar únicamente los componentes aprobados en A030.
- **Dependencias:** A030.
- **Alcance:** un componente o grupo inseparable por sesión; lockfile, build,
  licencias y pruebas afectadas.
- **Fuera de alcance:** cambios funcionales o varias migraciones independientes a
  la vez.
- **Criterios de aceptación:** lockfile reproducible, pruebas específicas y flujo
  canónico superados; rollback documentado.
- **Pruebas:** smoke de dependencia, `tools/check.ps1` y build afectado.
- **Terminado:** cada actualización aprobada tiene evidencia independiente.
- **Condición:** se omite si A030 decide mantener todas las versiones.

#### A032 — Unificar la versión del producto

- **Objetivo:** evitar valores de versión divergentes entre código, exportaciones,
  licencias, SBOM, instalador y artefactos.
- **Dependencias:** A001 y, si se ejecuta, A031.
- **Alcance:** fuente canónica de versión y consumidores de build/runtime.
- **Fuera de alcance:** publicar la versión.
- **Criterios de aceptación:** CLI, metadatos, manifiestos, nombres de artefactos y
  SBOM informan la misma versión; los datos persistidos conservan compatibilidad.
- **Pruebas:** tests de entrypoint, exportadores, licencias, portable, instalador y
  preparación de release.
- **Terminado:** no quedan literales de versión de producto divergentes salvo
  fixtures históricos explícitos.

### Fase A4 — Regresión, empaquetado y candidata local

#### A040 — Cerrar cobertura automática de la actualización

- **Objetivo:** cubrir los comportamientos añadidos y prevenir regresiones.
- **Dependencias:** A011, A012, A013, A032 y A021 si se ejecuta.
- **Alcance:** tests UI, accesibilidad verificable, instalador, recursos,
  versionado y fixture autorizado.
- **Fuera de alcance:** sustituir la matriz manual de Windows limpio.
- **Criterios de aceptación:** pruebas específicas y `tools/check.ps1` pasan sin
  exclusiones nuevas no justificadas.
- **Verificación:** resultado completo registrado con número de tests.
- **Terminado:** cero fallos y cero warnings nuevos relevantes.

#### A041 — Construir portable e instalador de la versión objetivo

- **Objetivo:** generar artefactos reproducibles con todos los recursos aprobados.
- **Dependencias:** A040.
- **Alcance:** portable, instalador, licencias, avisos, SBOM, manifiestos y hashes.
- **Fuera de alcance:** firma, subida o distribución.
- **Criterios de aceptación:** hashes laterales coinciden; el ZIP es íntegro; el
  instalador deriva del portable verificado; no hay recursos remotos inesperados.
- **Pruebas:** scripts de build y verificación de release en entorno local.
- **Terminado:** ambos artefactos quedan identificados e inmutables para el smoke.

#### A042 — Ejecutar matriz Windows limpio y upgrade N-1

- **Objetivo:** acreditar la experiencia real de la siguiente versión.
- **Dependencias:** A041.
- **Alcance:** P01, P02, I01, I02 e I03; inicio, proyecto, importación,
  validación, exploración, mapa, exportación, ayuda y persistencia.
- **Fuera de alcance:** corregir fallos dentro de la misma ejecución de evidencia;
  cada corrección debe reconstruir y volver a fijar artefactos.
- **Criterios de aceptación:** cero bloqueadores críticos/altos; I03 instala la
  versión anterior verificable, crea datos, actualiza y conserva el workspace.
- **Verificación:** matriz, hashes, capturas o logs mínimos y resultado fechado.
- **Terminado:** la versión objetivo queda acreditada en Windows limpio.

#### A043 — Preparar la nueva candidata local y documentación

- **Objetivo:** cerrar una candidata coherente y auditable sin publicarla.
- **Dependencias:** A042.
- **Alcance:** `CHANGELOG.md`, `README.md`, `docs/CURRENT_STATE.md`, checklist de
  release, manual afectado, manifiesto y resumen de límites conocidos.
- **Fuera de alcance:** anuncio, publicación, distribución o venta.
- **Criterios de aceptación:** documentación y artefactos comparten versión,
  alcance y hashes; no se promete rendimiento o compatibilidad no demostrados.
- **Verificación:** `git diff --check`, revisión de enlaces/rutas y verificador de
  release en modo solo lectura.
- **Terminado:** candidata local preparada y gates externos claramente pendientes.

#### A044 — Gate humano de publicación

- **Objetivo:** separar el cierre técnico de cualquier acción externa.
- **Dependencias:** A043.
- **Alcance:** revisión jurídica LGPL/Qt WebEngine, licencia propia, estrategia de
  distribución, coste/firma si se considera y autorización expresa de Yeison.
- **Fuera de alcance:** ejecutar automáticamente publicación, firma o compra.
- **Criterios de aceptación:** cada gate tiene responsable y decisión documentada.
- **Terminado:** `AUTORIZADA` o `NO AUTORIZADA`; una candidata técnica completa no
  equivale a permiso de distribución.

## 7. Orden de ejecución recomendado

La secuencia operativa vigente es:

```text
P0-001 ciclo de vida
  -> P0-002 diagnósticos
  -> P0-003 persistencia
  -> P0-004 cancelación
  -> P0-005 reset de estado
  -> P1 dependiente de los P0
  -> A031, cuando CTM quede verde y sus dependencias estén cerradas
  -> packaging final, upgrade y release candidate nuevo
```

Los números del backlog de la sección 9 son prioridades de producto; cada sesión
de implementación deberá concretar un alcance pequeño y registrar su evidencia.
La secuencia `Axxx` siguiente conserva las dependencias históricas del plan y no
desplaza los bloqueadores P0.

```text
A000 -> A001 -> A010 -> A011 -> A012 -> A013
  |       |                              |
  |       +-> A030 -> A031? -> A032 -----+
  +------------------> A021? ------------+
                                         |
                                         v
                           A040 -> A041 -> A042 -> A043 -> A044
```

`A021` y `A031` son condicionales. La dependencia manda sobre el número de
tarea. A040 solo puede iniciarse cuando se hayan cerrado o descartado de forma
explícita todas las ramas que entren en la versión.

## 8. Resultado esperado de cada sesión

Cada tarea debe cerrar con:

1. estado `DONE` o `BLOCKED`;
2. archivos modificados;
3. comprobaciones ejecutadas y resultado real;
4. evidencia o causa concreta del bloqueo;
5. riesgo o pendiente que pasa a la siguiente tarea.

No se iniciará la tarea siguiente en la misma sesión sin autorización expresa.

## 9. Backlog operativo adoptado

Este es el backlog vigente para seguir mejorando el producto. La prioridad es
P0 antes que P1 y P1 antes que P2, salvo una dependencia técnica explícita.
Cada punto debe convertirse en una unidad de trabajo verificable antes de
considerarse cerrado.

### P0 — Bloqueadores y criterio de salida

1. **APP-DEFECT-002 / APP-DEFECT-003 — Ciclo de vida de proyectos.** Corregir
   los errores UI-0001 al cerrar y UI-0003 al reabrir workspaces. Verificar que
   CTM-MiniGTFS-Route-102, CTM-Mallorca-Regression-02 y proyectos históricos se
   reabren sin reimportar. **Estado P0-001:** `DONE` con evidencia manual
   `P0-001-regression-03`: Mini-GTFS se recuperó sin reimportación, completó
   tres ciclos `open → close → open`, desaparecieron `UI-0001` y `UI-0003`, y
   conservó SHA-256 `D4674F72775B05A6E43D6B3B1BD8A732DF051CEE23329AD337DB287296C01182`.
   Mallorca se recuperó con cierre/reapertura correctos, preservando
   `IMPORTED / INVALID / 4` incidencias y SHA-256
   `B4DE215E398AB316C5CBB52672CD2CFC59CA8A4EA6FD68555EECEC67EBC0E7E6`.
2. **DIAG-DEFECT-001 — Diagnósticos útiles.** Incluir `error_code`, `operation`,
   `timestamp`, `exception_type`, `exception_message`, `traceback`, causa
   encadenada cuando existe, versión, estado de aplicación y frames con basename,
   función y línea, sin datos sensibles. **Estado P0-002:** `DONE`, cerrado con
   `P0-002-regression-05`: suite completa `262 PASS`, tests específicos de
   diagnóstico `PASS`, `tools/check.ps1` `PASS`, portable/NSIS/licencias/SBOM y
   smokes `PASS`, regresión manual instalada `PASS` y ZIP diagnóstico con solo
   `gtfs-explorer.log`. La salida no expone rutas absolutas, nombre de usuario,
   project path, secretos ni datos GTFS, y el diálogo no muestra traceback.
   El ejemplo real validado contiene `main_window.py:332` en `_choose_project` y
   `open_project.py:115` en `execute`. La aparente regresión previa fue causada
   por un EXE stale, no por Regression-05. `build_id=''` queda fuera de alcance
   y registrado para A032/versionado.
3. **Persistencia tras cierre/reapertura.** Abrir, comprobar feed, cerrar y
   reabrir verificando métricas, validación, exploración, estados e incidencias.
   **Estado P0-003:** `DONE`, cerrada sin cambios de producción. Evidencia:
   `tests/test_project_persistence_reopen.py` (3 tests añadidos), VALID
   close/reopen `PASS`, INVALID close/reopen `PASS`, reapertura repetida `PASS`,
   frontera real de proceso mediante nuevo intérprete Python `PASS` y coherencia
   `project.json` / DuckDB `PASS`. Tests específicos `3 passed`, batería
   relevante `29 passed`, suite completa `265 passed`, `tools/check.ps1: PASS`
   y `git diff --check: PASS`. No se ha demostrado pérdida real de persistencia
   y no quedan riesgos dentro de P0-003.

   Contrato: DuckDB es la fuente canónica del estado persistente;
   `project.json` es un descriptor/espejo verificable; validación, incidencias y
   estadísticas se reconstruyen desde DuckDB; pestañas, filtros y selecciones
   son estado transitorio de UI fuera de P0-003. El mismatch legacy recuperable
   de `project.json` sigue gobernado por P0-001.
4. **Cancelación real.** Importar el CTM grande y cancelar durante staging,
   normalización o validación; terminar como `CANCELLED`, dejar el workspace
   reutilizable y permitir una nueva importación. **Estado P0-004:** `DONE`,
   cerrado con el artefacto `P0-004-regression-01`. Contrato: se añadió
   `FeedStatus.CANCELLED`; la cancelación voluntaria no es `FAILED`; la primera
   importación cancelada queda `CANCELLED`; una reimportación cancelada conserva
   el último feed consistente `IMPORTED`; la normalización consulta cancelación
   cooperativa por lotes; una validación cancelada no deja resultado parcial
   final; `ImportJobAdapter` espera la finalización y liberación real de
   `QThread`/worker; la doble cancelación es segura; `started_at` y
   `finished_at` siguen `NULL` conforme al contrato global actual.

   Evidencia final: suite completa `268 passed`; `tools/check.ps1`, Ruff, mypy,
   `git diff --check`, portable smoke, smoke gráfico, NSIS y licencias/SBOM:
   `PASS`.

   Evidencia manual: primera importación cancelada con `CANCELLED`, 0 métricas,
   sin validaciones ni inventario parcial y sin `FAILED`; `cancel → close →
   reopen` conserva `CANCELLED`; `cancel → nuevo trabajo` termina `IMPORTED`
   con 1 agencia, 10.000 paradas, 1 ruta, 10.000 viajes y 500.000 eventos;
   la reimportación cancelada conserva el feed `IMPORTED`, métricas,
   inventario y validación previos; y tras cerrar/reabrir mantiene estado,
   métricas, periodo, una única validación y reutilización del proyecto.
5. **UI-STATE-001 — Reset entre proyectos.** No trasladar filtros RAW,
   Validación, ruta/servicio/viaje ni Exportación entre feeds; las preferencias
   visuales sí pueden persistir. **Estado P0-005:** `DONE`, cerrado con
   `P0-005-regression-01` y portable
   `GTFS-Explorer-Portable-0.1.0-P0-005-regression-01-win-x64.zip`.

   SHA-256: `B1C4747328A57642146F2D5A685B65DBCD9F823BEE040AD651AF92E36ACA4098`.

   Evidencia automatizada: tests P0-005 `5 passed`, batería UI `27 passed`,
   suite completa `275 passed`, `tools/check.ps1: PASS`, Ruff `PASS`, mypy
   `PASS`, `git diff --check: PASS` y `NO-ASYNC-LATE-CALLBACK-RISK`. La
   producción ya estaba implementada y no tuvo cambios adicionales durante la
   fase final de regresión.

   Evidencia manual A — A sucio → abrir B: RAW, Validación, Exportación y la
   pestaña `Datos raw` configurados deliberadamente en A no contaminaron B.
   La aplicación volvió a `Proyecto`, B fue el único contexto activo, RAW
   mostró sus propios datos sin `TEST_P0_005_A`, Validación volvió a las
   opciones iniciales, Exportación perdió R1, R2, destino y formato
   personalizado, y no hubo mezcla visual. Resultado: `PASS`.

   Evidencia manual B — close → reopen same project: `Datos raw` no permaneció
   seleccionada; al reabrir B y entrar en Explorar volvió `Rutas, viajes y
   paradas`, los selectores se reconstruyeron desde B, los datos persistieron y
   el estado transitorio no persistió. Resultado: `PASS`.

   Contrato: se resetean filtros y contexto RAW, paginación, filtros y
   selecciones de Validación, contexto y destino de Exportación, IDs de ruta,
   viaje y servicio, selectores y pestaña de Exploración, navegación contextual
   y estado de mapa ligado al feed. Se preservan tema, ajustes visuales,
   configuración global de mapa y paquete de mapa cuando corresponda. No se
   introduce persistencia de filtros ni preferencias nuevas.

### P1 — Funcionalidad, UX, robustez y release

6. **P1-01 — UX-PROJECT-001 — Identidad visible del proyecto — DONE.** La
   identidad global se muestra en status bar y en la página Proyecto con nombre
   y workspace real; el tooltip conserva la ruta completa. `NO_PROJECT` muestra
   `Sin proyecto abierto` y `Workspace: —`. El título de ventana no cambia.

   No se modifican persistencia, `project.json`, DuckDB, IDs, recuperación
   legacy ni el contenido de los diagnósticos. Evidencia automatizada: tests
   específicos `34 passed`, suite completa `277 passed`, `tools/check.ps1:
   PASS`, Ruff `PASS`, mypy `PASS` y `git diff --check: PASS`.

   Evidencia manual `PASS`: `NO_PROJECT`; `open A`; `A → B`; `B → close →
   NO_PROJECT`; `close → reopen A`; y apertura de proyecto inválido desde A,
   con `UI-0001`, estado final `NO_PROJECT` y sin identidad residual o falsa.
   Se observó un `.writer.lock` stale asociado a un PID inexistente; no se
   corrige en P1-01 y queda como evidencia para Robustez de workspace /
   Recuperación segura en P1 posteriores. Observación UX menor: en
   `NO_PROJECT` puede repetirse `Sin proyecto abierto` en la barra inferior;
   queda pendiente para observabilidad/UX.
7. **P1-02 — UX-IMPORT-001/002 — Importaciones informativas — DONE.** El
   contexto runtime muestra nombre del feed activo, fase traducida, progreso,
   proyecto, elapsed monotónico y cancelación visible mientras corresponde, y
   limpia el contexto al terminar. Artefacto: `P1-02-regression-01`. Portable
   SHA-256: `7DC96746BC1BC2D04C3684B16F04F1FC93BE890446D9579618FA1D2AE1AAF6EF`.
   Tests específicos `4 passed`; suite completa `281 passed`;
   `tools/check.ps1`, Ruff, mypy y `git diff --check`: `PASS`.

   La regresión manual con `P0-004-manual-feed-medium.zip` confirmó inicio,
   avance del elapsed, cambio de fases sin reinicio, limpieza y parada tras
   completion, y cancelación limpia conservando el último feed `IMPORTED`, sus
   métricas y validación. `Cancelando…` no se capturó visualmente porque el
   worker terminó antes de la captura; queda cubierto determinísticamente por
   tests y por el contrato P0-004, sin blocker.

   El alcance queda limitado a observabilidad runtime. No hay persistencia de
   duración, ETA, cambio de schema, logging por tick, thread adicional ni
   historial persistente.
8. **P1-03 — Estado visible del feed — DONE.** La página Proyecto separa
   explícitamente importación (`Completada`, `Cancelada`, `Fallida`) y validación
   (`VALID`, `INVALID`, `Sin ejecutar`, `No disponible`), muestra incidencias
   cuando existe una validación y no presenta métricas como completas para
   importaciones canceladas o fallidas. No cambia schema, persistencia,
   semántica GTFS ni el contexto runtime de P1-02. Artefacto:
   `P1-03-regression-01`. Portable SHA-256:
   `43571FAB01F0091480196F403C30122107959AADE2CCAE5D052A836BAB81949F`.
   Tests focales `38 passed`; suite completa `282 passed`;
   `tools/check.ps1`, Ruff, mypy y `git diff --check`: `PASS`.
   La regresión manual A-F confirmó sin feed, `IMPORTED + VALID`,
   `IMPORTED + INVALID`, primera importación `CANCELLED`, fallo técnico
   `FAILED` y reimportación cancelada conservando el feed previo. Se observó
   nuevamente un `writer.lock` stale en un caso controlado; queda fuera de
   P1-03 y registrado para Robustez de workspace / Recuperación segura.
9. **Historial de operaciones — P1-04 DONE.** Auditoría final
   `P1-04-AUDITADO-CERRABLE`: P1-04A/A2/A3/A4, B1, B2, B3 y C están
   `DONE`. La
   importación productiva registra `IMPORT` con una única `DuckDbUnitOfWork`
   compartida por la alta atómica y el cierre terminal atómico. `INVALID` cierra
   la operación como completada y no como fallo; `CANCELLED` y `FAILED`
   conservan sus estados. P1-04A2 corrigió directamente 009: retiró solo las
   tres FKs `detail.operation_id → operations.operation_id` incompatibles con
   DuckDB 1.1.3, conservó las otras seis FKs y las restricciones PK/UNIQUE.
   B1: focales `32 passed`, suite canónica `305 passed`, `tools/check.ps1`,
   Ruff, mypy y `git diff --check` en `PASS`. Un fallo intermitente inicial
   del spike WebEngine del mapa fue `NON-BLOCKER`; la repetición focal y el
   control canónico pasaron. Auditoría Tierra: sin RELEASE BLOCKERS. La suite
   actual de referencia es `320 passed`. El trabajo pendiente de portable/NSIS,
   EXPORT/CANCELLED con exportación async, VALIDATION standalone si se incorpora
   flujo manual y revisión de documentación residual queda como BACKLOG
   independiente, no como pendiente de P1-04.
9. **UX-RAW-001 — Dimensionado inteligente.** Ajustar columnas mediante cabecera
   y muestra visible, con límites, tooltip y scroll horizontal; no usar
   `ResizeToContents` sobre cientos de miles de filas.
10. **Origen RAW exacto.** Desde una incidencia como `stops.txt:95`, abrir el
    archivo, seleccionar la fila fuente y desplazar hasta ella.
11. **UX-EXPLORE-001 — Selectores buscables.** Añadir búsqueda/autocomplete para
    ruta, servicio, viaje y eventualmente parada.
12. **F-MAP-BASEMAP-001 — Basemap híbrido.** Internet: mapa base automático;
    offline con paquete: PMTiles local; offline sin paquete: mapa básico o
    aviso claro, con opción exclusivamente offline y atribución.
13. **Gestión de mapas offline.** Detectar bbox, proponer descarga de zona,
    mostrar tamaño/versión/fecha/almacenamiento y permitir actualizar o borrar;
    no descargar el planeta completo.
14. **UX-EXPORT-002/003 — Nombres previsibles.** Extensiones `.json`, nombre
    final visible para CSV spreadsheet-safe y ruta completa en el éxito.
15. **Ayuda contextual de exportación.** Explicar opciones deshabilitadas según
    formato, por ejemplo bbox solo en GeoJSON o neutralización solo en CSV.
16. **P1-09 — Semántica de “Salida oficial” — RESUELTO.** El Mini-GTFS se
    presenta como salida GTFS Schedule validada localmente y no como publicación
    oficial del proveedor; horarios y campos se muestran con su semántica GTFS.
17. **P1-10 — Líneas completamente vacías — RESUELTO.** Las líneas físicas se
    consumen para conservar `source_row`, pero no se materializan como filas
    lógicas ni alteran los conteos válidos; `,,` continúa sujeto a la validación
    de campos obligatorios.
18. **P1-11 — Extended Route Types — RESUELTO.** El catálogo local incluye los
    81 códigos documentados por Google Transit y acepta `715` y otros conocidos
    sin convertirlos al core; los desconocidos mantienen su validación y RAW.
19. **PACKAGING/I18N-DEFECT-001 — Mojibake NSIS.** Corregir textos como
    `Edición` antes del release público.
20. **Metadata/versionado del EXE — RESUELTO.** Exponer ProductName,
    FileVersion, ProductVersion, CompanyName, copyright y una salida CLI
    identificable desde la identidad canónica del producto.
21. **Versión visible en la aplicación — RESUELTO.** Mostrar versión, build id,
    GTFS 2026-04-27, arquitectura y ubicación de datos en runtime, UI,
    diagnósticos, benchmark y manifests de distribución.
22. **Directorios por defecto.** Usar `%LOCALAPPDATA%\GTFS Explorer\projects`,
    último directorio válido de proyectos/feeds y último destino de exportación.
23. **I18n de diálogos nativos.** Revisar `Yes/No` y cualquier texto mixto.
24. **A031 — Auditoría y pruebas de dependencias.** Reactivar tras dejar CTM
    verde; probar y documentar versiones, compatibilidad, licencias y riesgos,
    sin actualizar por inercia.
25. **Packaging final tras A031.** Rebuild portable/instalador limpio, smoke
    offline y gráfico, checksums, licencias, integridad, instalación,
    desinstalación, upgrade y preservación de proyectos.
26. **Upgrade entre versiones.** Instalar una versión anterior con proyecto real,
    actualizar y confirmar compatibilidad de `project.json` y DuckDB.
27. **Robustez de workspace.** Cubrir proyecto inexistente, descriptor ausente o
    corrupto, DuckDB corrupta/bloqueada, versión futura, permisos y solo lectura
    con mensajes útiles, no UI-000x genéricos.
28. **Recuperación segura.** No modificar proyectos que no puedan abrirse y
    ofrecer diagnóstico, ubicación y backup antes de migrar.
29. **Rendimiento formal.** Instrumentar y registrar baseline de feeds pequeño,
    medio y grande; medir importación y validación con datos reales.
30. **Progreso granular.** Mostrar subfases o filas procesadas cuando sea fiable,
    sin prometer ETA exacto.
31. **Tests E2E del flujo real.** Convertir CTM en fixtures sintéticos para
    `pickup/drop_off=0`, `direction_id` nulo, horas >24, paradas repetidas,
    `parent_station`, Mini-GTFS, cierre/reapertura y cancelación. CTM permanece
    externo al repositorio.
32. **Regression suite de exportación.** Automatizar hashes/estructura JSON,
    GeoJSON, CSV spreadsheet-safe y Mini-GTFS reimportable y válido.
33. **Validación contractual Mini-GTFS.** Garantizar referencias internas de
    rutas, agencia, viajes, shapes, paradas, parent station, calendarios y
    opcionales necesarios.
34. **Presentación de validación.** Añadir recuentos por regla, agrupación,
    ordenación y navegación RAW; explicar claramente el límite de 10.000.
35. **Estado visible del feed — DONE.** Mostrar claramente `IMPORTED / VALID`,
    `IMPORTED / INVALID`, `FAILED` y `CANCELLED`; cierre documentado como
    P1-03 con `P1-03-regression-01`.
36. **Accesibilidad y teclado.** Revisar foco, tab order, atajos, tablas,
    tamaños mínimos y contraste, especialmente en filtros y exportación.
37. **Ayuda/documentación final.** Cubrir proyectos, importación, VALID/INVALID,
    horas >24, RAW, exportaciones, Mini-GTFS, mapas, ubicación, backups,
    privacidad y troubleshooting.
38. **Privacidad/offline-first con mapas.** Mantener feed y workspace locales,
    explicar las solicitudes de tiles, no subir el feed y ofrecer modo offline.
39. **Release candidate real.** Crear un RC nuevo cuando el backlog crítico esté
    verde; no reutilizar `CTM-001-regression-02`.

### P0 final — Criterio de salida 1.0

40. No publicar hasta que no existan P0 abiertos, la suite esté verde, portable
    e instalador superen smoke, los proyectos cierren/reabran, cancelación
    funcione, Mini-GTFS reimporte, los diagnósticos sean útiles, CTM termine con
    las cuatro incidencias legítimas y sin falsos positivos, el packaging no
    tenga mojibake y la versión sea identificable.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
