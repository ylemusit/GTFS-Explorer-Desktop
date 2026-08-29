# Runbook: política híbrida y paquetes de mapa offline

Última actualización: 2026-08-26

## Principio

GTFS Explorer es offline-first. El overlay GTFS (`routes`, `shapes` y `stops`)
siempre se mantiene local y es independiente del mapa base. El mapa base puede
ser un paquete PMTiles local validado, el proveedor online interactivo configurado
por el producto o un fondo neutro. P1-17 no descarga mapas para uso offline.

## Política runtime P1-17

La preferencia global de la sesión admite tres modos:

- `AUTO`: usa PMTiles cuando los límites declarados del paquete cubren el
  overlay completo. Si el overlay queda fuera de esos límites, o no hay paquete
  compatible, usa el proveedor online explícito.
- `OFFLINE`: usa PMTiles únicamente cuando hay cobertura local compatible y
  bloquea siempre los orígenes exteriores. Fuera de cobertura mantiene el
  overlay sobre un fondo neutro y muestra `Sin cobertura offline`.
- `ONLINE`: usa explícitamente el proveedor remoto aunque exista PMTiles. El
  overlay continúa siendo completamente local.

El valor inicial es `AUTO`. La cobertura se decide por la envolvente del overlay
y el `bbox`/bounds del manifiesto PMTiles; no se escanean teselas individuales.
La decisión no cambia por mover la cámara, evitando oscilaciones junto a un
límite geográfico. El indicador visible usa, según el estado, `Mapa · Offline ·
PMTiles`, `Mapa · Online · OpenStreetMap`, `Mapa · Sin cobertura offline` o
`Mapa · Online no disponible`.

### Orígenes de red inventariados

1. `file:///...`: HTML, CSS, JavaScript y worker MapLibre locales, resueltos
   desde el paquete de la aplicación. No es una petición de red.
2. `qrc:///qtwebchannel/qwebchannel.js`: recurso interno de Qt WebEngine. No
   es una petición exterior.
3. `http://127.0.0.1:<puerto-efímero>/<token-efímero>/...`: servidor local
   temporal para `style.json`, `basemap.pmtiles` y los activos comprobados del
   paquete. Solo enlaza loopback, valida `Host`, usa allowlist y soporta rangos
   PMTiles. El token no se registra ni se persiste.
4. `https://tile.openstreetmap.org/{z}/{x}/{y}.png`: teselas raster de
   `OpenStreetMap Standard`, solo para uso interactivo cuando la fuente activa
   es `ONLINE` o `AUTO` fuera de cobertura local. El hostname es el único origen
   remoto allowlisted por el proveedor actual.

El estilo MapLibre, el bridge QWebChannel, el worker y el PMTiles son recursos
locales. No se carga un estilo, sprite, glyph, CDN ni otro origen remoto. Las
URLs de licencia o procedencia presentes en manifiestos son metadatos y no se
cargan durante la exploración. El interceptor de Qt bloquea cualquier URL que no
sea un recurso interno, el loopback activo o el origen remoto explícitamente
permitido; en `OFFLINE` bloquea todo origen remoto.

### Privacidad y peticiones externas

El proveedor online puede conocer la IP/conexión, las coordenadas `z/x/y`, la
zona aproximada visualizada y headers HTTP normales. El contenido GTFS,
`route_id`, `trip_id`, `stop_id`, nombres internos, shapes, GeoJSON, paths,
workspace, historial, nombres de proyecto, selección y datos de usuario no se
incluyen en peticiones externas. La plantilla de teselas solo admite `z`, `x` e
`y` en la ruta; rechaza query strings, fragmentos, credenciales, tokens, API
keys, bbox y contexto GTFS.

No existe tracking, analytics ni telemetría. El interceptor solo cuenta
bloqueos en memoria y no conserva las URLs bloqueadas.

### Sin Internet, fallback y caché

La red no participa en la importación ni en la exploración GTFS. Sin Internet,
el mapa neutro y las capas de ruta/paradas locales siguen disponibles. Si el
proveedor falla por DNS, HTTP, timeout, tesela ausente o error de estilo/fuente,
la aplicación no se cae: muestra `Mapa · Online no disponible`, conserva el
overlay y no cambia automáticamente a `OFFLINE`. El fallback de PMTiles solo
pertenece a la decisión `AUTO` cuando hay cobertura local.

No se crea un sistema nuevo de caché. Se conserva el comportamiento actual:
la caché de viewport acotada de la vista y la caché en memoria del motor
MapLibre; el servidor loopback responde con `Cache-Control: no-store`. No hay
downloader, crawler, prefetch, guardado de regiones, caché offline nueva ni
conversión de teselas a PMTiles.

## Proveedor online actual

El proveedor central es `OpenStreetMap Standard`, sin API key ni token, con
atribución visible `© OpenStreetMap contributors`. Su uso es interactivo: no hay
bulk download, prefetch offline ni construcción de PMTiles desde sus teselas.
`ONLINE` implica requests de teselas; no implica que el proveedor desconozca la
zona visualizada.

## P1-18 — datasets y basemaps gestionados

Un PMTiles técnicamente válido se registra como `VALID_DATASET`; no se promete
que sea un mapa base. El header PMTiles v3 clasifica `VECTOR`, `RASTER` (PNG,
JPEG o WebP) o `UNKNOWN`, sin inferirlo por la extensión.

