# Estado actual del proyecto

Última actualización: 2026-08-15

## Estado

T015_COMPLETED — T016_COMPLETED — T017_COMPLETED — T018_COMPLETED — T020_COMPLETED — T021_COMPLETED — T022_COMPLETED — T023_COMPLETED — T024_COMPLETED — T030_COMPLETED — T031_COMPLETED — T032_COMPLETED — T033_COMPLETED — T034_COMPLETED — T035_COMPLETED — T040_COMPLETED — T041_COMPLETED — T042_COMPLETED — T043_COMPLETED — T044_COMPLETED — T045_COMPLETED — T046_COMPLETED — T050_COMPLETED — T051_COMPLETED — T052_COMPLETED — T053_COMPLETED — T054_COMPLETED — T057_COMPLETED — T060_COMPLETED — T061_COMPLETED — T062_COMPLETED — T063_COMPLETED — T064_COMPLETED — T073_COMPLETED — T074_COMPLETED — T075_COMPLETED — T076_COMPLETED — T080_COMPLETED — T081_COMPLETED — T090_COMPLETED — T091_COMPLETED — T092_COMPLETED — T093_COMPLETED — T094_COMPLETED — T095_COMPLETED — T096_COMPLETED

## Objetivo actual

Construir GTFS Explorer Desktop como aplicación Windows x64, portable y offline-first para importar, explorar, validar, visualizar y exportar GTFS Schedule sin exigir herramientas de desarrollo al usuario final.

## Hechos comprobados

- El repositorio contiene el esqueleto ejecutable pre-alpha, sus tests de capas/entrypoint y la documentación de definición.
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
- UI PySide6, mapas MapLibre sin base y PMTiles local opcional.
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
- T096 está completada: la RC local `0.1.0-rc1` reúne changelog, checklist, manifiesto de release, SBOM, avisos y hashes verificados de portable e instalador. No se ha publicado ni distribuido; la autorización expresa y la revisión jurídica LGPL siguen pendientes.
- No hay ninguna tarea del orquestador en ejecución.

## Próximo paso autorizado por el plan

- El plan v1.0 no tiene más tareas ejecutables. La siguiente ficha futura es F100 — Motor de simulación, que requiere iniciar una nueva fase después de v1.0. La publicación o distribución de la RC seguirá requiriendo autorización explícita de Yeison.

## Problemas y decisiones abiertas

- El smoke de T001 se ha validado en Windows 11 x64; el Windows mínimo exacto de producto queda pendiente de la validación de compatibilidad prevista en el plan.
- El servidor loopback del mapa deberá conservar en producción las restricciones demostradas en DEC-016; no se autoriza escuchar en LAN/WAN ni servir rutas arbitrarias.
- Falta validar usuarios, comprador y disposición a pagar antes de gastos o publicación.
- Firma de código, mapas comerciales y licencia Qt comercial son opcionales y requieren autorización.

## Para retomar el proyecto

1. Lee `../AGENTS.md`.
2. Lee este documento.
3. No inicies F100 sin una nueva autorización de fase; la RC local no autoriza publicación ni distribución.
4. Lee únicamente la ficha autorizada, sus dependencias y archivos relacionados.
5. No uses el chat histórico como fuente normativa frente al código, tests o referencia oficial GTFS.

El orquestador se controla con `tools/plan_orchestrator.ps1`; su registro de estados es `docs/TASK_STATUS.json` y los bloqueos se documentan en `docs/TAREAS_PENDIENTES.md`.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
