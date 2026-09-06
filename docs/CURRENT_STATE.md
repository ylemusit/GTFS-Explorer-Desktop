# Estado actual del producto

## Target version

`0.2.0` — editor visual GTFS no destructivo en
`feature/0.2.0-visual-editor`.

## Product status

Correcciones pre-release acotadas tras auditoría independiente; no hay
autorización para nuevas funcionalidades.

## PASS

- Original GTFS y tablas `gtfs_*` inmutables; edición por Working Copy,
  revisiones y ChangeSets (DEC-020).
- RC1 0.2.0 y su gate de distribución Defender: PASS histórico.

## PARTIAL

- Aceptación visual nativa de editor, Windows/DPI/WebEngine y accesibilidad
  manual: no verificada. Un smoke técnico no la acredita.

## Open blockers

- Auditoría pre-release independiente: P1/P2 corregidos en fuente, pendiente
  de Final Source Gate. RC1 se conserva intacta, pero no es elegible para la
  versión final porque antecede a estas correcciones.

## Deferred

- Propagación avanzada de horarios, aceptación visual y gates de
  packaging/release quedan fuera de esta rebaseline.

## Last verified

2026-09-06: RC1 histórico PASS en distribución; auditoría independiente halló
P1/P2. Las correcciones requieren nuevo gate de fuente y nueva RC.

## Next authorized phase

`GTFS-020-FINAL-SOURCE-REGATE-001`; tras PASS, construir una nueva RC. La
aceptación humana final continúa pendiente.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
