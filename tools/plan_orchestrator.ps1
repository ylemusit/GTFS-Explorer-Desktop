#Requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet('Initialize', 'Configure', 'Validate', 'Status', 'Next', 'Run', 'Retry', 'Recover')]
    [string]$Action = 'Status',

    [ValidateRange(0, 1000)]
    [int]$MaxTasks = 1,

    [ValidatePattern('^T\d{3}$')]
    [string]$TaskId,

    [ValidateSet('gpt-5.6-luna', 'gpt-5.6-terra')]
    [string]$Model,

    [ValidateSet('low', 'medium', 'high', 'xhigh', 'max')]
    [string]$ReasoningEffort,

    [ValidateRange(1, 1440)]
    [int]$TaskTimeoutMinutes = 60,

    [ValidateRange(1, 120)]
    [int]$ControllerCheckTimeoutMinutes = 20,

    [switch]$DryRun,
    [switch]$NoAutoApprove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RepositoryRoot = Split-Path -Parent $PSScriptRoot
$script:PlanPath = Join-Path $script:RepositoryRoot 'docs\PLAN_MAESTRO_CONSTRUCCION.md'
$script:CurrentStatePath = Join-Path $script:RepositoryRoot 'docs\CURRENT_STATE.md'
$script:PendingPath = Join-Path $script:RepositoryRoot 'docs\TAREAS_PENDIENTES.md'
$script:StatePath = Join-Path $script:RepositoryRoot 'docs\TASK_STATUS.json'
$script:SchemaPath = Join-Path $PSScriptRoot 'task_result.schema.json'
$script:RunsRoot = Join-Path $script:RepositoryRoot '.codex-runs'
$script:Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$script:SupportedCodexModels = @('gpt-5.6-luna', 'gpt-5.6-terra')
$script:SupportedReasoningEfforts = @('low', 'medium', 'high', 'xhigh', 'max')
$script:DefaultCodexModel = 'gpt-5.6-terra'
$script:DefaultCodexReasoningEffort = 'medium'
$script:LastInvocationRunDirectory = $null

$storedExecutor = $null
if (Test-Path -LiteralPath $script:StatePath) {
    try {
        $storedState = Get-Content -LiteralPath $script:StatePath -Raw | ConvertFrom-Json
        if ($storedState.PSObject.Properties.Name -contains 'executor') {
            $storedExecutor = $storedState.executor
        }
    }
    catch {
        throw "No se pudo leer la configuración del ejecutor en TASK_STATUS.json: $($_.Exception.Message)"
    }
}

$script:CodexModel = if ($PSBoundParameters.ContainsKey('Model')) {
    $Model
}
elseif ($null -ne $storedExecutor) {
    $storedExecutor.model
}
else {
    $script:DefaultCodexModel
}
$script:CodexReasoningEffort = if ($PSBoundParameters.ContainsKey('ReasoningEffort')) {
    $ReasoningEffort
}
elseif ($null -ne $storedExecutor) {
    $storedExecutor.reasoning_effort
}
else {
    $script:DefaultCodexReasoningEffort
}

