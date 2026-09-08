[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$PreviousSetup,
    [Parameter(Mandatory = $true)] [string]$TargetSetup,
    [Parameter(Mandatory = $true)] [string]$PortableZip,
    [Parameter(Mandatory = $true)] [string]$OutputDir,
    [int]$TimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Hash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-Installer([string]$Installer, [string]$InstallDir) {
    $arguments = "/S /D=$InstallDir"
    $process = Start-Process -FilePath (Resolve-Path -LiteralPath $Installer) -ArgumentList $arguments -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Timeout del instalador: $Installer"
    }
    if ($process.ExitCode -ne 0) { throw "El instalador terminó con código $($process.ExitCode): $Installer" }
}

$previous = Get-Item -LiteralPath $PreviousSetup
$target = Get-Item -LiteralPath $TargetSetup
$portable = Get-Item -LiteralPath $PortableZip
$out = New-Item -ItemType Directory -Force -Path $OutputDir
$root = New-Item -ItemType Directory -Force -Path (Join-Path $out.FullName ('upgrade-' + [guid]::NewGuid().ToString('N')))
$installDir = Join-Path $root.FullName 'install'
$portableDir = Join-Path $root.FullName 'portable'
$marker = Join-Path $root.FullName 'user-data-marker.txt'
[IO.File]::WriteAllText($marker, 'user data must survive installer replacement', [Text.Encoding]::UTF8)

try {
    Invoke-Installer $previous.FullName $installDir
    $oldExe = Join-Path $installDir 'GTFS Explorer.exe'
    if (-not (Test-Path -LiteralPath $oldExe)) { throw 'El baseline no dejó el ejecutable esperado.' }
    $oldPath = (Resolve-Path -LiteralPath $oldExe).Path
    $oldSmoke = Start-Process -FilePath $oldPath -ArgumentList '--runtime-smoke' -WorkingDirectory $installDir -Wait -PassThru
    if ($oldSmoke.ExitCode -ne 0) { throw "El smoke del baseline falló: $($oldSmoke.ExitCode)" }
    Invoke-Installer $target.FullName $installDir
    $currentExe = (Resolve-Path -LiteralPath $oldExe).Path
    $currentSmoke = Start-Process -FilePath $currentExe -ArgumentList '--runtime-smoke' -WorkingDirectory $installDir -Wait -PassThru
    if ($currentSmoke.ExitCode -ne 0) { throw "El smoke target falló: $($currentSmoke.ExitCode)" }
    if (-not (Test-Path -LiteralPath $marker)) { throw 'El marker de datos de usuario desapareció.' }
    Expand-Archive -LiteralPath $portable.FullName -DestinationPath $portableDir
    $portableExeItem = Get-ChildItem -LiteralPath $portableDir -Filter 'GTFS Explorer.exe' -Recurse -File | Select-Object -First 1
    if ($null -eq $portableExeItem) { throw 'El portable extraído no contiene GTFS Explorer.exe.' }
    $portableExe = $portableExeItem.FullName
    $portableSmoke = Start-Process -FilePath $portableExe -ArgumentList '--runtime-smoke' -WorkingDirectory $portableExeItem.DirectoryName -Wait -PassThru
    if ($portableSmoke.ExitCode -ne 0) { throw "El smoke portable falló: $($portableSmoke.ExitCode)" }
    $registryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\GTFS Explorer Desktop'
    if (-not (Test-Path -LiteralPath $registryKey)) { throw 'No existe la entrada de desinstalación HKCU esperada.' }
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'GTFS Explorer Desktop.lnk'
    $startShortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'GTFS Explorer Desktop\GTFS Explorer Desktop.lnk'
    if (-not (Test-Path -LiteralPath $desktopShortcut)) { throw 'Falta el acceso directo del escritorio.' }
    if (-not (Test-Path -LiteralPath $startShortcut)) { throw 'Falta el acceso directo del menú Inicio.' }
    $uninstaller = Join-Path $installDir 'uninstall.exe'
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw 'Falta el desinstalador del target.' }
    $uninstallProcess = Start-Process -FilePath $uninstaller -ArgumentList '/S' -PassThru
    if (-not $uninstallProcess.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $uninstallProcess.Id -Force -ErrorAction SilentlyContinue
        throw 'Timeout del desinstalador.'
    }
    if ($uninstallProcess.ExitCode -ne 0) { throw "El desinstalador terminó con código $($uninstallProcess.ExitCode)." }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        $residualExe = Test-Path -LiteralPath $currentExe
        $residualRegistry = Test-Path -LiteralPath $registryKey
        $residualDesktop = Test-Path -LiteralPath $desktopShortcut
        $residualStart = Test-Path -LiteralPath $startShortcut
        if (-not ($residualExe -or $residualRegistry -or $residualDesktop -or $residualStart)) { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    $residualExe = Test-Path -LiteralPath $currentExe
    $residualRegistry = Test-Path -LiteralPath $registryKey
    $residualDesktop = Test-Path -LiteralPath $desktopShortcut
    $residualStart = Test-Path -LiteralPath $startShortcut
    if ($residualExe -or $residualRegistry -or $residualDesktop -or $residualStart) {
        throw "La desinstalación dejó artefactos: exe=$residualExe registry=$residualRegistry desktop=$residualDesktop start=$residualStart"
    }
    if (-not (Test-Path -LiteralPath $marker)) { throw 'La desinstalación eliminó datos de usuario.' }
    $report = [ordered]@{
        previous = [ordered]@{ executable_path = $oldPath; sha256 = Hash $previous.FullName; install_directory = $installDir }
        target = [ordered]@{ executable_path = $currentExe; sha256 = Hash $target.FullName; install_directory = $installDir }
        portable = [ordered]@{ archive = $portable.Name; sha256 = Hash $portable.FullName; executable_path = $portableExe }
        same_install_directory = $true
        user_data_preserved = (Test-Path -LiteralPath $marker)
        registry_and_shortcuts = 'verified-before-uninstall-and-removed-after-uninstall'
        uninstall = 'passed'
    }
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $out.FullName 'upgrade-smoke.json') -Encoding utf8
    Write-Output "UPGRADE_SMOKE=PASS"
    Write-Output "REPORT=$(Join-Path $out.FullName 'upgrade-smoke.json')"
}
finally {
    $uninstaller = Join-Path $installDir 'uninstall.exe'
    if (Test-Path -LiteralPath $uninstaller) {
        $cleanup = Start-Process -FilePath $uninstaller -ArgumentList '/S' -Wait -PassThru
        if ($cleanup.ExitCode -ne 0) { Write-Warning "La limpieza del uninstaller terminó con código $($cleanup.ExitCode)." }
    }
    if (Test-Path -LiteralPath $root.FullName) { Remove-Item -LiteralPath $root.FullName -Recurse -Force -ErrorAction SilentlyContinue }
}
