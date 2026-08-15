# `gtfs-explorer.bundle` 1.0.0

Contrato público de una exportación JSON normalizada de GTFS Explorer Desktop.

- Se valida contra `gtfs-explorer.bundle.schema.json` (JSON Schema draft 2020-12).
- El exportador produce arrays en orden determinista; el schema valida forma, no orden.
- `null` representa un dato GTFS ausente. Las horas usan texto GTFS y segundos desde el inicio del día de servicio, por lo que pueden superar `24:00:00`.
- El bundle no contiene rutas locales, usuarios de Windows ni datos fuera de la selección.

La serie 1.x solo admite cambios compatibles. Cambiar campos obligatorios, tipos, nullabilidad, unidades, semántica o eliminar campos exige crear `2.0.0` y emitir `schema_version: "2.0.0"`.

`minimal.json` y `complete.json` son golden files semánticos y usan datos sintéticos.
