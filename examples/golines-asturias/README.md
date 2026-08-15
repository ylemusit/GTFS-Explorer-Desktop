# Ejemplo local GoLines Asturias

Este kit permite comprobar conjuntamente la importación GTFS, las consultas,
las rutas, las paradas y el mapa base offline de GTFS Explorer Desktop.

## Contenido generado

- `golines-asturias-demo.gtfs.zip`: seis variantes entre Oviedo, Gijón y
  Avilés, dos viajes de muestra por variante, horarios, paradas y shapes.
- `map-package/`: mapa vectorial PMTiles de Asturias con carreteras, agua,
  usos del suelo y edificios, preparado para el contrato v1 de GTFS Explorer.
- `example-manifest.json` y `SHA256SUMS.txt`: procedencia, alcance y hashes.

Los viajes y geometrías son reconstrucciones técnicas procedentes del catálogo
local de GoLines. No constituyen un GTFS oficial ni datos operativos certificados
por ALSA o CENTROBUS. El catálogo fuente no dispone en el repositorio de una
licencia específica de redistribución: el ZIP generado es únicamente para
evaluación local hasta obtener autorización o sustituirlo por datos abiertos.

El mapa procede de Protomaps Basemap, con datos OpenStreetMap y Natural Earth.
Debe conservar la atribución visible `© OpenStreetMap contributors` y la
licencia declarada en `map-package/package.json`.

## Generación

Desde la raíz de GTFS Explorer Desktop:

```powershell
.\.venv\Scripts\python.exe tools\build_golines_example.py `
  --golines-root "C:\ruta\a\GoLines" `
  --output examples\golines-asturias\generated `
  --pmtiles-bin "C:\ruta\a\GoLines\tools\pmtiles.exe"
```

El destino debe estar vacío o no existir. Los artefactos generados se excluyen
de Git por su tamaño y por la limitación de redistribución del catálogo.

## Prueba manual

1. Crea un proyecto nuevo e importa `golines-asturias-demo.gtfs.zip`.
2. Abre **Ajustes visuales** y selecciona la carpeta `map-package`.
3. En **Explorar**, selecciona OG1, GO1, OA1, AO1, GA1 o AG1 y un viaje.
4. Comprueba que aparecen simultáneamente mapa, línea, paradas y horarios.

Propietario y autor del ejemplo: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
