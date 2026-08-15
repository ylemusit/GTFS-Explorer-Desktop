# Runbook: paquetes de mapa offline

Última actualización: 2026-08-13

## Principio

GTFS Explorer no descarga teselas de OpenStreetMap ni de ningún proveedor. El
mapa base es opcional y solo abre un paquete local que supera la validación de
hashes, PMTiles v3, estilo local y atribución. La ausencia de paquete conserva
el fondo neutro de la aplicación.

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
