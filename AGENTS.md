# GTFS Explorer Desktop — Operating model

## Una tarea por chat

Cada chat tiene un objetivo y descriptor únicos. No mezclar fases, features,
refactors ni gates independientes; los pendientes van a otro chat.

## Disciplina de contexto

Usar el contexto mínimo suficiente:

- **HOT:** `AGENTS.md`, `docs/SESSION_CONTEXT.md`, descriptor de tarea y
  `docs/TASK_STATUS.json` solo si aplica el orquestador legado.
- **WARM:** bajo demanda `ARCHITECTURE.md`, `DOMAIN.md`, ADR concreto,
  especificación, tests y módulos relacionados.
- **COLD:** no leer por defecto. Historial, gates, incidentes, benchmarks,
  releases y evidencias están en GTFS Explorer Engineering o Artifacts.

No recorrer `docs/` entero ni cargar historia para una tarea ordinaria.

## Implementación y documentación

Conservar arquitectura, contratos y trabajo ajeno. Preferir el cambio mínimo;
sin limpiezas generales ni dependencias innecesarias. Una tarea documental no
modifica `src/`, runtime web, GTFS, esquema ni comportamiento de producto.

Actualizar `CURRENT_STATE.md` solo ante cambio material actual;
`ARCHITECTURE.md` si cambia arquitectura; `DOMAIN.md` si cambian reglas; y ADR
para decisiones relevantes. Evidencia histórica en Engineering; binarios,
manifests y runtime evidence en Artifacts.

## Modelos y escalado

Consultar `docs/tasks/AI_EXECUTION_POLICY.md` y registrar un perfil por run.
Escalar solo por causa demostrada; cada retry requiere evidencia o hipótesis nueva.
El límite de ejecución es el `EXECUTION_BOUNDARY` de la tarea y aplica privilegio mínimo.
Las reglas normativas de recursos y operaciones Git están en
[AI_EXECUTION_POLICY.md](docs/tasks/AI_EXECUTION_POLICY.md).

## Verificación y salida

Durante desarrollo, ejecutar solo checks directamente afectados. La batería
integrada completa pertenece al gate final salvo riesgo crítico. Build,
packaging, Defender, publicación, commit y tag requieren su gate y autorización.

Final compacto: estado, cambio o causa, archivos, verificación, métrica/riesgo
importante y siguiente gate. No pegar archivos ni narrar comandos.

## Condiciones de parada

Detenerse al cumplir aceptación. No publicar, desplegar, gastar, procesar datos
sensibles, hacer commit/tag ni tocar releases estables sin autorización. No
afirmar validaciones no ejecutadas.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.

## Task Telemetry

La telemetría es `OPTIONAL_LOCAL_INTEGRATION`. El entorno de ejecución puede
proporcionar una integración compatible; el repositorio no exige una ruta
local concreta. Si está disponible y habilitada, puede registrar al inicio y
al cierre `TASK_ID`, `RUN_ID`, intento, modelo/perfil y estados, junto con los
metadatos operativos ya establecidos (clase, riesgo, complejidad, razonamiento,
verificación/aceptación y causa de bloqueo).

`TASK_ID` es estable y `RUN_ID` único por ejecución. No se guarda contenido de
prompts, respuestas, código, salidas de herramientas, secretos, cookies ni
credenciales. Si la integración no está disponible o falla, registrar cuando
sea relevante `TASK_TELEMETRY_STATUS=UNAVAILABLE` y continuar el trabajo
autorizado, sin inventar datos. La ausencia o fallo de telemetría no bloquea
desarrollo, verificación ni documentación, ni constituye un fallo de la tarea
salvo que la telemetría figure explícitamente en sus criterios de aceptación.

`PASS`, `PARTIAL` y `BLOCKED` son los estados de cierre de tarea admitidos por
la integración; no sustituyen los resultados de verificación.
`ASTRA` sigue requiriendo autorización explícita.
