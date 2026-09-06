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

- **Luna Medium:** mecánica, i18n, tests, documentación y bugs conocidos.
- **Terra Medium:** varias capas, persistencia, concurrencia, lifecycle Qt,
  diseño focal o debugging no trivial.
- **Terra High:** excepcional y justificado; nunca por longitud.
- **Sol:** diagnóstico complejo, arquitectura, seguridad, integridad o blocker.
  Preferir: Sol diagnostica; Luna/Terra implementa.
- **Astra:** deshabilitado por defecto; solo autorización explícita tras Sol y
  riesgo serio, seguridad crítica o decisión irreversible.

No escalar repetidamente: tras uno o dos intentos razonables, registrar el
bloqueo o solicitar el diagnóstico adecuado. FAST MODE solo por urgencia.

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

Cuando una tarea incluya `TASK_ID`, debe registrar su ciclo mediante el
Control Center antes de empezar y justo antes de la respuesta final:

1. `node C:\Users\yeiso\.codex\task-telemetry.mjs start <TASK_ID> ...`
2. Ejecutar la tarea dentro de su alcance.
3. `node C:\Users\yeiso\.codex\task-telemetry.mjs end <TASK_ID> --status PASS|PARTIAL|BLOCKED`

Los metadatos permitidos son pequeños y operativos (`project`, `task_type`,
`size`, `model`, `reasoning`, `parent_task`, `feature` y `gate`). No se guarda
contenido de prompts, respuestas, código, salidas de herramientas, secretos,
cookies ni credenciales. Si falla el registro, debe informarse
`TASK_TELEMETRY_STATUS=FAIL` sin inventar datos ni ocultar el trabajo realizado.
`PASS`, `PARTIAL` y `BLOCKED` son los únicos estados de cierre; `ASTRA` sigue
requiriendo autorización explícita.
