# Decisiones del producto

Índice de ADR vigentes e históricos del producto. Los detalles están en
docs/adr/; el documento monolítico anterior se conserva, con hash verificado,
en GTFS Explorer Engineering.

| ID | Decisión | Estado |
| --- | --- | --- |
| [DEC-020](adr/dec-020-editor-0-2-0-no-destructivo-basado-en-revisiones-y-changesets.md) | Editor 0.2.0 no destructivo basado en revisiones y ChangeSets | Aceptada e integrada en el núcleo, la migración y los primeros |
| [DEC-001](adr/dec-001-aplicaci-n-windows-con-pyside6-qt-widgets.md) | Aplicación Windows con PySide6/Qt Widgets | Aceptada, validada por el smoke T001 |
| [DEC-013](adr/dec-013-versiones-fijadas-tras-smoke-t001.md) | Versiones fijadas tras smoke T001 | Aceptada |
| [DEC-002](adr/dec-002-duckdb-como-motor-nico-por-proyecto.md) | DuckDB como motor único por proyecto | Aceptada |
| [DEC-003](adr/dec-003-doble-representaci-n-staging-fiel-y-modelo-tipado.md) | Doble representación: staging fiel y modelo tipado | Aceptada |
| [DEC-004](adr/dec-004-sin-pandas-polars-geopandas-ni-pydantic-obligatorios.md) | Sin Pandas, Polars, GeoPandas ni Pydantic obligatorios | Aceptada |
| [DEC-005](adr/dec-005-maplibre-local-y-pmtiles-opcional.md) | MapLibre local y PMTiles opcional | Aceptada, revisada por DEC-016 |
| [DEC-015](adr/dec-015-t070-no-go-para-pmtiles-mediante-scheme-handler.md) | T070 NO-GO para PMTiles mediante scheme handler | Superada por DEC-016 |
| [DEC-016](adr/dec-016-t070-go-con-servidor-loopback-ef-mero-protegido.md) | T070 GO con servidor loopback efímero protegido | Aceptada |
| [DEC-018](adr/dec-018-p1-16-pol-tica-offline-first-de-mapas.md) | P1-16 política offline-first de mapas | Aceptada |
| [DEC-019](adr/dec-019-p1-17-convivencia-de-basemap-online-y-overlay-gtfs-local.md) | P1-17 convivencia de basemap online y overlay GTFS local | Aceptada |
| [DEC-006](adr/dec-006-validaci-n-trazable-sin-puntuaci-n-num-rica.md) | Validación trazable sin puntuación numérica | Aceptada |
| [DEC-007](adr/dec-007-v1-0-se-limita-a-gtfs-schedule.md) | v1.0 se limita a GTFS Schedule | Aceptada |
| [DEC-008](adr/dec-008-exportaciones-p-blicas-versionadas.md) | Exportaciones públicas versionadas | Aceptada |
| [DEC-009](adr/dec-009-portable-standalone-y-nsis.md) | Portable standalone y NSIS | Aceptada y demostrada por T091/T092 |
| [DEC-010](adr/dec-010-privacidad-local-y-red-opt-in.md) | Privacidad local y red opt-in | Aceptada |
| [DEC-011](adr/dec-011-coste-obligatorio-de-licencias-servicios-0.md) | Coste obligatorio de licencias/servicios: 0 € | Aceptada como objetivo |
| [DEC-012](adr/dec-012-una-tarea-del-plan-por-chat.md) | Una tarea del plan por chat | Aceptada |
| [DEC-014](adr/dec-014-terra-medio-para-el-piloto-del-orquestador.md) | Terra Medio para el piloto del orquestador | Aceptada para evaluación |
| [DEC-017](adr/dec-017-alcance-y-versi-n-objetivo-de-la-actualizaci-n-posterior-a-rc1.md) | Alcance y versión objetivo de la actualización posterior a rc1 | Aceptada para la actualización |

## Uso

Lee únicamente el ADR relacionado con la tarea. Una decisión nueva debe crear
un ADR con ID, fecha, estado, contexto, decisión y consecuencias; después se
añade al índice sin duplicar el contenido.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
