# DEC-016 — T070 GO con servidor loopback efímero protegido

Fecha: 2026-08-13

Estado: Aceptada

## Decisión preservada

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

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
