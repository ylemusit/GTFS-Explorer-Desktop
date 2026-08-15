# Dominio del proyecto

Última actualización: 2026-08-11

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
- Validez, buenas prácticas y reglas propias se muestran separadas; no hay puntuación numérica en v1.0.

## Estados

```text
Proyecto: IMPORTING | READY | INVALID | CANCELLED | FAILED | RECOVERY_REQUIRED | MIGRATION_REQUIRED
Problema: FATAL | ERROR | WARNING | NOTICE
Job: PENDING | RUNNING | CANCELLING | SUCCEEDED | CANCELLED | FAILED
```

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
