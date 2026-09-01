param(
    [Parameter(Mandatory = $true)] [string]$PortableZip,
    [Parameter(Mandatory = $true)] [string]$SetupExe,
    [Parameter(Mandatory = $true)] [string]$OutputDir,
    [switch]$GenerateManifest
)

$ErrorActionPreference = 'Stop'
$portable = Get-Item -LiteralPath $PortableZip
$setup = Get-Item -LiteralPath $SetupExe
$out = New-Item -ItemType Directory -Force -Path $OutputDir

function Get-Sha256([System.IO.FileInfo]$Path) {
    return (Get-FileHash -LiteralPath $Path.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}

$temp = Join-Path $out.FullName ('package-smoke-extracted-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
Expand-Archive -LiteralPath $portable.FullName -DestinationPath $temp
$root = Join-Path $temp 'GTFS-Explorer'
$exe = Join-Path $root 'GTFS Explorer.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Falta GTFS Explorer.exe en el portable.' }
foreach ($required in @('portable.flag', 'manifest.json', 'docs\USER_GUIDE.md', 'QtWebEngineProcess.exe', 'qtwebengine_resources.pak', 'web\map\qt_resources\map_bundle.js')) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $required))) { throw "Falta recurso portable: $required" }
}
$forbidden = Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
    $relative = [System.IO.Path]::GetRelativePath($root, $_.FullName)
    $relative -match '(^|\\)tests(\\|$)|(^|\\)\.git(\\|$)|(^|\\)\.env$|(^|\\)__pycache__(\\|$)|(^|\\)ctm(\\|$)'
}
if ($forbidden) { throw ('Archivos prohibidos en portable: ' + (($forbidden | ForEach-Object FullName) -join ', ')) }
$process = Start-Process -FilePath $exe -ArgumentList '--runtime-smoke' -WorkingDirectory $root -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Portable runtime smoke falló con código $($process.ExitCode)." }

$manifest = [ordered]@{
    product = 'GTFS Explorer Desktop'
    version = '0.1.0'
    status = 'LOCAL_ONLY_NOT_PUBLISHED'
    artifacts = @(
        [ordered]@{ file = $portable.Name; bytes = $portable.Length; sha256 = Get-Sha256 $portable; packaging_type = 'portable-zip' },
        [ordered]@{ file = $setup.Name; bytes = $setup.Length; sha256 = Get-Sha256 $setup; packaging_type = 'nsis-installer' }
    )
    build_tools = [ordered]@{ python = '3.12'; nuitka = '2.6.9'; nsis = '3.x'; pyside6 = '6.8.3'; duckdb = '1.1.3' }
    portable_smoke = 'passed'
    webengine_resources = 'passed'
    signing = 'unsigned'
}
if ($GenerateManifest) {
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out.FullName 'release-manifest.json') -Encoding utf8
    @($manifest.artifacts | ForEach-Object { "$($_.sha256)  $($_.file)" }) | Set-Content -LiteralPath (Join-Path $out.FullName 'checksums.txt') -Encoding ascii
}
Write-Output "PACKAGE_SMOKE=PASS"
Write-Output "PORTABLE_EXECUTABLE=$exe"
Write-Output "PORTABLE_SHA256=$(Get-Sha256 $portable)"
Write-Output "SETUP_SHA256=$(Get-Sha256 $setup)"
