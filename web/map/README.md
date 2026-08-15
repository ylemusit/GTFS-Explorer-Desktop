# Recursos web del mapa

Este directorio es exclusivamente de desarrollo. Node y npm no forman parte de
la aplicación distribuida: el resultado son cuatro ficheros estáticos copiados
a `web/map/qt_resources/`, que el empaquetador Qt incorpora como recursos.

## Build reproducible y sin red

Con Node 24.x y npm 11.x, preparar una caché en el job o imagen de CI:

```powershell
Set-Location web/map
npm ci
Set-Location ../..
python tools/build_map_assets.py
```

Para una repetición offline, la caché ya preparada y el lock son obligatorios:

```powershell
python tools/build_map_assets.py --offline
```

El script ejecuta `npm ci --offline`, genera el bundle, copia los recursos Qt,
actualiza sus hashes SHA-256 y rechaza referencias remotas. El escaneo permite
solo cuatro URLs de documentación inertes incluidas por las librerías bloqueadas
(MapLibre, PMTiles y el espacio de nombres SVG); cualquier URL nueva falla el build.
El manifiesto registra las versiones de Node/npm: sus hashes se comparan solo
entre builds con el mismo lock y la misma versión de esbuild/Node.

No se deben añadir CDN, estilos, sprites, fuentes o teselas remotas. El bridge
posterior solo podrá proporcionar URLs loopback locales y PMTiles locales.
