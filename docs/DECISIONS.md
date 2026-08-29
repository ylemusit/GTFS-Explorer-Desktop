# Decisiones del proyecto

Última actualización: 2026-08-13

## DEC-001 — Aplicación Windows con PySide6/Qt Widgets

Fecha: 2026-08-11

Estado: Aceptada, validada por el smoke T001

Se utilizará Python x64, PySide6 y Qt Widgets. Streamlit queda limitado a prototipos externos y no forma parte del producto final. Motivo: UI nativa, ejecución sin navegador externo y empaquetado portable. Revisar solo si T001 demuestra incompatibilidad bloqueante.

## DEC-013 — Versiones fijadas tras smoke T001

Fecha: 2026-08-12

Estado: Aceptada

La combinación reproducible validada en Windows 11 x64 es Python 3.12.10, PySide6 6.8.2.1, DuckDB 1.1.3, Shapely 2.0.7 y Nuitka 2.6.9, con `uv.lock` como lockfile. `QWebEngineView` se obtiene mediante los paquetes de PySide6; no existe un paquete independiente `PySide6-WebEngine` en PyPI para esta versión.

## DEC-002 — DuckDB como motor único por proyecto

Fecha: 2026-08-11

Estado: Aceptada

DuckDB persistirá staging, modelo tipado y derivados. No habrá servidor ni ORM. Se aplicarán paginación, límites de memoria/temporales y conexión por job/thread. Revisar si benchmarks reproducibles incumplen los límites de v1.0.

## DEC-003 — Doble representación: staging fiel y modelo tipado

Fecha: 2026-08-11

Estado: Aceptada

Los lexemas de origen y columnas extra se conservan; las consultas usan tablas tipadas. Una conversión inválida genera un problema, no una corrección o pérdida silenciosa.

## DEC-004 — Sin Pandas, Polars, GeoPandas ni Pydantic obligatorios

Fecha: 2026-08-11

Estado: Aceptada

DuckDB, lotes Python, `dataclasses` y Shapely cubren el alcance inicial con menor peso. Añadir una dependencia solo si un perfil o contrato concreto lo exige.

## DEC-005 — MapLibre local y PMTiles opcional

Fecha: 2026-08-11

Estado: Aceptada, revisada por DEC-016

Qt WebEngine alojará MapLibre/PMTiles JS local y QWebChannel será el bridge. El mapa funciona con fondo vacío y no descarga teselas OSM para offline. DEC-016 sustituye el scheme handler inicialmente previsto por un loopback protegido que superó T070.

## DEC-015 — T070 NO-GO para PMTiles mediante scheme handler

Fecha: 2026-08-13

Estado: Superada por DEC-016

El spike aislado en `spikes/map_webengine/` ha demostrado que `gtfs-spike://`
carga HTML local con CSP en Qt WebEngine. No ha demostrado QWebChannel: el
recurso `qrc:///qtwebchannel/qwebchannel.js` no está disponible en el entorno
fijado. Más importante, la API pública de `QWebEngineUrlRequestJob` permite
leer `Range` y añadir cabeceras, pero no emitir el estado HTTP `206 Partial
Content`, condición del servicio de rangos PMTiles. Por tanto T070 concluye
NO-GO: no se iniciarán T071--T075 ni se integrará un mapa en producción.

Una alternativa basada en loopback exclusivamente local requerirá una decisión
nueva, un modelo de seguridad y un spike independiente; no está autorizada por
esta decisión.

## DEC-016 — T070 GO con servidor loopback efímero protegido

Fecha: 2026-08-13

Estado: Aceptada

Se sustituye el scheme handler por un servidor HTTP efímero enlazado únicamente
a `127.0.0.1`. Usa puerto y token aleatorios, valida `Host`, admite `GET`/`HEAD`
y únicamente el `OPTIONS` de preflight para orígenes locales `null`/`file://`,
expone una lista cerrada de assets y PMTiles, no registra el token
y termina con la vista. La CSP solo permite el mismo origen, QWebChannel y los
workers/imágenes locales imprescindibles. El interceptor WebEngine bloquea toda
URL exterior.

El spike fijado en MapLibre GL JS 6.3.0, PMTiles 4.5.0 y esbuild 0.28.2 demuestra:

- PMTiles v3 real servido con `206 Partial Content` y `Content-Range`;
- línea y parada renderizadas por MapLibre sin solicitudes externas;
- QWebChannel bidireccional (`python:js-ping`);
- ejecución standalone Nuitka/PySide6 en Windows 11 x64: 2,175 ms para arranque
  y smoke, 309.92 MiB antes de optimización.

El render standalone bajo `QT_QPA_PLATFORM=offscreen` pierde el contexto D3D;
la sesión gráfica normal completa el smoke. Esta limitación afecta al método de
prueba headless, no al transporte aceptado. T070 pasa a GO y habilita T071.

## DEC-018 — P1-16 política offline-first de mapas

Fecha: 2026-08-26

Estado: Aceptada

GTFS Explorer mantiene `AUTO` como preferencia inicial de sesión: usa primero
un paquete PMTiles local validado y, fuera de cobertura, el proveedor online
interactivo configurado. `OFFLINE` no permite orígenes remotos. `ONLINE` es una
autorización explícita para el proveedor actual OpenStreetMap Standard. Si ese
proveedor no está disponible, la vista presenta `no disponible` sin convertir
el modo en `OFFLINE`; sin paquete local ni proveedor disponible se mantiene el
fondo neutro.

La vista WebEngine usa un interceptor de allowlist. Solo se permiten los
recursos `file:///`, `qrc:///` y el servidor `127.0.0.1` efímero del paquete
validado; no se registran URLs bloqueadas. El servidor loopback conserva el
token aleatorio temporal, el control de `Host`, la lista cerrada de archivos y
los rangos PMTiles establecidos en DEC-016.

No se añaden proveedores, CDN, API keys, tokens persistentes, descargas,
tracking, analytics ni telemetría. Una futura URL de tesela externa deberá
contener únicamente `z/x/y`, sin query, credenciales, bbox o identificadores
GTFS. La gestión de caché y paquetes offline queda para P1-18; la intermitencia
del spike WebEngine, si reaparece sin romper este contrato, queda como
`BACKLOG`.

## DEC-019 — P1-17 convivencia de basemap online y overlay GTFS local

Fecha: 2026-08-26

Estado: Aceptada

La vista separa conceptualmente `Basemap`, `Overlay GTFS` y `Política de fuente`.
El overlay (`routes`, `shapes` y `stops`) permanece local y no se reconstruye al
cambiar de basemap. El paquete PMTiles conserva sus bounds declarados en el
manifiesto; la cobertura se decide comparándolos con la envolvente del overlay,
sin escanear teselas. La presencia de un fichero PMTiles no se interpreta como
cobertura mundial.

`AUTO` usa PMTiles cuando cubre el overlay completo y, fuera de cobertura o sin
paquete compatible, usa el proveedor online central. `OFFLINE` mantiene cero
requests remotos y muestra el overlay sobre fondo neutro cuando no hay cobertura.
`ONLINE` fuerza el proveedor remoto, aunque exista PMTiles; si falla por red,
HTTP, timeout lógico, tesela ausente o estilo/fuente, muestra estado neutral sin
convertirse en `OFFLINE`. La atribución visible depende de la fuente activa.

El proveedor inicial es `OpenStreetMap Standard`, mediante
`https://tile.openstreetmap.org/{z}/{x}/{y}.png`, solo para uso interactivo y
con `© OpenStreetMap contributors`. El allowlist de WebEngine permite únicamente
recursos locales, loopback validado y el hostname del proveedor configurado. La
petición externa puede revelar IP, headers normales, `z/x/y` y zona aproximada,
pero nunca IDs, nombres, shapes, GeoJSON, paths, workspace, historial, selección
ni tokens del GTFS Explorer.

P1-17 no implementa descarga, prefetch, crawler, caché offline adicional,
conversión a PMTiles, catálogo regional ni selección de múltiples proveedores.
La gestión inteligente de paquetes offline queda para P1-18.

## DEC-006 — Validación trazable sin puntuación numérica

Fecha: 2026-08-11

Estado: Aceptada

Se emitirán FATAL/ERROR/WARNING/NOTICE con código y origen. MobilityData será integración opcional y separada. Una nota 0–100 queda prohibida hasta existir ponderación validada con usuarios y expertos.

