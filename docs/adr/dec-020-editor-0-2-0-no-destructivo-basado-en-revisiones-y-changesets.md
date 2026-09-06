# DEC-020 — Editor 0.2.0 no destructivo basado en revisiones y ChangeSets

Fecha: 2026-09-03

Estado: Aceptada e integrada en el núcleo, la migración y los primeros

## Decisión preservada

Fecha: 2026-09-03

Estado: Aceptada e integrada en el núcleo, la migración y los primeros
verticales; la publicación de la release continúa pendiente.

La implementación integra `EditorSession`, un `EditorWidget` y un repositorio
DuckDB de deltas para rutas, viajes, stop_times, shapes, servicios,
calendar/calendar_dates, agencias y attributions, además de las dependencias
directas de frecuencias y transfers. Las tablas `gtfs_*` quedan fuera de toda
mutación del editor.

El feed original y su staging permanecen inmutables. La edición se realiza en
un borrador materializado sobre una WorkingRevision y solo una confirmación
atómica publica una revisión nueva. Los cambios son comandos explícitos con
before/after, impacto, previsualización de relaciones y operación inversa; el
historial persiste undo/redo. Las eliminaciones o renombrados con referencias
requieren cambios secundarios explícitos dentro del mismo comando compuesto.
La revisión `original` es la revisión 0 implícita. `editor_revisions` guarda
metadatos y `editor_revision_deltas` conserva una fila JSON por entidad
modificada o eliminada; la reconstrucción es `ORIGINAL_GTFS + cadena de deltas`.
Así se mantiene la compatibilidad de las consultas GTFS, DuckDB y UI sin
persistir snapshots monolíticos del feed. La compactación/checkpoints queda
preparada para una decisión posterior.

La apertura de proyectos 0.1.0 prepara el almacenamiento del editor mediante
una migración editorial v2, idempotente, transaccional y con backup dedicado.
Inicializa `base_revision_id` y `working_revision_id` en `original`, sin crear
`working-0.entities_json`. Los proyectos experimentales anteriores convierten
sus snapshots publicados a deltas por entidad y eliminan el formato antiguo;
una excepción restaura el archivo DuckDB antes de liberar el lock. La
migración no cambia el esquema GTFS ni el descriptor histórico.

MapLibre/WebEngine conserva un bridge restringido v1/v2 y no puede escribir
datos: los gestos solo se convierten en propuestas de comandos autorizados.
Horarios, servicios y operadores usan el mismo contrato de impacto. KML/KMZ
es intercambio geoespacial seguro y clasificado, no una prueba de que un
fichero sea un GTFS completo. El routing automático, servidor, cuentas y red
adicional quedan fuera de 0.2.0.

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
