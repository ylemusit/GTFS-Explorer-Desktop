# Arquitectura del proyecto

Última actualización: 2026-08-13

## Resumen

Aplicación Windows x64 local y offline-first construida en Python/PySide6. DuckDB persiste un staging fiel, un modelo GTFS tipado y resultados derivados. La presentación Qt consume casos de uso; nunca ejecuta SQL. MapLibre se incrusta con Qt WebEngine, se comunica por contratos QWebChannel y consume PMTiles opcional mediante un servidor HTTP efímero limitado a loopback.

```text
Qt Widgets -> aplicación -> dominio/puertos -> DuckDB/import/validación/export
     |
     +-> QWebChannel -> MapLibre local -> HTTP 127.0.0.1 efímero -> PMTiles opcional
```

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

Dominio no depende de capas externas. Presentación no contiene SQL. JavaScript no accede a DB ni filesystem.

## Datos

- Manifiesto de origen con hashes.
- `stg_*`: valores fieles como texto y fila fuente.
- `gtfs_*`: columnas tipadas.
- `drv_*`: derivados regenerables.
- `v_*`: vistas de consulta.
- Una base DuckDB por proyecto, con migraciones y escritor único.

IDs se conservan como texto. Horas GTFS usan segundos desde el día de servicio y lexema original para admitir valores superiores a 24 horas.

## Distribución

- Portable: build `standalone` con `portable.flag` y workspace relativo si es escribible.
  `tools/build_portable.py` publica el ZIP x64, su SHA-256 y un manifiesto interno.
- Instalado: workspace en `%LOCALAPPDATA%\GTFS Explorer`.
- Instalador objetivo: NSIS.
- Mapas regionales y MobilityData/JRE, si se distribuyen, son paquetes separados por tamaño/licencia.

El detalle vinculante y el árbol objetivo están en `PLAN_MAESTRO_CONSTRUCCION.md`.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