function Write-Utf8Atomic {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [AllowEmptyString()] [string]$Content
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    }

    $temporaryPath = Join-Path $directory ('.tmp-' + [guid]::NewGuid().ToString('N'))
    try {
        [System.IO.File]::WriteAllText($temporaryPath, $Content, $script:Utf8NoBom)
        [System.IO.File]::Move($temporaryPath, $Path, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory)] [string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-OrchestratorLockInfo {
    $lockPath = Join-Path $script:RunsRoot 'orchestrator.lock'
    if (-not (Test-Path -LiteralPath $lockPath)) {
        return [pscustomobject]@{
            exists = $false
            valid = $true
            active = $false
            path = $lockPath
            process_id = $null
            started_at = $null
        }
    }

    $values = @{}
    foreach ($line in (Get-Content -LiteralPath $lockPath)) {
        if ($line -match '^(?<key>[a-z_]+)=(?<value>.+)$') {
            $values[$Matches.key] = $Matches.value
        }
    }

    $lockPid = 0
    $isValid = $values.ContainsKey('pid') -and
        [int]::TryParse([string]$values.pid, [ref]$lockPid) -and
        $lockPid -gt 0
    $active = $false
    if ($isValid) {
        $active = $null -ne (Get-Process -Id $lockPid -ErrorAction SilentlyContinue)
    }

    return [pscustomobject]@{
        exists = $true
        valid = $isValid
        active = $active
        path = $lockPath
        process_id = if ($isValid) { $lockPid } else { $null }
        started_at = if ($values.ContainsKey('started_at')) { $values.started_at } else { $null }
    }
}

function Get-ActiveCodexChildren {
    if (-not (Test-Path -LiteralPath $script:RunsRoot)) {
        return @()
    }

    $activeChildren = [System.Collections.Generic.List[object]]::new()
    foreach ($processFile in (Get-ChildItem -LiteralPath $script:RunsRoot -Filter 'process.json' -File -Recurse -ErrorAction SilentlyContinue)) {
        try {
            $metadata = Get-Content -LiteralPath $processFile.FullName -Raw | ConvertFrom-Json
        }
        catch {
            continue
        }
        if (
            $metadata.PSObject.Properties.Name -notcontains 'status' -or
            $metadata.PSObject.Properties.Name -notcontains 'child_pid' -or
            $metadata.status -ne 'RUNNING' -or
            $null -eq $metadata.child_pid
        ) {
            continue
        }
        $childProcess = Get-Process -Id ([int]$metadata.child_pid) -ErrorAction SilentlyContinue
        if ($null -ne $childProcess) {
            $activeChildren.Add([pscustomobject]@{
                process_id = [int]$metadata.child_pid
                task_id = $metadata.task_id
                process_file = $processFile.FullName
            })
        }
    }
    return @($activeChildren)
}

function Get-PlanTasks {
    if (-not (Test-Path -LiteralPath $script:PlanPath)) {
        throw "No existe el plan maestro: $script:PlanPath"
    }

    $planText = Get-Content -LiteralPath $script:PlanPath -Raw
    $pattern = '(?ms)^#### (?<id>[TF]\d{3}) — (?<title>[^\r\n]+)\r?\n(?<body>.*?)(?=^#### [TF]\d{3} — |^### Fase |^## |\z)'
    $matches = [regex]::Matches($planText, $pattern)
    $tasks = [System.Collections.Generic.List[object]]::new()

    foreach ($match in $matches) {
        $id = $match.Groups['id'].Value
        if (-not $id.StartsWith('T', [System.StringComparison]::Ordinal)) {
            continue
        }

        $body = $match.Groups['body'].Value.TrimEnd()
        $dependencyMatch = [regex]::Match(
            $body,
            '(?m)^- \*\*Dependencias:\*\*\s*(?<value>.+?)\s*$'
        )
        if (-not $dependencyMatch.Success) {
            throw "La tarea $id no declara dependencias."
        }

        $tasks.Add([pscustomobject][ordered]@{
            id = $id
            title = $match.Groups['title'].Value.Trim()
            dependency_text = $dependencyMatch.Groups['value'].Value.Trim()
            block = "#### $id — $($match.Groups['title'].Value.Trim())`n`n$body"
            order = $tasks.Count
        })
    }

    if ($tasks.Count -eq 0) {
        throw 'No se encontraron tareas Txxx en el plan maestro.'
    }

    $taskById = @{}
    foreach ($task in $tasks) {
        if ($taskById.ContainsKey($task.id)) {
            throw "La tarea $($task.id) está duplicada en el plan."
        }
        $taskById[$task.id] = $task
    }

    foreach ($task in $tasks) {
        $dependencies = [System.Collections.Generic.List[object]]::new()
        $dependencyMatches = [regex]::Matches(
            $task.dependency_text,
            '(?<start>T\d{3})(?:\s*[–-]\s*(?<end>T?\d{3}))?'
        )

        foreach ($dependencyMatch in $dependencyMatches) {
            $startId = $dependencyMatch.Groups['start'].Value
            $dependencyIds = [System.Collections.Generic.List[string]]::new()

            if ($dependencyMatch.Groups['end'].Success) {
                $startNumber = [int]$startId.Substring(1)
                $endText = $dependencyMatch.Groups['end'].Value
                $endNumber = [int]$endText.TrimStart('T')
                if ($endNumber -lt $startNumber) {
                    throw "Rango de dependencias inválido en $($task.id): $($dependencyMatch.Value)"
                }

                foreach ($candidate in $tasks) {
                    $candidateNumber = [int]$candidate.id.Substring(1)
                    if ($candidateNumber -ge $startNumber -and $candidateNumber -le $endNumber) {
                        $dependencyIds.Add($candidate.id)
                    }
                }
            }
            else {
                $dependencyIds.Add($startId)
            }

            foreach ($dependencyId in $dependencyIds) {
                $requiresGo = $task.dependency_text -match ('(?i)\b' + [regex]::Escape($dependencyId) + '\s+GO\b')
                if (-not ($dependencies | Where-Object { $_.id -eq $dependencyId })) {
                    $dependencies.Add([pscustomobject][ordered]@{
                        id = $dependencyId
                        required_gate = if ($requiresGo) { 'GO' } else { 'ANY' }
                    })
                }
            }
        }

        Add-Member -InputObject $task -NotePropertyName dependencies -NotePropertyValue @($dependencies)
    }

    return @($tasks)
}

function Test-PlanTasks {
    param([Parameter(Mandatory)] [object[]]$Tasks)

    $taskById = @{}
    foreach ($task in $Tasks) {
        $taskById[$task.id] = $task
    }

    foreach ($task in $Tasks) {
        foreach ($dependency in $task.dependencies) {
            if (-not $taskById.ContainsKey($dependency.id)) {
                throw "La tarea $($task.id) depende de una tarea inexistente: $($dependency.id)."
            }
            if ($dependency.id -eq $task.id) {
                throw "La tarea $($task.id) depende de sí misma."
            }
        }
    }

    $visiting = @{}
    $visited = @{}
    function Visit-Task {
        param([string]$Id)
        if ($visiting.ContainsKey($Id)) {
            throw "El plan contiene un ciclo de dependencias que incluye $Id."
        }
        if ($visited.ContainsKey($Id)) {
            return
        }

        $visiting[$Id] = $true
        foreach ($dependency in $taskById[$Id].dependencies) {
            Visit-Task -Id $dependency.id
        }
        $visiting.Remove($Id)
        $visited[$Id] = $true
    }

    foreach ($task in $Tasks) {
        Visit-Task -Id $task.id
    }
}

function New-TaskState {
    param([Parameter(Mandatory)] [object[]]$Tasks)

    $now = [DateTimeOffset]::Now.ToString('o')
    $taskStates = foreach ($task in $Tasks) {
        $isDocumentBaseline = $task.id -eq 'T000'
        [pscustomobject][ordered]@{
            id = $task.id
            title = $task.title
            status = if ($isDocumentBaseline) { 'DONE' } else { 'PENDING' }
            gate_decision = 'NOT_APPLICABLE'
            started_at = $null
            completed_at = if ($isDocumentBaseline) { $now } else { $null }
            session_id = $null
            summary = if ($isDocumentBaseline) { 'Línea base documental declarada como completada en docs/CURRENT_STATE.md.' } else { $null }
            blocker = $null
        }
    }

    $state = [pscustomobject][ordered]@{
        schema_version = 1
        plan_sha256 = Get-FileSha256 -Path $script:PlanPath
        initialized_at = $now
        updated_at = $now
        executor = [pscustomobject][ordered]@{
            model = $script:CodexModel
            reasoning_effort = $script:CodexReasoningEffort
        }
        tasks = @($taskStates)
    }
    Update-ReadyStates -State $state -Tasks $Tasks
    return $state
}

function Save-TaskState {
    param([Parameter(Mandatory)] [object]$State)
    $State.updated_at = [DateTimeOffset]::Now.ToString('o')
    $json = $State | ConvertTo-Json -Depth 12
    Write-Utf8Atomic -Path $script:StatePath -Content ($json + "`n")
}

function Read-TaskState {
    param(
        [Parameter(Mandatory)] [object[]]$Tasks,
        [switch]$AllowExecutorMismatch
    )

    if (-not (Test-Path -LiteralPath $script:StatePath)) {
        throw "No existe $script:StatePath. Ejecuta primero: .\tools\plan_orchestrator.ps1 -Action Initialize"
    }

    $state = Get-Content -LiteralPath $script:StatePath -Raw | ConvertFrom-Json
    if ($state.schema_version -ne 1) {
        throw "Versión de estado no soportada: $($state.schema_version)."
    }
    if ($state.PSObject.Properties.Name -notcontains 'executor') {
        throw 'TASK_STATUS.json no declara el modelo y el razonamiento obligatorios del ejecutor.'
    }
    if ($state.executor.model -notin $script:SupportedCodexModels) {
        throw "TASK_STATUS.json declara un modelo no soportado: $($state.executor.model)."
    }
    if ($state.executor.reasoning_effort -notin $script:SupportedReasoningEfforts) {
        throw "TASK_STATUS.json declara un razonamiento no soportado: $($state.executor.reasoning_effort)."
    }
    if (
        -not $AllowExecutorMismatch -and
        ($state.executor.model -ne $script:CodexModel -or
            $state.executor.reasoning_effort -ne $script:CodexReasoningEffort)
    ) {
        throw "TASK_STATUS.json usa $($state.executor.model)/$($state.executor.reasoning_effort); usa -Action Configure para cambiar el ejecutor."
    }
    if ($state.plan_sha256 -ne (Get-FileSha256 -Path $script:PlanPath)) {
        throw 'El plan maestro ha cambiado desde la inicialización. Revisa y reconcilia TASK_STATUS.json antes de continuar.'
    }

    $planIds = @($Tasks | ForEach-Object { $_.id })
    $stateIds = @($state.tasks | ForEach-Object { $_.id })
    if (@(Compare-Object -ReferenceObject $planIds -DifferenceObject $stateIds).Count -ne 0) {
        throw 'TASK_STATUS.json no contiene exactamente las tareas vigentes del plan maestro.'
    }

    return $state
}

function Get-StateTaskById {
    param(
        [Parameter(Mandatory)] [object]$State,
        [Parameter(Mandatory)] [string]$Id
    )
    $stateTask = $State.tasks | Where-Object { $_.id -eq $Id } | Select-Object -First 1
    if ($null -eq $stateTask) {
        throw "No existe la tarea $Id en el registro de estado."
    }
    return $stateTask
}

function Test-DependenciesSatisfied {
    param(
        [Parameter(Mandatory)] [object]$Task,
        [Parameter(Mandatory)] [object]$State
    )

    foreach ($dependency in $Task.dependencies) {
        $dependencyState = Get-StateTaskById -State $State -Id $dependency.id
        if ($dependencyState.status -ne 'DONE') {
            return $false
        }
        if ($dependency.required_gate -eq 'GO' -and $dependencyState.gate_decision -ne 'GO') {
            return $false
        }
    }
    return $true
}

function Update-ReadyStates {
    param(
        [Parameter(Mandatory)] [object]$State,
        [Parameter(Mandatory)] [object[]]$Tasks
    )

    foreach ($task in $Tasks) {
        $stateTask = Get-StateTaskById -State $State -Id $task.id
        if ($stateTask.status -in @('DONE', 'IN_PROGRESS', 'BLOCKED')) {
            continue
        }
        $stateTask.status = if (Test-DependenciesSatisfied -Task $task -State $State) { 'READY' } else { 'PENDING' }
    }
}

function Get-ReadyPlanTasks {
    param(
        [Parameter(Mandatory)] [object[]]$Tasks,
        [Parameter(Mandatory)] [object]$State
    )

    Update-ReadyStates -State $State -Tasks $Tasks
    return @($Tasks | Where-Object {
        (Get-StateTaskById -State $State -Id $_.id).status -eq 'READY'
    } | Sort-Object order)
}

function Get-TaskPrompt {
    param(
        [Parameter(Mandatory)] [object]$Task,
        [Parameter(Mandatory)] [object]$State
    )

    $dependencySummary = if ($Task.dependencies.Count -eq 0) {
        'Ninguna.'
    }
    else {
        ($Task.dependencies | ForEach-Object {
            $dependencyState = Get-StateTaskById -State $State -Id $_.id
            "$($_.id)=$($dependencyState.status), gate=$($dependencyState.gate_decision)"
        }) -join '; '
    }

    return @"
Objetivo único: ejecutar profesionalmente la tarea $($Task.id) del plan maestro de GTFS Explorer Desktop.

Esta sesión se ha iniciado explícitamente con el modelo $script:CodexModel y razonamiento $script:CodexReasoningEffort.

Reglas obligatorias:
- Lee AGENTS.md, docs/SESSION_CONTEXT.md y el descriptor de tarea antes de modificar.
- La ficha exacta de la tarea se incluye al final. Consulta otros documentos solo si la ficha lo requiere.
- Ejecuta únicamente $($Task.id). No empieces ni prepares la siguiente tarea.
- Conserva todo trabajo existente y no reviertas cambios ajenos.
- No uses subagentes.
- Implementa el cambio mínimo completo y mantenible.
- Ejecuta las pruebas de la ficha y las comprobaciones proporcionales necesarias.
- Si una comprobación local falla únicamente por el sandbox o una ACL de temporales, reintenta una vez el mismo comando acotado mediante el mecanismo de permisos ampliados; no lo trates como una nueva autorización funcional.
- Ejecuta git diff --check y git status --short si Git está disponible.
- No declares DONE si queda un criterio sin demostrar o una prueba necesaria sin ejecutar.
- No hagas commit, push, publicación, despliegue ni compras.
- Detente con BLOCKED ante costes, credenciales, permisos ampliados, datos sensibles, terceros, decisiones de contrato/seguridad/licencia/persistencia o cualquier criterio imposible de demostrar.
- Si dos intentos equivalentes fallan, cambia de hipótesis; no repitas en bucle.
- Actualiza docs/CURRENT_STATE.md solo si el estado material del producto cambia.
- La respuesta final debe cumplir exactamente el esquema JSON solicitado por el controlador.
- Para DONE: blocker.present=false, todas las pruebas deben estar PASSED y todos los criterios demonstrated=true.
- Para BLOCKED: describe lo completado, el problema, la evidencia y la acción concreta necesaria.
- gate_decision debe ser NOT_APPLICABLE salvo que la ficha exija expresamente GO o NO-GO.

Dependencias registradas: $dependencySummary

Ficha exacta:

$($Task.block)
"@
}

function Get-CodexCommand {
    $application = Get-Command codex.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $application -or $application.CommandType -ne 'Application') {
        throw 'No se encontró el binario nativo codex.exe. El orquestador no usa wrappers .cmd porque el prompt debe viajar como un argumento literal seguro.'
    }
    return $application.Source
}

