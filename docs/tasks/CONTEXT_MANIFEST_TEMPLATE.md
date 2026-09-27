# Context manifest template

```yaml
HOT:
  - AGENTS.md
  - docs/SESSION_CONTEXT.md
  - task descriptor
WARM:
  - source: docs/ARCHITECTURE.md
    reason: "" # cargar solo si la tarea cruza ese contrato
    section: "" # opcional: sección o selector
COLD: [] # historial y evidencia; solo bajo demanda
```

Marcar solo el contexto necesario. `docs/CURRENT_STATE.md` es la autoridad de estado vigente y se consulta cuando la tarea lo requiere. COLD nunca se carga por defecto.
