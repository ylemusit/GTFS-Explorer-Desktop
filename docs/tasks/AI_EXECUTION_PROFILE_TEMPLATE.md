# AI execution profile template

Perfil por ejecución, separado del contrato permanente. `RUN_ID` identifica un run único; `ATTEMPT` numera intentos de la misma tarea.

```yaml
RUN_ID: ""
TASK_ID: ""
ATTEMPT: 1
MODEL: ""
REASONING: medium
SELECTION_REASON: ""
ITERATION_BUDGET: 2
ESCALATION:
  ALLOWED: false
  MAX_MODEL: none
  MAX_REASONING: medium
EXECUTION_MODE: NORMAL_TASK
PERMISSIONS_PROFILE: "" # referencia al EXECUTION_BOUNDARY de la tarea
```

Cada retry requiere evidencia nueva o una hipótesis distinta. La telemetría es
`OPTIONAL_LOCAL_INTEGRATION`, según [AGENTS.md](../../AGENTS.md): si el entorno
proporciona una integración compatible, disponible y habilitada, puede registrar
el perfil efectivo y los metadatos del run. Si falta o falla, registrar cuando
sea relevante `TASK_TELEMETRY_STATUS=UNAVAILABLE` y continuar el trabajo
autorizado. Solo afecta a la aceptación de la tarea si la telemetría es un
criterio explícito; no exige una ruta personal ni bloquea otros checks.
