# Dependencias del bundle web de mapa

El lock `web/map/package-lock.json` fija estas versiones. Los recursos
distribuidos incorporan MapLibre GL JS y PMTiles; esbuild solo se usa en el
entorno de desarrollo.

| Dependencia | Versión | Licencia declarada |
| --- | --- | --- |
| maplibre-gl | 6.3.0 | BSD-3-Clause (incluye avisos de terceros) |
| pmtiles | 4.5.0 | BSD-3-Clause |
| esbuild | 0.28.2 | MIT (solo build) |

`maplibre-gl-6.3.0.txt` se copia desde el paquete bloqueado durante el build y
debe distribuirse junto con los recursos. PMTiles declara BSD-3-Clause en su
metadata publicada; T093 consolidará el SBOM y las atribuciones completas de
todas las dependencias transitivas.