function Complete-TaskWithoutPipelineOutput {
    param([Parameter(Mandatory)] [System.Threading.Tasks.Task]$Task)

    # PowerShell materializa Task.GetResult() como VoidTaskResult. Si se deja en
    # el pipeline, la función llamadora devuelve ese valor además de su contrato.
    $null = $Task.GetAwaiter().GetResult()
}

function Invoke-CodexTask {
    param(
        [Parameter(Mandatory)] [object]$Task,
        [Parameter(Mandatory)] [object]$State
    )

    if (-not (Test-Path -LiteralPath $script:SchemaPath)) {
        throw "No existe el esquema de salida: $script:SchemaPath"
    }

    $timestamp = [DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss')
    $runDirectory = Join-Path $script:RunsRoot "$($Task.id)-$timestamp"
    [System.IO.Directory]::CreateDirectory($runDirectory) | Out-Null
    $script:LastInvocationRunDirectory = $runDirectory

    $prompt = Get-TaskPrompt -Task $Task -State $State
    $promptPath = Join-Path $runDirectory 'prompt.txt'
    $eventsPath = Join-Path $runDirectory 'events.jsonl'
    $stderrPath = Join-Path $runDirectory 'stderr.log'
    $resultPath = Join-Path $runDirectory 'result.json'
    $processPath = Join-Path $runDirectory 'process.json'
    $beforeStatusPath = Join-Path $runDirectory 'git-status-before.txt'
    $afterStatusPath = Join-Path $runDirectory 'git-status-after.txt'
    $invocationPath = Join-Path $runDirectory 'invocation.json'

    Write-Utf8Atomic -Path $promptPath -Content $prompt
    $invocationMetadata = [pscustomobject][ordered]@{
        task_id = $Task.id
        model = $script:CodexModel
        reasoning_effort = $script:CodexReasoningEffort
        execution_policy = if ($NoAutoApprove) { 'workspace-write' } else { 'approve-for-me' }
        timeout_minutes = $TaskTimeoutMinutes
        started_at = [DateTimeOffset]::Now.ToString('o')
    }
    Write-Utf8Atomic -Path $invocationPath -Content (($invocationMetadata | ConvertTo-Json -Depth 4) + "`n")
    $beforeStatus = (& git -C $script:RepositoryRoot status --short --untracked-files=all 2>&1 | Out-String)
    Write-Utf8Atomic -Path $beforeStatusPath -Content $beforeStatus

    $arguments = [System.Collections.Generic.List[string]]::new()
    foreach ($argument in @(
        'exec',
        '--json',
        '--model', $script:CodexModel,
        '--config', ('model_reasoning_effort="' + $script:CodexReasoningEffort + '"'),
        '--cd', $script:RepositoryRoot,
        '--output-schema', $script:SchemaPath,
        '--output-last-message', $resultPath
    )) {
        $arguments.Add($argument)
    }
    if (-not $NoAutoApprove) {
        $arguments.Add('--approve-for-me')
    }
    else {
        $arguments.Add('--sandbox')
        $arguments.Add('workspace-write')
    }
    $arguments.Add($prompt)

    $processStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $processStartInfo.FileName = Get-CodexCommand
    $processStartInfo.WorkingDirectory = $script:RepositoryRoot
    $processStartInfo.UseShellExecute = $false
    $processStartInfo.CreateNoWindow = $true
    $processStartInfo.RedirectStandardOutput = $true
    $processStartInfo.RedirectStandardError = $true
    foreach ($argument in $arguments) {
        $processStartInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $processStartInfo
    if (-not $process.Start()) {
        throw "No se pudo iniciar Codex para $($Task.id)."
    }

    $processMetadata = [pscustomobject][ordered]@{
        task_id = $Task.id
        status = 'RUNNING'
        controller_pid = $PID
        child_pid = $process.Id
        timeout_minutes = $TaskTimeoutMinutes
        started_at = [DateTimeOffset]::Now.ToString('o')
        last_heartbeat_at = [DateTimeOffset]::Now.ToString('o')
        timed_out = $false
        exit_code = $null
        stdout_characters = 0
        stderr_characters = 0
        finished_at = $null
    }
    Write-Utf8Atomic -Path $processPath -Content (($processMetadata | ConvertTo-Json -Depth 4) + "`n")

    $stdoutStream = $null
    $stderrStream = $null
    $stdoutCopyTask = $null
    $stderrCopyTask = $null
    $timedOut = $false
    try {
        $stdoutStream = [System.IO.FileStream]::new(
            $eventsPath,
            [System.IO.FileMode]::Create,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read,
            4096,
            [System.IO.FileOptions]::Asynchronous
        )
        $stderrStream = [System.IO.FileStream]::new(
            $stderrPath,
            [System.IO.FileMode]::Create,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::Read,
            4096,
            [System.IO.FileOptions]::Asynchronous
        )
        $stdoutCopyTask = $process.StandardOutput.BaseStream.CopyToAsync($stdoutStream)
        $stderrCopyTask = $process.StandardError.BaseStream.CopyToAsync($stderrStream)

        $deadline = [DateTimeOffset]::UtcNow.AddMinutes($TaskTimeoutMinutes)
        $nextHeartbeat = [DateTimeOffset]::UtcNow.AddSeconds(5)
        while (-not $process.WaitForExit(1000)) {
            $now = [DateTimeOffset]::UtcNow
            if ($now -ge $deadline) {
                $timedOut = $true
                $processMetadata.timed_out = $true
                $processMetadata.status = 'TERMINATING'
                $processMetadata.last_heartbeat_at = [DateTimeOffset]::Now.ToString('o')
                Write-Utf8Atomic -Path $processPath -Content (($processMetadata | ConvertTo-Json -Depth 4) + "`n")
                try {
                    $process.Kill($true)
                }
                catch {
                    $process.Kill()
                }
                if (-not $process.WaitForExit(10000)) {
                    throw "Codex superó $TaskTimeoutMinutes minutos y no se pudo detener su árbol de procesos."
                }
                break
            }
            if ($now -ge $nextHeartbeat) {
                $processMetadata.last_heartbeat_at = [DateTimeOffset]::Now.ToString('o')
                Write-Utf8Atomic -Path $processPath -Content (($processMetadata | ConvertTo-Json -Depth 4) + "`n")
                $nextHeartbeat = $now.AddSeconds(5)
            }
        }

        $process.WaitForExit()
        Complete-TaskWithoutPipelineOutput -Task $stdoutCopyTask
        Complete-TaskWithoutPipelineOutput -Task $stderrCopyTask
    }
    finally {
        if ($null -ne $stdoutStream) {
            $stdoutStream.Dispose()
        }
        if ($null -ne $stderrStream) {
            $stderrStream.Dispose()
        }
    }

    $stdout = if (Test-Path -LiteralPath $eventsPath) {
        [System.IO.File]::ReadAllText($eventsPath, $script:Utf8NoBom)
    }
    else {
        ''
    }
    $stderr = if (Test-Path -LiteralPath $stderrPath) {
        [System.IO.File]::ReadAllText($stderrPath, $script:Utf8NoBom)
    }
    else {
        ''
    }
    $processMetadata.status = if ($timedOut) { 'TIMED_OUT' } else { 'EXITED' }
    $processMetadata.exit_code = $process.ExitCode
    $processMetadata.stdout_characters = $stdout.Length
    $processMetadata.stderr_characters = $stderr.Length
    $processMetadata.last_heartbeat_at = [DateTimeOffset]::Now.ToString('o')
    $processMetadata.finished_at = [DateTimeOffset]::Now.ToString('o')
    Write-Utf8Atomic -Path $processPath -Content (($processMetadata | ConvertTo-Json -Depth 4) + "`n")

    $afterStatus = (& git -C $script:RepositoryRoot status --short --untracked-files=all 2>&1 | Out-String)
    Write-Utf8Atomic -Path $afterStatusPath -Content $afterStatus

    $sessionId = $null
    foreach ($line in ($stdout -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            continue
        }
        try {
            $event = $line | ConvertFrom-Json
            if ($event.type -eq 'thread.started') {
                $sessionId = $event.thread_id
                break
            }
        }
        catch {
            continue
        }
    }

    return [pscustomobject][ordered]@{
        exit_code = $process.ExitCode
        session_id = $sessionId
        run_directory = $runDirectory
        result_path = $resultPath
        stderr = $stderr
        timed_out = $timedOut
    }
}

function Invoke-ControllerCheck {
    param([Parameter(Mandatory)] [string]$RunDirectory)

    $checkPath = Join-Path $PSScriptRoot 'check.ps1'
    $logPath = Join-Path $RunDirectory 'controller-check.log'
    if (-not (Test-Path -LiteralPath $checkPath)) {
        return [pscustomobject]@{
            passed = $false
            timed_out = $false
            exit_code = $null
            log_path = $logPath
            output = "No existe el flujo canónico: $checkPath"
        }
    }

    $pwshCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $pwshCommand) {
        return [pscustomobject]@{
            passed = $false
            timed_out = $false
            exit_code = $null
            log_path = $logPath
            output = 'No se encontró pwsh.exe para ejecutar el control independiente.'
        }
    }

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $pwshCommand.Source
    $startInfo.WorkingDirectory = $script:RepositoryRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $checkPath)) {
        $startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw 'No se pudo iniciar el control independiente del repositorio.'
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $timedOut = -not $process.WaitForExit($ControllerCheckTimeoutMinutes * 60 * 1000)
    if ($timedOut) {
        try {
            $process.Kill($true)
        }
        catch {
            $process.Kill()
        }
        $process.WaitForExit(10000) | Out-Null
    }
    else {
        $process.WaitForExit()
    }

    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $combinedOutput = @(
        if (-not [string]::IsNullOrWhiteSpace($stdout)) { $stdout.TrimEnd() }
        if (-not [string]::IsNullOrWhiteSpace($stderr)) { $stderr.TrimEnd() }
    ) -join "`n"
    Write-Utf8Atomic -Path $logPath -Content ($combinedOutput + "`n")

    return [pscustomobject]@{
        passed = -not $timedOut -and $process.ExitCode -eq 0
        timed_out = $timedOut
        exit_code = $process.ExitCode
        log_path = $logPath
        output = $combinedOutput
    }
}

