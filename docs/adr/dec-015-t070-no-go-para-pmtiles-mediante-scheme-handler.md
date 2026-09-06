# DEC-015 — T070 NO-GO para PMTiles mediante scheme handler

Fecha: 2026-08-13

Estado: Superada por DEC-016

## Decisión preservada

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

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
