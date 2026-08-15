[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repositoryRoot

$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
}

$runtimeRoot = Join-Path $repositoryRoot "tests\.runtime"
[System.IO.Directory]::CreateDirectory($runtimeRoot) | Out-Null
# DuckDB files can remain momentarily locked on Windows after a prior run.
# A per-run base avoids Pytest attempting to delete a previous run before the
# suite begins; tests still use an isolated, deterministic directory layout.
$pytestBaseTemp = Join-Path $runtimeRoot ("pytest-" + [guid]::NewGuid().ToString("N"))

$checks = @(
    @("-m", "ruff", "format", "--check", "src", "tests", "tools"),
    @("-m", "ruff", "check", "src", "tests", "tools"),
    @("-m", "mypy", "src"),
    @("-m", "pytest", "tests", "--basetemp", $pytestBaseTemp)
)

foreach ($check in $checks) {
    & $python @check
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
