# Arquitectura del proyecto

Última actualización: 2026-08-27

## Resumen

Aplicación Windows x64 local y offline-first construida en Python/PySide6. DuckDB persiste un staging fiel, un modelo GTFS tipado y resultados derivados. La presentación Qt consume casos de uso; nunca ejecuta SQL. MapLibre se incrusta con Qt WebEngine, se comunica por contratos QWebChannel y mantiene separado el overlay GTFS local del basemap, que puede ser PMTiles mediante un servidor efímero de loopback o teselas online de un proveedor allowlisted.

```text
Qt Widgets -> aplicación -> dominio/puertos -> DuckDB/import/validación/export
     |
     +-> QWebChannel -> MapLibre local
                         |-> overlay GTFS local (routes/shapes/stops)
                         |-> basemap PMTiles -> HTTP 127.0.0.1 efímero
                         |-> basemap online -> proveedor HTTPS allowlisted
                         \-> política AUTO/OFFLINE/ONLINE
```

## Identidad y versionado

`src/gtfs_explorer/product.py` mantiene la identidad canónica del producto:
nombre, versión, edición, autor, copyright y revisión de la especificación
GTFS. Las capas de runtime, presentación, diagnóstico, exportación y benchmark
consumen `IDENTITY`; los consumidores históricos de `__version__` reciben un
alias compatible sin declarar otra versión.

La presentación muestra la identidad en el título, la bienvenida y Acerca de.
Los builders no duplican la versión: portable renderiza un spec efímero con
metadata PE para Nuitka y NSIS recibe sus definiciones desde el mismo módulo.
Los manifests de ambos formatos incluyen la versión de producto y la versión
numérica de archivo. El build id procede únicamente de un identificador de
pipeline con formato seguro y usa `local` como fallback.

## Capas y dirección de dependencia

- `domain`: tipos, reglas y puertos; no conoce Qt, DuckDB ni filesystem.
- `application`: comandos, queries, jobs, progreso y cancelación.
- `infrastructure`: importadores seguros, DuckDB, validadores, geometría, exportadores y archivos.
- `presentation`: Qt Widgets, modelos paginados y bridge del mapa.
- `resources/map_web`: bundle local bloqueado; sin CDN o Node en runtime.
- `resources/help`: manual versionado incluido en el paquete; la UI lo busca y
  presenta como texto escapado, sin depender de enlaces externos.
- El servidor del mapa enlaza solo `127.0.0.1`, usa puerto y token efímeros,
  valida `Host` y expone una lista cerrada de recursos y métodos. Su ciclo de
  vida queda ligado a la vista; nunca sirve proyectos ni rutas arbitrarias.
- La política global ofrece `AUTO`, `OFFLINE` y `ONLINE`. `AUTO` prioriza un
  paquete local cuando sus bounds cubren el overlay completo; fuera de cobertura
  usa el proveedor online central. `OFFLINE` no permite red exterior y conserva
  el overlay sobre fondo neutro si no hay cobertura. `ONLINE` fuerza el proveedor
  online aunque exista PMTiles.
- El proveedor online actual es `OpenStreetMap Standard` y solo genera rutas de
  tesela con `z/x/y`. El estilo, worker, bridge y GeoJSON GTFS son locales; el
  cambio de basemap no toca DuckDB, IDs, selección ni la cámara.
- El interceptor de Qt no conserva URLs bloqueadas. Las peticiones externas
  solo pueden alcanzar el hostname del proveedor configurado, con coordenadas
  de tesela `z/x/y`, sin query, credenciales ni contexto GTFS. En `OFFLINE` son
  cero.

Dominio no depende de capas externas. Presentación no contiene SQL. JavaScript no accede a DB ni filesystem.

## Datos

- Manifiesto de origen con hashes.
- `stg_*`: valores fieles como texto y fila fuente.
- `gtfs_*`: columnas tipadas.
- `drv_*`: derivados regenerables.
- `v_*`: vistas de consulta.
- Una base DuckDB por proyecto, con migraciones y escritor único.

IDs se conservan como texto. Horas GTFS usan segundos desde el día de servicio y lexema original para admitir valores superiores a 24 horas.

## Almacenamiento y ubicaciones de usuario

`ApplicationPaths` centraliza las ubicaciones. En Windows usa
`QStandardPaths.DocumentsLocation`, por lo que respeta Documents redirigido,
OneDrive y perfiles no estándar; los entornos Linux/macOS usan el fallback
estándar de Python. Estas rutas son defaults de los diálogos, no obligaciones:
cuando corresponde, la persona usuaria puede elegir otra carpeta y la fuente
original no se mueve ni se copia silenciosamente.

| Recurso | Ubicación predeterminada instalada | Contrato |
| --- | --- | --- |
| Proyectos | `Documents/GTFS Explorer/Projects` | Workspace elegido por el usuario; no se migran proyectos existentes automáticamente. |
| Imports GTFS | `Documents/GTFS Explorer/Imports` | Solo inicio del selector; ZIP/carpeta/CSV permanecen donde se seleccionaron. |
| Exports | `Documents/GTFS Explorer/Exports` | Destino inicial de JSON, GeoJSON, CSV, Mini-GTFS, informes y vistas raw; naming P1-13 sigue vigente. |
| Fuentes PMTiles | `Documents/GTFS Explorer/Maps` | Inicio del selector; la biblioteca gestionada no está aquí. |
| Mapas offline gestionados | `%LOCALAPPDATA%/GTFS Explorer/maps` | Biblioteca global P1-18; los PMTiles importados se copian según su contrato actual. |
| Diagnósticos | `Documents/GTFS Explorer/Diagnostics` | Destino inicial del ZIP que el usuario decide exportar. |
| Recovery | `<workspace del proyecto>/recovery` | Mecanismo P1-20 actual; no se mueve a una raíz global. |

Logs, settings, caché y temporales técnicos permanecen en
`%LOCALAPPDATA%/GTFS Explorer` (o en el workspace portable existente). El
settings local solo recuerda `last_project_dir`, `last_import_dir`,
`last_export_dir`, `last_pmtiles_import_dir` y `last_diagnostic_dir`. Si una
preferencia falta o deja de ser accesible se usa el default; las carpetas de
usuario se crean lazymente al abrir la operación que las necesita. No se
escriben datos modificables en `Program Files`, ni se incorporan rutas nuevas a
DuckDB, historial, recovery report, metadata pública de diagnóstico o manifest
de exportación.

## Distribución

- Portable: build `standalone` con `portable.flag` y workspace relativo si es escribible.
  `tools/build_portable.py` publica el ZIP x64, su SHA-256 y un manifiesto interno.
- Instalado: workspace en `%LOCALAPPDATA%\GTFS Explorer`.
- Instalador objetivo: NSIS.
- Mapas regionales y MobilityData/JRE, si se distribuyen, son paquetes separados por tamaño/licencia.

El detalle vinculante y el árbol objetivo están en `PLAN_MAESTRO_CONSTRUCCION.md`.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