## DEC-007 — v1.0 se limita a GTFS Schedule

Fecha: 2026-08-11

Estado: Aceptada

GTFS Realtime y simulador quedan después de v1.0. La arquitectura conserva puntos de extensión, pero no se implementan anticipadamente.

## DEC-008 — Exportaciones públicas versionadas

Fecha: 2026-08-11

Estado: Aceptada

JSON dispone de JSON Schema y SemVer; GeoJSON sigue RFC 7946; CSV fiel se separa del modo Excel-safe; Mini-GTFS exige cierre, reimportación y validación. Cambios breaking incrementan versión mayor.

## DEC-009 — Portable standalone y NSIS

Fecha: 2026-08-11

Estado: Aceptada y demostrada por T091/T092

El portable será una carpeta `standalone`, no onefile. `pyside6-deploy`/Nuitka es el build objetivo. NSIS es el instalador gratuito base. Firma de código es opcional y requiere autorización de coste.

## DEC-010 — Privacidad local y red opt-in

Fecha: 2026-08-11

Estado: Aceptada

No habrá cuentas, telemetría, subida de feeds ni tráfico automático. Logs minimizan contenido y rutas. Cualquier futura red/Realtime exige decisión nueva y controles de secretos/consentimiento.

## DEC-011 — Coste obligatorio de licencias/servicios: 0 €

Fecha: 2026-08-11

Estado: Aceptada como objetivo

El MVP y v1.0 deben poder construirse con stack abierto, mapas opcionales y release sin firma. Tiempo, hardware, electricidad, almacenamiento, ancho de banda y cumplimiento no se consideran gratuitos. Ningún gasto se autoriza por esta decisión.

## DEC-012 — Una tarea del plan por chat

Fecha: 2026-08-11

Estado: Aceptada

El agente ejecuta una ficha `Txxx`, comprueba dependencias y se detiene al terminar. Se evita que un modelo de razonamiento bajo amplíe el alcance, mezcle fases o cree contratos incompatibles.

## DEC-014 — Terra Medio para el piloto del orquestador

Fecha: 2026-08-12

Estado: Aceptada para evaluación

El ejecutor del piloto T013/T014/T020 será `gpt-5.6-terra` con razonamiento `medium`. La selección prioriza el equilibrio entre capacidad y coste para tareas de implementación con contratos, pruebas y decisiones técnicas. El modelo queda registrado en `docs/TASK_STATUS.json` y cada ejecución conserva evidencia propia. Revisar la decisión con los resultados del piloto; los bloqueos ambientales no se atribuirán al modelo.

## DEC-017 — Alcance y versión objetivo de la actualización posterior a rc1

Fecha: 2026-08-18

Estado: Aceptada para la actualización

La siguiente candidata local se denominará `0.1.0-rc2`. No es una publicación,
una autorización de distribución ni una versión final. Mantiene la versión base
`0.1.0` porque el alcance previsto no modifica contratos públicos de
importación, validación o exportación; en particular, respeta DEC-008 y no
requiere incrementar la versión mayor del bundle JSON.

El alcance candidato comprende exclusivamente los cambios que superen sus
tareas y pruebas: identidad y créditos coherentes (A010), presentación de
inicio accesible y no bloqueante (A011), estados vacíos del resumen (A012),
actualización del instalador por usuario (A013) y, solo si se aprueba tras su
auditoría, el mantenimiento técnico de A030--A032. El feed
`examples/ctm-mallorca-es.zip` queda excluido del alcance de la candidata, de
los artefactos y de cualquier recorrido de ejemplo; no se planifica auditarlo
ni incorporarlo.

Los cambios locales inventariados en A000 no se incorporan por esta decisión:
cada uno sigue condicionado a los criterios de aceptación de su tarea. La
fuente canónica y los nombres de artefactos se actualizarán únicamente en A032,
después de cerrar el alcance; hasta entonces `pyproject.toml` y
`gtfs_explorer.__version__` permanecen sin cambios.

El rollback consiste en no generar ni sustituir artefactos `rc1`: si fallan las
pruebas, el build, el smoke o el upgrade N-1 de la actualización, la candidata
`rc2` no se prepara y la corrección se limita a la tarea que haya fallado antes
de reconstruir artefactos nuevos.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
