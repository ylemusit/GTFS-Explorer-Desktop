# A030 — Auditoría de versiones y compatibilidad

Fecha de cierre: 2026-08-23  
Alcance: auditoría; no se modifican dependencias, lockfiles ni artefactos.

| Componente | Versión fijada | Versión local | Candidato oficial consultado | Decisión |
|---|---:|---:|---:|---|
| Python | 3.12.x | 3.12.10 | 3.12 mantenido por compatibilidad x64 | MANTENER |
| PySide6 / Qt WebEngine | 6.8.2.1 | 6.8.2.1 | 6.11.2 en PyPI | PROBAR |
| DuckDB | 1.1.3 | 1.1.3 | 1.5.5 en PyPI | PROBAR |
| Shapely | 2.0.7 | 2.0.7 | 2.1.2 en PyPI | PROBAR |
| Nuitka | 2.6.9 | no comprobado en smoke | 4.1.3 en PyPI | PROBAR |
| MapLibre GL JS | 6.3.0 | 6.3.0 en lockfile | 6.5.0 en npm | PROBAR |
| PMTiles JS | 4.5.0 | 4.5.0 en lockfile | 4.5.0 en npm | MANTENER |
| esbuild | 0.28.2 | 0.28.2 en lockfile | 0.28.2 en npm | MANTENER |
| Node.js / npm | no fijados como runtime | 24.11.0 / 11.6.1 | toolchain local | PROBAR |
| NSIS | 3.x documentado | `makensis` no está en PATH | instalador oficial NSIS | PROBAR |
| Herramientas Python | mypy 1.15.0, pytest 8.3.5, ruff 0.9.10 | fijadas | versiones más nuevas en PyPI | MANTENER |
| GTFS Schedule | registro `2026-04-27` | registro validado | referencia oficial actual | PROBAR |

## Resultado

No se actualiza ningún componente dentro de A030. Las versiones más nuevas no
se adoptan por inercia: PySide6/Qt WebEngine, DuckDB, Shapely, Nuitka, MapLibre,
Node/NSIS y el cotejo GTFS requieren pruebas acotadas. PMTiles, esbuild, Python y
las herramientas de desarrollo se mantienen en esta candidata.

Riesgos principales para A031:

- PySide6/Qt WebEngine puede afectar QWebChannel, MapLibre, WebEngine y la
  revisión jurídica LGPL/GPL.
- DuckDB debe probar apertura y migración de workspaces existentes, staging,
  recuperación, cancelación y exportaciones.
- Shapely debe repetir las pruebas geométricas y de empaquetado.
- Nuitka debe repetir el build standalone Windows y el smoke de portable.
- MapLibre debe reconstruir el bundle y repetir las pruebas de WebEngine,
  loopback, CSP y PMTiles.
- NSIS no puede darse por validado hasta disponer de `makensis` y compilar el
  instalador.
- El cotejo GTFS debe conservar la semántica de horas superiores a `24:00:00` y
  las condiciones entre `calendar.txt` y `calendar_dates.txt`.

A031 queda condicionada a autorización de Yeison y se ejecutará como una sesión
por componente o grupo inseparable, con rollback y pruebas específicas. A032 no
se inicia hasta cerrar A031 o documentar que todas las versiones se mantienen.

Fuentes oficiales consultadas:

- https://pypi.org/project/duckdb/
- https://pypi.org/project/PySide6/
- https://pypi.org/project/Shapely/
- https://pypi.org/project/Nuitka/
- https://github.com/MapLibre/maplibre-gl-js/releases
- https://github.com/protomaps/PMTiles
- https://github.com/evanw/esbuild/releases
- https://gtfs.org/documentation/schedule/reference/

Propietario y autor: Yeison Arbey Carrillo Lemus.  
Todos los derechos reservados.
