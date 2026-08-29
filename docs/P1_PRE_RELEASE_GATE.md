# P1 — Gate pre-release de arquitectura

Fecha: 2026-08-27  
Estado: CERRABLE

## Alcance

Auditoría de arquitectura y robustez del núcleo completado P0 y P1-01 a
P1-30. No se aplicaron actualizaciones de dependencias, no se construyeron
artefactos, ni se inició packaging, upgrade, RC, P2 o una funcionalidad nueva.

El worktree ya contenía cambios de P1 antes de la auditoría. Este gate no
modifica código de producto ni atribuye esos cambios a un fix nuevo.

## Evidencia ejecutada

- Batería crítica de lifecycle, persistencia/reapertura, cancelación, recovery,
  locking, operaciones, exportaciones y mapas: `114 passed in 126.75s`.
- Journeys productivos: `pytest -q -m e2e tests/test_e2e_journeys.py`:
  `11 passed in 47.17s`.
- Gate canónico `tools/check.ps1`: Ruff format, Ruff lint y mypy sin
  incidencias; suite completa `472 passed in 463.55s`.
- `git diff --check`: sin errores de whitespace. Los avisos LF/CRLF existentes
  de Git no son errores de contenido.

La suite cubre comportamiento file-backed, reapertura y procesos reales para
el lock; no se limita a asserts estructurales. Los E2E usan el flujo Qt,
DuckDB y filesystem locales, y sustituyen únicamente el render pixel-perfect
de WebEngine por un doble funcional. Por ello el smoke visual real sigue siendo
un gate manual, no una afirmación implícita de esta evidencia.

## Resultado de la auditoría

| Área | Resultado |
| --- | --- |
| Arquitectura y fuentes de verdad | DuckDB permanece como estado canónico; `project.json` es descriptor/mirror recuperable; `product.py`, paths/settings y `operations` mantienen responsabilidades distinguibles. No se ha hallado una contradicción durable. |
| Lifecycle de proyecto y UI | Create/open/close/reopen y cambio A a B reconstruyen el estado desde disco y limpian el contexto dependiente del proyecto. `NO_PROJECT` conserva acciones protegidas. |
| Importación y cancelación | `READY`, `INVALID`, `CANCELLED` y `FAILED` siguen separados. Un feed semánticamente inválido queda importado e inspeccionable; una reimportación cancelada conserva el feed anterior. |
| Operations e historial | `INTERRUPTED` se deriva al presentar operaciones residuales `RUNNING`; no muta el ledger histórico. Las transiciones, detalles y reapertura están cubiertos sobre DuckDB file-backed. |
| Persistencia y migraciones | La cadena 001–009 se aplica transaccionalmente, comprueba versión e historial y toma copia previa al migrar una base existente. Las regresiones cubren 8 a 9, rollback y preservación de backup. |
| Lock y recovery | El lock del SO es la autoridad; se prueba segundo escritor y carrera. Recovery inspecciona antes de mutar, usa lock, snapshot, staging, validación y rollback; no se halló un camino normal que sobrescriba un proyecto válido. |
| RAW, compatibilidad y validación | Se preservan `source_row`, líneas físicas y CSV multilinea; las horas >=24, route types extendidos y valores desconocidos conservan los contratos de P1. Los estados y filtros de validación no fabrican un resultado técnico. |
| Exportaciones y Mini-GTFS | JSON, CSV, GeoJSON y Mini-GTFS verifican selección, manifiesto, SHA-256, publicación, historial y privacidad. Mini-GTFS se reimporta en un proyecto independiente manteniendo dependencias, IDs, shapes, servicios y lexemas relevantes. |
| Mapas y privacidad | `OFFLINE` bloquea remoto; los orígenes online se limitan al proveedor activo y las teselas sólo usan `z/x/y`. Paquetes locales validan paths, hashes, estilos sin URLs remotas y separan validez de renderizabilidad. |
| Rendimiento y threading | El progreso/cancelación es cooperativo y el cleanup terminal está cubierto. MEDIUM lento y LARGE timeout de staging no han demostrado corrupción ni inviabilidad universal de uso normal. |
| Windows, identidad y directorios | La identidad sale de `product.py`; las rutas mutables se separan de la instalación y soportan Documents redirigido/Unicode. Los tests cubren i18n, metadatos, directorios recordados y diálogos. |
| Accesibilidad, ayuda y documentación | Labels, metadata accesible, teclado y ayuda local están cubiertos contractualmente. No se detectó una afirmación material de privacidad o comportamiento que contradiga el producto. |
| Seguridad y privacidad global | Import ZIP rechaza traversal, enlaces, colisiones y límites inseguros; mapas/recovery/exportaciones validan rutas y publicación. Logs y diagnósticos tienen regresiones negativas para paths y secretos. |

## Clasificación de hallazgos

### RELEASE BLOCKERS

Ninguno. No se ha reproducido pérdida o corrupción de datos, comportamiento
destructivo, lifecycle incoherente, persistencia falsa, doble escritor,
recovery inseguro, exportación corrupta ni fuga seria de privacidad.

### POST-RC

- Prueba manual con lector de pantalla; no hay certificación NVDA, JAWS o
  Narrator.
- Smoke visual real de WebEngine/Chromium y disponibilidad externa del proveedor
  online, separados del contrato de privacidad ya probado.

### TECH DEBT

- LARGE alcanza timeout durante staging; el perfil observado apunta a coste
  lineal de inserción DuckDB, no a una regresión funcional o cuadrática.
- Las exportaciones pesadas son síncronas y pueden congelar temporalmente la UI.
- `MainWindow` concentra responsabilidades; no se ha demostrado un defecto
  material actual.

### IMPROVEMENTS

- Screenshots mantenibles y mejoras incrementales de la guía.
- Accesibilidad avanzada del lienzo cartográfico MapLibre/WebGL.
- Perfil y optimización posterior de staging LARGE o progreso de exportación,
  si una medición de uso real lo justifica.

## Gates manuales y binarios pendientes

Son gates de las fases posteriores, no bloqueos del núcleo auditado:

- P1-32: build portable/NSIS, Properties del EXE, inclusión de ayuda, hashes,
  instalación y desinstalación en entorno limpio.
- P1-33: upgrade desde una instalación anterior con proyecto persistente.
- P1-34: RC real, revisión legal/publicación y autorización explícita de
  distribución.

## Decisión

`A031_UNFREEZE = YES` — el núcleo puede entrar en una actualización de
dependencias acotada a componentes aprobados por A030, con evidencia y rollback
por componente. Este gate no ejecuta A031.

`PACKAGING_READY_AFTER_A031 = YES` — la arquitectura no impide iniciar P1-32
después de A031; los gates binarios indicados arriba siguen siendo obligatorios
antes de cualquier distribución.

`CORE_FREEZE_READY = YES`

P1-PRE-RELEASE-GATE-CERRABLE