function Get-ReportedPathErrors {
    param([Parameter(Mandatory)] [object]$Result)

    $errors = [System.Collections.Generic.List[string]]::new()
    $rootPrefix = $script:RepositoryRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    foreach ($reportedPath in @($Result.files_changed)) {
        if ([System.IO.Path]::IsPathRooted($reportedPath)) {
            $errors.Add("files_changed contiene una ruta absoluta: $reportedPath")
            continue
        }
        try {
            $fullPath = [System.IO.Path]::GetFullPath((Join-Path $script:RepositoryRoot $reportedPath))
        }
        catch {
            $errors.Add("files_changed contiene una ruta inválida: $reportedPath")
            continue
        }
        if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $errors.Add("files_changed escapa del repositorio: $reportedPath")
        }
    }
    return @($errors)
}

function Test-TaskResult {
    param(
        [Parameter(Mandatory)] [object]$Task,
        [Parameter(Mandatory)] [object]$Invocation
    )

    $errors = [System.Collections.Generic.List[string]]::new()
    if ($Invocation.timed_out) {
        $errors.Add("Codex superó el timeout de $TaskTimeoutMinutes minutos.")
    }
    if ($Invocation.exit_code -ne 0) {
        $errors.Add("Codex terminó con código $($Invocation.exit_code).")
        if (-not [string]::IsNullOrWhiteSpace($Invocation.stderr)) {
            $stderrSummary = $Invocation.stderr.Trim()
            if ($stderrSummary.Length -gt 1000) {
                $stderrSummary = $stderrSummary.Substring(0, 1000) + '...'
            }
            $errors.Add("stderr: $stderrSummary")
        }
    }
    if (-not (Test-Path -LiteralPath $Invocation.result_path)) {
        $errors.Add('Codex no generó el resultado JSON final.')
        return [pscustomobject]@{ valid = $false; result = $null; errors = @($errors) }
    }

    $result = $null
    try {
        $result = Get-Content -LiteralPath $Invocation.result_path -Raw | ConvertFrom-Json
    }
    catch {
        $errors.Add("El resultado final no es JSON válido: $($_.Exception.Message)")
        return [pscustomobject]@{ valid = $false; result = $null; errors = @($errors) }
    }

    if ($result.task_id -ne $Task.id) {
        $errors.Add("El resultado corresponde a $($result.task_id), no a $($Task.id).")
    }
    foreach ($pathError in (Get-ReportedPathErrors -Result $result)) {
        $errors.Add($pathError)
    }
    if ($result.status -eq 'DONE') {
        if ($result.blocker.present) {
            $errors.Add('El resultado declara DONE pero también declara un bloqueo.')
        }
        if (@($result.tests | Where-Object { $_.status -ne 'PASSED' }).Count -gt 0) {
            $errors.Add('Hay pruebas fallidas o no ejecutadas en un resultado DONE.')
        }
        if (@($result.criteria | Where-Object { -not $_.demonstrated }).Count -gt 0) {
            $errors.Add('Hay criterios no demostrados en un resultado DONE.')
        }
        $controllerCheck = Invoke-ControllerCheck -RunDirectory $Invocation.run_directory
        if (-not $controllerCheck.passed) {
            $checkSummary = $controllerCheck.output
            if ($checkSummary.Length -gt 1500) {
                $checkSummary = $checkSummary.Substring(0, 1500) + '...'
            }
            if ($controllerCheck.timed_out) {
                $errors.Add("El control independiente superó $ControllerCheckTimeoutMinutes minutos. Log: $($controllerCheck.log_path)")
            }
            else {
                $errors.Add("El control independiente terminó con código $($controllerCheck.exit_code): $checkSummary")
            }
        }
    }
    elseif ($result.status -eq 'BLOCKED') {
        if (-not $result.blocker.present) {
            $errors.Add('El resultado declara BLOCKED sin describir un bloqueo.')
        }
    }
    else {
        $errors.Add("Estado final no soportado: $($result.status).")
    }

    if ($Task.id -eq 'T070' -and $result.status -eq 'DONE' -and $result.gate_decision -eq 'NOT_APPLICABLE') {
        $errors.Add('T070 debe terminar con una decisión GO o NO_GO.')
    }
    if ($Task.id -ne 'T070' -and $result.gate_decision -ne 'NOT_APPLICABLE') {
        $errors.Add("$($Task.id) no puede emitir una decisión de puerta del mapa.")
    }

    $diffCheckOutput = (& git -C $script:RepositoryRoot diff --check 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        $errors.Add("git diff --check falló: $($diffCheckOutput.Trim())")
    }

    return [pscustomobject]@{
        valid = $errors.Count -eq 0
        result = $result
        errors = @($errors)
    }
}

