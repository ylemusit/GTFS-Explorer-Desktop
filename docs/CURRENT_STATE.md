# Estado actual del producto

## Línea base protegida actual

**GTFS Explorer Desktop v0.2.2** es la línea base activa y protegida.

- Estado de release: `RELEASE_CLOSED`.
- Estado de línea base: `ACTIVE_PROTECTED_BASELINE`.
- Commit de release protegido: `85c700587ffec06d73d84825e1951fb73259b62c`.
- Árbol de release protegido: `4aa02bf1f040798fa4099a0e48ff734514e39e85`.
- Tag protegido: `v0.2.2`.
- Esquema de proyecto: `11`.
- Esquema de informe: `1.1.0`.

`v0.2.2` es un release histórico inmutable. El desarrollo futuro se realizará
en commits descendientes; cualquier cambio distribuido requiere una nueva
versión de producto.

## Estado funcional cerrado

- GTFS-021 y GTFS-022: CLOSED.
- GTFS-023: `CLOSED_IN_V0.2.2`.
- Bizkaibus, resultado aceptado actual:
  `run_004_gtfs023_candidate001`.
- Los 1.040.852 hallazgos históricos de Bizkaibus están clasificados como
  `INVALIDATED_PRODUCT_FINDING` y `FALSE_POSITIVE_ENUM_CONTRACT`.
- Bloqueadores funcionales abiertos heredados del cierre de v0.2.2: ninguno.

## Observaciones no bloqueantes

- El fixture de prueba DuckDB grande ocupa aproximadamente 54,51 MB.
- Existe un histórico de variabilidad temporal de preparación QWebEngine/MapLibre.
- La exportación de informe de validación sin incidencias está deshabilitada por
  el comportamiento actual de la interfaz.
- El release v0.2.2 no está firmado.

Estas observaciones no son bloqueadores no resueltos de v0.2.2.

## Siguiente fase de ingeniería

`AUDIT_QUALITY_REQUIREMENT_MODEL` es la siguiente fase de ingeniería. No está
implementada todavía y debe construirse sobre v0.2.2, manteniendo separadas la
conformidad con la especificación GTFS, calidad de datos, buenas prácticas,
hallazgos de auditoría y mapeos regulatorios o legales.

Todos los derechos reservados.
