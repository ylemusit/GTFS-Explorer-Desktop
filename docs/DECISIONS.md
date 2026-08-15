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

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
