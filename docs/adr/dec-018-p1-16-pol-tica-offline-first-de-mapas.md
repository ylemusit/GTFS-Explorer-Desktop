# DEC-018 — P1-16 política offline-first de mapas

Fecha: 2026-08-26

Estado: Aceptada

## Decisión preservada

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

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
