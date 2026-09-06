# DEC-017 — Alcance y versión objetivo de la actualización posterior a rc1

Fecha: 2026-08-18

Estado: Aceptada para la actualización

## Decisión preservada

Fecha: 2026-08-18

Estado: Aceptada para la actualización

La siguiente candidata local se denominará `0.1.0-rc2`. No es una publicación,
una autorización de distribución ni una versión final. Mantiene la versión base
`0.1.0` porque el alcance previsto no modifica contratos públicos de
importación, validación o exportación; en particular, respeta DEC-008 y no
requiere incrementar la versión mayor del bundle JSON.

El alcance candidato comprende exclusivamente los cambios que superen sus
tareas y pruebas: identidad y créditos coherentes (A010), presentación de
inicio accesible y no bloqueante (A011), estados vacíos del resumen (A012),
actualización del instalador por usuario (A013) y, solo si se aprueba tras su
auditoría, el mantenimiento técnico de A030--A032. El feed
`examples/ctm-mallorca-es.zip` queda excluido del alcance de la candidata, de
los artefactos y de cualquier recorrido de ejemplo; no se planifica auditarlo
ni incorporarlo.

Los cambios locales inventariados en A000 no se incorporan por esta decisión:
cada uno sigue condicionado a los criterios de aceptación de su tarea. La
fuente canónica y los nombres de artefactos se actualizarán únicamente en A032,
después de cerrar el alcance; hasta entonces `pyproject.toml` y
`gtfs_explorer.__version__` permanecen sin cambios.

El rollback consiste en no generar ni sustituir artefactos `rc1`: si fallan las
pruebas, el build, el smoke o el upgrade N-1 de la actualización, la candidata
`rc2` no se prepara y la corrección se limita a la tarea que haya fallado antes
de reconstruir artefactos nuevos.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## Procedencia

Migrada sin reinterpretación desde docs/DECISIONS.md, preservada con SHA-256
en GTFS Explorer Engineering durante la rebaseline documental del 2026-09-05.