- Un raster compatible obtiene el perfil local mínimo `builtin-raster-v1` y es
  `RENDERABLE_BASEMAP`.
- Un vector solo es renderizable si llega como bundle con `MapStyleProfile`:
  `style_id`, versión, perfil de teselas, `style.json` y assets requeridos.
  Un vector sin ese perfil queda instalado con estado `Sin estilo compatible`;
  no se trata como corrupto ni se recomienda en AUTO/OFFLINE.
- El bundle se instala como `maps/packages/<package_id>/<version>/` y contiene
  `map.pmtiles`, `package.json`, `style.json` y los assets declarados. Se copia
  a staging, se valida completo, se publica y solo después se actualiza el
  índice atómico. El índice contiene paths relativos.

El estilo MapLibre debe ser v8, usar exclusivamente la fuente `basemap` que
apunta al PMTiles declarado y no puede usar `http`, `https`, `//` ni `file://`.
Glyphs, sprites y style externos quedan bloqueados; los assets necesarios se
declaran, se incluyen y se protegen con SHA-256. Así OFFLINE mantiene cero
peticiones externas y el loopback solo sirve la allowlist del bundle.

El panel **Mapas offline** lista nombre, tipo, cobertura, tamaño, estado y
fuente/versión. Permite importar y eliminar con confirmación. Al eliminar el
activo se desactiva primero; AUTO vuelve a resolver o pasa al proveedor online
y OFFLINE queda neutral cuando no hay cobertura. Nunca se modifica GTFS,
proyectos ni exportaciones.

El catálogo puede descargar PMTiles con checksum y cancelación, pero no puede
declarar `offline_ready` sin bundle de estilo. BBOX_EXTRACT, catálogo público,
perfil Protomaps y sus glyphs/sprites completos quedan en BACKLOG.

## Preparación histórica de P1-18

La arquitectura deja disponible el flujo futuro `importar GTFS → calcular bounds
→ detectar región → comprobar PMTiles instalado → recomendar paquete compatible`,
pero no crea catálogo de regiones ni downloader. La gestión y descarga de
paquetes offline pertenece a P1-18.

No ejecutes este proceso ni distribuyas su resultado hasta que el responsable
de la fuente haya confirmado por escrito que permite la extracción regional,
el uso local y la redistribución prevista. La atribución y la licencia no son
una autorización: son metadatos obligatorios del paquete.

## Requisitos

- Python 3.12 del entorno del repositorio.
- `pmtiles` instalado localmente y fijado en el registro de la ejecución. El
  wrapper conserva literalmente la salida de `pmtiles --version` en el
  manifiesto.
- Un PMTiles de origen que el responsable haya autorizado, o una URL aprobada
  explícitamente para esa extracción.
- `style.json` MapLibre v8 y, si los usa, assets locales. No puede contener
  URLs `http`, `https` ni referencias CDN.

El mapa regional generado no se añade a Git. Guarda también la evidencia de
licencia fuera del paquete si incluye datos personales o condiciones privadas.

## Crear y validar

Primero, revisa la licencia aplicable y completa la atribución exacta de la
fuente. Para una fuente local autorizada:

```powershell
python tools/build_map_package.py `
  --source D:\fuentes-autorizadas\region.pmtiles `
  --source-reference "Fuente regional autorizada, revisión 2026-08" `
  --output D:\paquetes-mapa\asturias `
  --bbox="-7.2,42.8,-4.4,43.8" `
  --min-zoom 0 --max-zoom 14 `
  --style D:\estilos\style.json --assets D:\estilos\assets `
  --license "ODbL-1.0" `
  --license-url "https://opendatacommons.org/licenses/odbl/" `
  --attribution "© OpenStreetMap contributors"
```

Para una URL remota que ya haya sido revisada y autorizada, añade
`--confirm-source-authorized`. Sin esa confirmación el comando falla antes de
invocar `pmtiles`. Esta protección no sustituye la revisión humana de la
licencia.

El wrapper ejecuta, en este orden, `pmtiles extract` y `pmtiles verify`; solo
publica la carpeta al terminar ambos. `package.json` registra una referencia a la fuente,
versión de CLI, licencia, atribución, bbox, zooms y SHA-256 de `basemap.pmtiles`,
`style.json` y assets copiados. No guarda la ruta local de origen. El contrato formal está en
`schemas/map_package/1.0.0/schema.json`.

En la aplicación, abre Ajustes y selecciona la carpeta resultante. Si falla
una verificación o se altera un archivo, el paquete se rechaza y no se inicia
ningún tráfico de red.

## Ejemplo local de Asturias

`examples/golines-asturias/` contiene el estilo, el generador y las instrucciones
para crear un kit conjunto GTFS + mapa usando los activos locales de GoLines. El
directorio `generated/map-package` puede seleccionarse directamente en Ajustes
visuales y `generated/golines-asturias-demo.gtfs.zip` se importa como feed.

La comprobación visual automatizada exige mapa base, línea y paradas simultáneas.
El conjunto de horarios derivado de CENTROBUS es solo para evaluación local y no
debe redistribuirse hasta confirmar el permiso aplicable.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
