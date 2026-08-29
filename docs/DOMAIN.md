# Dominio del proyecto

Última actualización: 2026-08-26

## Propósito

Representar y explorar GTFS Schedule de forma fiel, relacional, trazable y segura. La aplicación no es un planificador ni un sistema operacional.

## Actores

- Usuario técnico/analista.
- Integrador que consume exportaciones.
- Responsable que revisa validez y licencias del feed.

No hay clientes o compradores confirmados.

## Conceptos

- **Fuente:** ZIP, carpeta o archivo compatible seleccionado, siempre de solo lectura.
- **Feed:** dataset GTFS Schedule asociado a hash, revisión de especificación e importación.
- **Proyecto:** workspace persistente con DuckDB, descriptor, caché y reportes.
- **Staging:** copia lógica fiel de valores y procedencia.
- **Modelo tipado:** representación consultable que no reemplaza el staging.
- **Servicio:** reglas de calendario asociadas por `service_id`.
- **Tiempo de servicio:** segundos desde el inicio del día de servicio; puede superar 24 horas.
- **Selección:** conjunto explícito de rutas, viajes o servicios que limita consulta/exportación.
- **Problema:** resultado trazable de una regla, con severidad y origen.
- **Mini-GTFS:** subconjunto Schedule autocontenido y revalidado; no una simple selección de filas.
- **Paquete de mapa:** PMTiles, estilo, assets, licencia, atribución y hashes.

## Reglas esenciales

- No modificar la fuente.
- No descartar filas ni corregir valores silenciosamente.
- No asumir que `direction_id=0/1` significa ida/vuelta.
- No tratar `.csv` compatible como GTFS oficial.
- No mezclar GTFS Schedule y Realtime.
- No inferir datos ausentes.
- GeoJSON usa `[longitud, latitud]`.
- Mini-GTFS solo se publica si el cierre de dependencias soportado se reimporta y valida.
- Mini-GTFS se selecciona por una o varias `route_id`; `trip_id` y `service_id` solo
  restringen los viajes de esas rutas. Una selección sin ruta, sin viajes compatibles
  o con referencias core rotas se rechaza antes de publicar.
- El cierre core incluye `agency.txt`, `routes.txt`, `trips.txt`, `stops.txt`,
  `stop_times.txt` y solo los servicios seleccionados de `calendar.txt` y/o
  `calendar_dates.txt`, incluyendo `parent_station` y las shapes referenciadas.
- Los opcionales normalizados actualmente (`frequencies.txt`, `transfers.txt`,
  `feed_info.txt` y `attributions.txt`) se incluyen solo con filas existentes y
  relevantes; los opcionales no soportados y la metadata interna del workspace se
  excluyen. Las relaciones a entidades fuera de la selección se descartan para no
  crear referencias huérfanas.
- El exportador conserva IDs, lexemas UTF-8, tipos extendidos, horas superiores a
  `24:00:00` y filas repetidas de `stop_times`; no regenera IDs, no deduplica por
  `stop_id` ni fabrica fechas o metadata para ajustar el subconjunto.
- El ZIP debe tener tablas `.txt` en la raíz, orden estable y pasar reimportación y
  validación normal en un proyecto independiente antes de generar el manifiesto.
- Validez, buenas prácticas y reglas propias se muestran separadas; no hay puntuación numérica en v1.0.

## Estados

```text
Proyecto: IMPORTING | READY | INVALID | CANCELLED | FAILED | RECOVERY_REQUIRED | MIGRATION_REQUIRED
Problema: FATAL | ERROR | WARNING | NOTICE
Job: PENDING | RUNNING | CANCELLING | SUCCEEDED | CANCELLED | FAILED
```

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
