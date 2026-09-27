# Task contract template

Una tarea primaria por chat. Declarar `none`, `not_required` o `unknown` cuando proceda. Modelo y razonamiento pertenecen al [perfil de ejecución](AI_EXECUTION_PROFILE_TEMPLATE.md).

```yaml
TASK_ID: ""
TITLE: ""
TASK_CLASS: "" # ver AI_EXECUTION_POLICY.md
EXECUTION_MODE: NORMAL_TASK # o LONG_HORIZON_INVESTIGATION
GOAL: ""
BASELINE: "" # identidad protegida, si aplica
HEAD: ""
BRANCH: ""
WORKTREE_STATE: ""
SCOPE: []
OUT_OF_SCOPE: []
AFFECTED_CONTRACTS: []
EXPECTED_RUNTIME_DELTA: none
SCHEMA_IMPACT: none
REPORT_SCHEMA_IMPACT: none
RISK: low # low | medium | high
COMPLEXITY: low # low | medium | high
ACCEPTANCE: [] # criterios identificados
VERIFICATION_MATRIX:
  - criterion: "AC-01"
    contract: ""
    evidence: [] # evidencia prevista; no afirma resultado
    verification_level: focal
VERIFICATION:
  FOCAL: required
  INTEGRATED_GATE: not_required
  PACKAGING: not_required
  SECURITY: not_required
  VISUAL: not_required
  EXTERNAL_ACCEPTANCE: not_required
VERIFICATION_RESULTS: [] # al cerrar; un registro por nivel comprobado
# Ejemplo de registro conditional (campos obligatorios para ese caso):
# - level: FOCAL
#   condition: "criterio que determina la aplicabilidad"
#   condition_met: unknown # true | false | unknown
#   result: BLOCKED # PASS | FAIL | NOT_RUN | NOT_APPLICABLE | BLOCKED
#   evidence: [] # evidencia real de ejecución o causa de no ejecución
EXTERNAL_ACCEPTANCE_PROVIDER: # distinto del nivel VERIFICATION.EXTERNAL_ACCEPTANCE
  actor_or_system: none # quién proporciona la aceptación, si aplica
  artifact_or_evidence: [] # qué la acredita; prevista o real, indicarlo
EXECUTION_BOUNDARY:
  FILESYSTEM: workspace-write # o read-only
  NETWORK: denied
  REMOTE_GIT: denied
  CREDENTIALS: none
  REAL_DATA: denied
  COMMIT: denied
  TAG: denied
  PUBLISH: denied
CONTEXT_MANIFEST: docs/tasks/CONTEXT_MANIFEST_TEMPLATE.md
DELIVERABLE: ""
```

`VERIFICATION` declara niveles aplicables (`required`, `not_required` o
`conditional`); [TESTING.md](../TESTING.md) define su significado y resultados.
La matriz enlaza cada criterio importante con contrato y evidencia prevista.
Cada nivel `conditional` debe declarar su condición y, al cerrar, registrar su
evaluación y resultado en `VERIFICATION_RESULTS`. Nunca declarar `PASS` sin
haber ejecutado la verificación. `VERIFICATION.EXTERNAL_ACCEPTANCE` declara el
nivel; `EXTERNAL_ACCEPTANCE_PROVIDER` identifica el actor/sistema y la evidencia
que proporcionan esa aceptación. Registrar ejecución, verificación y aceptación
por separado al cerrar.
