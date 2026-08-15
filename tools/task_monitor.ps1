#Requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateRange(1, 3600)]
    [int]$RefreshSeconds = 5,

    [switch]$Watch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $repositoryRoot 'docs\TASK_STATUS.json'
$runsRoot = Join-Path $repositoryRoot '.codex-runs'

function Get-RunMetadata {
    param([Parameter(Mandatory)] [string]$TaskId)

    $run = Get-ChildItem -LiteralPath $runsRoot -Directory -Filter "$TaskId-*" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $run) {
        return $null
    }
    $path = Join-Path $run.FullName 'process.json'
    if (-not (Test-Path -LiteralPath $path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Format-Timestamp {
    param([AllowNull()] [object]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '-' }
    if ($Value -is [DateTimeOffset]) {
        return $Value.ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')
    }
    if ($Value -is [DateTime]) {
        return $Value.ToString('yyyy-MM-dd HH:mm:ss')
    }
    return ([DateTimeOffset]::Parse([string]$Value)).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')
}

function Show-TaskMonitor {
    if (-not (Test-Path -LiteralPath $statePath)) {
        throw "No existe el registro de tareas: $statePath"
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $now = [DateTimeOffset]::Now
    $summary = $state.tasks | Group-Object status | ForEach-Object { "$($_.Name): $($_.Count)" }

    try {
        Clear-Host
    }
    catch {
        # Algunas consolas redirigidas no admiten Clear-Host.
    }
    Write-Host 'GTFS Explorer Desktop — monitor del plan maestro'
    Write-Host "Actualizado: $($now.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    Write-Host ($summary -join ' | ')
    Write-Host ''

    $rows = foreach ($task in $state.tasks) {
        $run = if ($task.status -eq 'IN_PROGRESS') { Get-RunMetadata -TaskId $task.id } else { $null }
        [pscustomobject]@{
            Tarea = $task.id
            Estado = $task.status
            Titulo = $task.title
            Inicio = Format-Timestamp $task.started_at
            Fin = Format-Timestamp $task.completed_at
            PID = if ($null -ne $run -and $null -ne $run.child_pid) { $run.child_pid } else { '-' }
            Heartbeat = if ($null -ne $run) { Format-Timestamp $run.last_heartbeat_at } else { '-' }
            Bloqueo = if ($null -ne $task.blocker) { $task.blocker.description } else { '' }
        }
    }
    $rows | Format-Table -AutoSize -Wrap

    $active = @($rows | Where-Object Estado -eq 'IN_PROGRESS')
    if ($active.Count -gt 0) {
        Write-Host ''
        Write-Host 'En ejecución:'
        $active | ForEach-Object { Write-Host "- $($_.Tarea): $($_.Titulo) (heartbeat: $($_.Heartbeat))" }
    }
    Write-Host ''
    Write-Host 'Ctrl+C detiene solo el monitor; no detiene tareas del orquestador.'
}

do {
    Show-TaskMonitor
    if ($Watch) { Start-Sleep -Seconds $RefreshSeconds }
} while ($Watch)
