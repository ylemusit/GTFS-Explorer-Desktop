# A031 — Actualización y revalidación de dependencias

Fecha: 2026-08-28  
Autor: Yeison Arbey Carrillo Lemus. Todos los derechos reservados.

## Decisión

A031 actualiza únicamente dependencias runtime con cambio compatible y probado.
No se inicia P1-32, P1-33 ni P1-34, no se cambia la versión del producto y no
se modifica la lógica funcional.

| Dependencia | Antes | Después | Tipo | Motivo | Riesgo/resultado |
|---|---:|---:|---|---|---|
| PySide6 / Qt | 6.8.2.1 | 6.8.3 | runtime/UI | patch compatible | smoke Qt/WebEngine PASS; focal PASS |
| Shapely | 2.0.7 | 2.1.2 | runtime/geometría | minor compatible | distancia y focal geométrica PASS |
| DuckDB | 1.1.3 | 1.1.3 | runtime/persistencia | congelado por contratos físicos e históricos | diferido; no se elimina ningún workaround |
| Nuitka | 2.6.9 | 2.6.9 | packaging | build portable no ejecutado en A031 | diferido a packaging |
| MapLibre GL JS | 6.3.0 | 6.3.0 | mapas | no aporta cambio material sin reconstruir bundle | BACKLOG |
| PMTiles JS | 4.5.0 | 4.5.0 | mapas | ya fijado y vigente | mantenido |
| esbuild | 0.28.2 | 0.28.2 | packaging web | ya fijado y vigente | mantenido |
| pytest | 8.3.5 | 8.3.5 | test | no necesario para el objetivo | mantenido |
| Ruff | 0.9.10 | 0.9.10 | development | candidatos probados introducen fallos existentes nuevos en el gate | mantenido |
| mypy | 1.15.0 | 1.15.0 | development | candidato probado introduce incompatibilidad en el bridge | mantenido |

El candidato DuckDB 1.2.2 superó smoke y la focal, pero no se adopta: la
investigación requerida de timestamps, constraints/FK, índices, transacciones,
reapertura y migraciones no justifica mover la versión canónica en esta tarea.
Las majors (DuckDB 1.5.x, Nuitka 4.x, mypy 2.x) quedan rechazadas por alcance y
riesgo de migración. No hay evidencia local de una vulnerabilidad material ni
un advisory verificado que obligue a actualizar.

## Reproducibilidad y verificación

- `pyproject.toml` y `uv.lock` actualizados; restricciones exactas conservadas.
- Entorno limpio temporal Python 3.12.10 creado con `uv sync --frozen`: PASS.
- Imports críticos, Qt WebEngine, DuckDB, Shapely y Nuitka: PASS.
- Focal de persistencia, migraciones, lifecycle, cancelación, locking,
  recovery, mapas/offline, exportaciones, Mini-GTFS y E2E: baseline 88 passed;
  candidato 88 passed.
- `OFFLINE = 0 remote requests`, mapas controlados y E2E local: PASS según la
  focal existente.
- Suite completa sobre el entorno limpio: `472 passed` en `517,91 s`.
- `tools/check.ps1` sobre `.venv`: formato, Ruff y mypy PASS; suite `471
  passed, 1 failed` por `test_map_loopback_spike.py::test_webengine_bridge_and_range_contract_are_demonstrated`
  (`map_loaded=False`). Repetición focal en el entorno limpio A031: `4 passed`
  en `13,19 s`; se clasifica como IMPORTANTE-PERO-NO-BLOQUEANTE ambiental,
  fuera de las dependencias actualizadas.
- SMALL comparable import/validation/queries/exports: los dos procesos
  alcanzaron el límite operativo sin emitir JSON y se cancelaron; resultado
  `TIMEOUT/NOT VERIFIED`, sin usarlo para afirmar una regresión.

## Hallazgos

- BLOCKER: ninguno identificado por la actualización aplicada.
- IMPORTANTE-PERO-NO-BLOQUEANTE: `tools/check.ps1` tuvo un fallo aislado de
  WebEngine en el `.venv` histórico; la repetición final pasó. No se han
  ocultado ni refactorizado hallazgos fuera de A031.
- BACKLOG: investigación focal DuckDB, build portable/NSIS real y actualización
  independiente de herramientas de desarrollo o MapLibre si aportan valor.

`NSIS_BINARY_GATE = PENDING_P1_32` porque `makensis` no se instala ni se usa en
A031.
