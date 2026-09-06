# DEC-019 — P1-17 convivencia de basemap online y overlay GTFS local

Fecha: 2026-08-26

Estado: Aceptada

## Decisión preservada

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

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
