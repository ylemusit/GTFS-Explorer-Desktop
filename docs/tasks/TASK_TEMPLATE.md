# Task descriptor template

```yaml
TASK_ID: ""
TITLE: ""
GOAL: ""
SCOPE: []
OUT_OF_SCOPE: []
ACCEPTANCE: []
RISK: low | medium | high
MODEL: luna | terra | sol | astra-with-explicit-approval
REASONING: medium | high-with-justification
REQUIRED_CONTEXT: docs/tasks/CONTEXT_MANIFEST_TEMPLATE.md
FILES_EXPECTED: []
TEST_POLICY: focal | integrated-final-gate
DELIVERABLE: ""
TELEMETRY:
  REQUIRED: true
  START: "node C:\\Users\\yeiso\\.codex\\task-telemetry.mjs start <TASK_ID>"
  END: "node C:\\Users\\yeiso\\.codex\\task-telemetry.mjs end <TASK_ID> --status PASS|PARTIAL|BLOCKED"
  SENSITIVE_CONTENT_EXPORTED: false
```

Breve, concreto y suficiente para una sola tarea.