function Add-PendingEntry {
    param(
        [Parameter(Mandatory)] [object]$Task,
        [Parameter(Mandatory)] [string]$Status,
        [Parameter(Mandatory)] [string]$Problem,
        [string]$CompletedPart = 'No determinada.',
        [string]$RequiredAction = 'Revisar la evidencia y decidir cómo continuar.',
        [string]$RunDirectory = ''
    )

    $relativeRunDirectory = if ([string]::IsNullOrWhiteSpace($RunDirectory)) {
        'No disponible.'
    }
    else {
        [System.IO.Path]::GetRelativePath($script:RepositoryRoot, $RunDirectory).Replace('\', '/')
    }
    $safeProblem = $Problem.Trim()
    $safeCompletedPart = $CompletedPart.Trim()
    $safeRequiredAction = $RequiredAction.Trim()
    $entry = @"

## $($Task.id) — $($Task.title)

- **Fecha:** $([DateTimeOffset]::Now.ToString('o'))
- **Estado:** $Status
- **Parte completada:** $safeCompletedPart
- **Problema o criterio pendiente:** $safeProblem
- **Evidencia:** $relativeRunDirectory
- **Acción necesaria:** $safeRequiredAction
- **Dependencias afectadas:** el orquestador no ejecutará tareas que dependan directa o indirectamente de $($Task.id).
"@

    if (-not (Test-Path -LiteralPath $script:PendingPath)) {
        Write-Utf8Atomic -Path $script:PendingPath -Content "# Tareas pendientes y bloqueos`n`n<!-- ORCHESTRATOR_ENTRIES -->`n"
    }
    $pendingContent = Get-Content -LiteralPath $script:PendingPath -Raw
    $pendingContent = $pendingContent -replace '(?m)^Actualmente no hay tareas pendientes ni bloqueos registrados\.\r?\n\r?\n', ''
    $marker = '<!-- ORCHESTRATOR_ENTRIES -->'
    if ($pendingContent.Contains($marker, [System.StringComparison]::Ordinal)) {
        $pendingContent = $pendingContent.Replace($marker, ($entry.TrimEnd() + "`n`n" + $marker))
    }
    else {
        $pendingContent = $pendingContent.TrimEnd() + $entry + "`n"
    }
    Write-Utf8Atomic -Path $script:PendingPath -Content $pendingContent
}

function Invoke-OneTask {
    param(
        [Parameter(Mandatory)] [object]$Task,
        [Parameter(Mandatory)] [object]$State,
        [Parameter(Mandatory)] [object[]]$Tasks
    )

    $stateTask = Get-StateTaskById -State $State -Id $Task.id
    if ($stateTask.status -ne 'READY') {
        throw "La tarea $($Task.id) no está READY; estado actual: $($stateTask.status)."
    }

    if ($DryRun) {
        Write-Host "DRY-RUN: se ejecutaría $($Task.id) — $($Task.title)"
        return 'DRY_RUN'
    }

    $stateTask.status = 'IN_PROGRESS'
    $stateTask.started_at = [DateTimeOffset]::Now.ToString('o')
    Save-TaskState -State $State
    Write-Host "Iniciando $($Task.id) — $($Task.title)"

    $invocation = $null
    try {
        $invocation = Invoke-CodexTask -Task $Task -State $State
        $verification = Test-TaskResult -Task $Task -Invocation $invocation
    }
    catch {
        $problem = $_.Exception.Message
        $stateTask.status = 'BLOCKED'
        $stateTask.blocker = [pscustomobject]@{
            type = 'TECHNICAL'
            description = $problem
            required_action = 'Revisar el fallo del orquestador antes de reintentar.'
        }
        Save-TaskState -State $State
        $failureRunDirectory = if ($null -ne $invocation) { $invocation.run_directory } else { $script:LastInvocationRunDirectory }
        Add-PendingEntry -Task $Task -Status 'BLOCKED' -Problem $problem -RunDirectory $failureRunDirectory
        throw
    }

    if (-not $verification.valid) {
        $problem = $verification.errors -join ' '
        $stateTask.status = 'BLOCKED'
        $stateTask.session_id = $invocation.session_id
        $stateTask.blocker = [pscustomobject]@{
            type = 'TECHNICAL'
            description = $problem
            required_action = 'Revisar el resultado y los cambios parciales antes de reintentar.'
        }
        Save-TaskState -State $State
        Add-PendingEntry -Task $Task -Status 'BLOCKED' -Problem $problem -RunDirectory $invocation.run_directory
        Write-Error "$($Task.id) no superó la verificación del controlador: $problem"
    }

    $result = $verification.result
    $stateTask.session_id = $invocation.session_id
    $stateTask.summary = $result.summary
    $stateTask.gate_decision = $result.gate_decision

    if ($result.status -eq 'BLOCKED') {
        $stateTask.status = 'BLOCKED'
        $stateTask.blocker = $result.blocker
        Save-TaskState -State $State
        Add-PendingEntry -Task $Task -Status 'BLOCKED' -Problem $result.blocker.description -CompletedPart $result.summary -RequiredAction $result.blocker.required_action -RunDirectory $invocation.run_directory
        Write-Host "$($Task.id) quedó BLOCKED. La cadena se detiene."
        return 'BLOCKED'
    }

    $stateTask.status = 'DONE'
    $stateTask.completed_at = [DateTimeOffset]::Now.ToString('o')
    $stateTask.blocker = $null
    Update-ReadyStates -State $State -Tasks $Tasks
    Save-TaskState -State $State
    Write-Host "$($Task.id) quedó DONE y verificada."

    if ($Task.id -eq 'T070' -and $result.gate_decision -eq 'NO_GO') {
        Add-PendingEntry -Task $Task -Status 'DONE / NO_GO' -Problem 'El spike T070 concluyó NO_GO; T071–T075 no pueden continuar.' -CompletedPart $result.summary -RequiredAction 'Tomar una nueva decisión técnica documentada antes de reanudar la rama de mapas.' -RunDirectory $invocation.run_directory
        Write-Host 'T070 concluyó NO_GO. La cadena se detiene para una nueva decisión.'
        return 'BLOCKED'
    }

    return 'DONE'
}

function Enter-OrchestratorLock {
    if (-not (Test-Path -LiteralPath $script:RunsRoot)) {
        [System.IO.Directory]::CreateDirectory($script:RunsRoot) | Out-Null
    }
    $lockPath = Join-Path $script:RunsRoot 'orchestrator.lock'
    $existingLock = Get-OrchestratorLockInfo
    if ($existingLock.exists) {
        if (-not $existingLock.valid) {
            throw "El lock del orquestador no es válido. Revísalo y usa -Action Recover: $lockPath"
        }
        if ($existingLock.active) {
            throw "Ya existe un orquestador activo con PID $($existingLock.process_id): $lockPath"
        }
        throw "Existe un lock huérfano del PID $($existingLock.process_id). Usa -Action Recover antes de ejecutar tareas."
    }
    try {
        $stream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $writer = [System.IO.StreamWriter]::new($stream, $script:Utf8NoBom)
        $writer.WriteLine("pid=$PID")
        $writer.WriteLine("started_at=$([DateTimeOffset]::Now.ToString('o'))")
        $writer.Flush()
        return [pscustomobject]@{ path = $lockPath; stream = $stream; writer = $writer }
    }
    catch [System.IO.IOException] {
        throw "No se pudo adquirir el lock exclusivo del orquestador: $lockPath"
    }
}

function Exit-OrchestratorLock {
    param([object]$Lock)
    if ($null -eq $Lock) {
        return
    }
    $Lock.writer.Dispose()
    $Lock.stream.Dispose()
    if (Test-Path -LiteralPath $Lock.path) {
        Remove-Item -LiteralPath $Lock.path -Force
    }
}

$tasks = Get-PlanTasks
Test-PlanTasks -Tasks $tasks

switch ($Action) {
    'Initialize' {
        if (Test-Path -LiteralPath $script:StatePath) {
            throw "El registro ya existe: $script:StatePath. No se sobrescribe automáticamente."
        }
        $state = New-TaskState -Tasks $tasks
        Save-TaskState -State $state
        Write-Host "Registro inicial creado. T000=DONE; primera tarea READY: $((Get-ReadyPlanTasks -Tasks $tasks -State $state | Select-Object -First 1).id)"
        break
    }
    'Configure' {
        if (-not $PSBoundParameters.ContainsKey('Model') -and -not $PSBoundParameters.ContainsKey('ReasoningEffort')) {
            throw 'Configure requiere -Model, -ReasoningEffort o ambos.'
        }
        $state = Read-TaskState -Tasks $tasks -AllowExecutorMismatch
        $inProgress = @($state.tasks | Where-Object { $_.status -eq 'IN_PROGRESS' })
        if ($inProgress.Count -gt 0) {
            throw "No se cambia el ejecutor mientras haya tareas IN_PROGRESS: $($inProgress.id -join ', ')."
        }
        $lockInfo = Get-OrchestratorLockInfo
        if ($lockInfo.exists) {
            throw 'Existe un lock activo o pendiente. Ejecuta primero -Action Recover.'
        }
        $state.executor.model = $script:CodexModel
        $state.executor.reasoning_effort = $script:CodexReasoningEffort
        Save-TaskState -State $state
        Write-Host "Ejecutor configurado: $script:CodexModel / razonamiento $script:CodexReasoningEffort."
        break
    }
    'Validate' {
        if (-not (Test-Path -LiteralPath $script:SchemaPath)) {
            throw "No existe el esquema: $script:SchemaPath"
        }
        Get-Content -LiteralPath $script:SchemaPath -Raw | ConvertFrom-Json | Out-Null
        if (Test-Path -LiteralPath $script:StatePath) {
            $state = Read-TaskState -Tasks $tasks
            Update-ReadyStates -State $state -Tasks $tasks
        }
        $lockInfo = Get-OrchestratorLockInfo
        if ($lockInfo.exists) {
            if ($lockInfo.valid -and $lockInfo.active) {
                throw "Hay un orquestador activo con PID $($lockInfo.process_id)."
            }
            throw 'Existe un lock huérfano o inválido. Ejecuta -Action Recover.'
        }
        $codexCommand = Get-CodexCommand
        $codexVersion = (& $codexCommand --version 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($codexVersion)) {
            throw 'El binario nativo de Codex no respondió correctamente a --version.'
        }
        Write-Host "Validación correcta: $($tasks.Count) tareas v1, plan acíclico, esquema JSON válido y $codexVersion disponible. Ejecutor: $script:CodexModel / razonamiento $script:CodexReasoningEffort."
        break
    }
    'Status' {
        $state = Read-TaskState -Tasks $tasks
        Update-ReadyStates -State $state -Tasks $tasks
        $state.tasks | Select-Object id, title, status, gate_decision | Format-Table -AutoSize
        break
    }
    'Next' {
        $state = Read-TaskState -Tasks $tasks
        $ready = @(Get-ReadyPlanTasks -Tasks $tasks -State $state)
        if ($ready.Count -eq 0) {
            Write-Host 'No hay tareas READY.'
        }
        else {
            $ready[0] | Select-Object id, title, dependency_text | ConvertTo-Json
        }
        break
    }
    'Retry' {
        if ([string]::IsNullOrWhiteSpace($TaskId)) {
            throw 'Retry requiere -TaskId Txxx.'
        }
        $state = Read-TaskState -Tasks $tasks
        $task = $tasks | Where-Object { $_.id -eq $TaskId } | Select-Object -First 1
        if ($null -eq $task) {
            throw "No existe $TaskId en el plan."
        }
        $stateTask = Get-StateTaskById -State $state -Id $TaskId
        if ($stateTask.status -notin @('BLOCKED', 'IN_PROGRESS')) {
            throw "$TaskId no está BLOCKED ni IN_PROGRESS; estado actual: $($stateTask.status)."
        }
        if (-not (Test-DependenciesSatisfied -Task $task -State $state)) {
            throw "Las dependencias de $TaskId ya no están satisfechas."
        }
        $stateTask.status = 'READY'
        $stateTask.started_at = $null
        $stateTask.completed_at = $null
        $stateTask.session_id = $null
        $stateTask.summary = $null
        $stateTask.gate_decision = 'NOT_APPLICABLE'
        $stateTask.blocker = $null
        Save-TaskState -State $state
        Write-Host "$TaskId vuelve a READY. El historial de pendientes se conserva."
        break
    }
    'Recover' {
        $state = Read-TaskState -Tasks $tasks
        $activeChildren = @(Get-ActiveCodexChildren)
        if ($activeChildren.Count -gt 0) {
            $description = ($activeChildren | ForEach-Object {
                "$($_.task_id): PID $($_.process_id)"
            }) -join ', '
            throw "No se recupera mientras existan procesos Codex activos registrados: $description"
        }

        $lockInfo = Get-OrchestratorLockInfo
        $removedLock = $false
        if ($lockInfo.exists) {
            if (-not $lockInfo.valid) {
                throw "El lock no tiene un PID válido y no se elimina automáticamente: $($lockInfo.path)"
            }
            if ($lockInfo.active) {
                throw "El orquestador con PID $($lockInfo.process_id) sigue activo; no se recupera."
            }
            Remove-Item -LiteralPath $lockInfo.path -Force
            $removedLock = $true
        }

        $abandonedRuns = 0
        if (Test-Path -LiteralPath $script:RunsRoot) {
            foreach ($processFile in (Get-ChildItem -LiteralPath $script:RunsRoot -Filter 'process.json' -File -Recurse -ErrorAction SilentlyContinue)) {
                try {
                    $metadata = Get-Content -LiteralPath $processFile.FullName -Raw | ConvertFrom-Json
                }
                catch {
                    continue
                }
                if (
                    $metadata.PSObject.Properties.Name -contains 'status' -and
                    $metadata.status -eq 'RUNNING'
                ) {
                    $metadata.status = 'ABANDONED'
                    $metadata.finished_at = [DateTimeOffset]::Now.ToString('o')
                    Write-Utf8Atomic -Path $processFile.FullName -Content (($metadata | ConvertTo-Json -Depth 4) + "`n")
                    $abandonedRuns++
                }
            }
        }

        $recoveredTasks = [System.Collections.Generic.List[string]]::new()
        foreach ($stateTask in @($state.tasks | Where-Object { $_.status -eq 'IN_PROGRESS' })) {
            $stateTask.status = 'BLOCKED'
            $stateTask.blocker = [pscustomobject]@{
                type = 'TECHNICAL'
                description = 'La ejecución anterior terminó sin resultado verificable.'
                required_action = "Revisar los cambios y artefactos de $($stateTask.id), y después usar Retry explícitamente."
            }
            $recoveredTasks.Add($stateTask.id)
            $task = $tasks | Where-Object { $_.id -eq $stateTask.id } | Select-Object -First 1
            Add-PendingEntry -Task $task -Status 'BLOCKED / RECOVERED' -Problem $stateTask.blocker.description -RequiredAction $stateTask.blocker.required_action
        }
        if ($recoveredTasks.Count -gt 0) {
            Save-TaskState -State $state
        }

        Write-Host "Recuperación completada. Lock eliminado: $removedLock. Runs abandonados: $abandonedRuns. Tareas reconciliadas: $($recoveredTasks.Count)."
        break
    }
    'Run' {
        $state = Read-TaskState -Tasks $tasks
        $inProgress = @($state.tasks | Where-Object { $_.status -eq 'IN_PROGRESS' })
        if ($inProgress.Count -gt 0) {
            throw "Hay una tarea IN_PROGRESS de una ejecución interrumpida: $($inProgress.id -join ', '). Revisa los cambios y usa Retry explícitamente."
        }

        $lock = $null
        try {
            $lock = Enter-OrchestratorLock
            $completedThisRun = 0
            while ($MaxTasks -eq 0 -or $completedThisRun -lt $MaxTasks) {
                $ready = @(Get-ReadyPlanTasks -Tasks $tasks -State $state)
                if (-not [string]::IsNullOrWhiteSpace($TaskId)) {
                    $ready = @($ready | Where-Object { $_.id -eq $TaskId })
                    if ($ready.Count -eq 0) {
                        throw "$TaskId no está READY."
                    }
                }
                if ($ready.Count -eq 0) {
                    $notDone = @($state.tasks | Where-Object { $_.status -ne 'DONE' })
                    if ($notDone.Count -eq 0) {
                        Write-Host 'Todas las tareas v1 del plan están DONE.'
                    }
                    else {
                        Write-Host 'No quedan tareas READY; existen tareas pendientes o bloqueadas.'
                    }
                    break
                }

                $outcome = Invoke-OneTask -Task $ready[0] -State $state -Tasks $tasks
                if ($outcome -ne 'DONE') {
                    break
                }
                $completedThisRun++
                if (-not [string]::IsNullOrWhiteSpace($TaskId)) {
                    break
                }
            }
        }
        finally {
            Exit-OrchestratorLock -Lock $lock
        }
        break
    }
}
