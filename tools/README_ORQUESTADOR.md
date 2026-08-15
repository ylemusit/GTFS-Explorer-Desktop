# Orquestador del plan maestro

`plan_orchestrator.ps1` ejecuta como máximo una tarea del plan por sesión independiente de Codex. Calcula las dependencias desde `docs/PLAN_MAESTRO_CONSTRUCCION.md`, conserva el estado en `docs/TASK_STATUS.json` y detiene la cadena ante cualquier bloqueo o evidencia incompleta.

## Requisitos

- PowerShell 7 o posterior.
- Codex CLI autenticado y su binario nativo `codex.exe` disponible en `PATH`.
- Repositorio Git disponible.

El script usa la revisión automática de permisos de Codex (`--approve-for-me`); si se desactiva con `-NoAutoApprove`, limita la sesión a `workspace-write`. No combina ambas opciones porque la CLI las define como excluyentes. No hace commits, no publica, no despliega y no autoriza compras. Los artefactos de cada sesión se guardan localmente en `.codex-runs/`, que Git ignora.

Todas las sesiones se abren con los parámetros explícitos registrados en `docs/TASK_STATUS.json`, independientemente de los valores globales de Codex. El ejecutor se cambia únicamente con `-Action Configure` y nunca mientras haya una tarea en curso.

- Modelo actual recomendado: `gpt-5.6-terra` (Terra).
- Razonamiento: `medium` (Medio).

Cada carpeta de ejecución contiene `invocation.json`, `process.json`, `events.jsonl`, `stderr.log` y el resultado estructurado. `process.json` registra PID, heartbeat y timeout; los eventos y errores se escriben mientras Codex trabaja. Una tarea dispone de 60 minutos por defecto, configurable con `-TaskTimeoutMinutes`.

## Comandos

Validar el orquestador y el plan:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Validate
```

Cambiar explícitamente el ejecutor cuando no haya tareas activas:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Configure -Model gpt-5.6-terra -ReasoningEffort medium
```

Consultar estados y la siguiente tarea disponible:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Status
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Next
```

Monitor de solo lectura, con tareas pendientes, ejecutadas, bloqueadas y la tarea activa con PID/heartbeat:

```powershell
pwsh -NoProfile -File .\tools\task_monitor.ps1
pwsh -NoProfile -File .\tools\task_monitor.ps1 -Watch -RefreshSeconds 5
```

`Ctrl+C` detiene únicamente el monitor, nunca una ejecución del orquestador.

Simular la selección sin abrir una sesión de Codex ni modificar estados:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Run -MaxTasks 1 -DryRun
```

Ejecutar exactamente la siguiente tarea `READY`:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Run -MaxTasks 1
```

La ejecución continua se solicita expresamente con `-MaxTasks 0`. Se detiene al encontrar un bloqueo, una respuesta inválida, una prueba no superada, un criterio no demostrado o una puerta `T070 NO_GO`.

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Run -MaxTasks 0
```

Una tarea interrumpida o bloqueada nunca se reanuda automáticamente. Después de revisar sus cambios y el registro de `docs/TAREAS_PENDIENTES.md`, puede volver a habilitarse explícitamente:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Retry -TaskId T001
```

Si el controlador fue interrumpido, `Recover` comprueba primero que no siga vivo ni el controlador ni un proceso Codex registrado. Solo entonces elimina un lock huérfano, marca los runs incompletos como abandonados y convierte cualquier tarea `IN_PROGRESS` en `BLOCKED` para exigir revisión y `Retry` explícito:

```powershell
pwsh -NoProfile -File .\tools\plan_orchestrator.ps1 -Action Recover
```

Un resultado `DONE` no se acepta únicamente por la declaración del agente: el controlador vuelve a ejecutar `tools/check.ps1` y conserva la salida en `controller-check.log`. También rechaza rutas absolutas o exteriores al repositorio en `files_changed`.

Propietario y autor: Yeison Arbey Carrillo Lemus.

Todos los derechos reservados.
