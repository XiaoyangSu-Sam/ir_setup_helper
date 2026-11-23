[CmdletBinding()]
param([string]$Installer = '')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (!$Installer) {
    $Installer = (Get-ChildItem -LiteralPath (Join-Path $root 'dist') -Filter '*-setup.exe' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$work = Join-Path ([IO.Path]::GetTempPath()) ("ir-setup-smoke-" + [Guid]::NewGuid())
$program = Join-Path $work 'program'
$library = Join-Path $work 'library'
$runtime = Join-Path $library 'runtime-installed'
$launcher = Join-Path $program 'IRSetupHelper.exe'
$priorData = $env:ENDURANCE_DATA_DIR
$priorWatcher = $env:ENDURANCE_NO_WATCHER
$priorLive = $env:ENDURANCE_NO_LIVE
New-Item -ItemType Directory -Path $work | Out-Null

function Install-Product {
    $setupLog = Join-Path $work 'install.log'
    $result = Start-Process -FilePath $Installer -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
        ('/DIR="' + $program + '"'), ('/LOG="' + $setupLog + '"')
    ) -WindowStyle Hidden -Wait -PassThru
    if ($result.ExitCode -ne 0) { throw "Installation exited with $($result.ExitCode). See $setupLog." }
}

try {
    $env:ENDURANCE_DATA_DIR = $library
    $env:ENDURANCE_NO_WATCHER = '1'
    $env:ENDURANCE_NO_LIVE = '1'
    Install-Product
    if (!(Test-Path -LiteralPath $launcher)) { throw 'Installer did not copy the executable.' }
    foreach ($asset in @('_internal/app.py', '_internal/config/setup_rules.json', '_internal/endurance/ui_assets/timing-wall.js')) {
        if (!(Test-Path -LiteralPath (Join-Path $program $asset))) { throw "Missing bundled asset: $asset" }
    }
    $running = Start-Process -FilePath $launcher -ArgumentList '--no-browser' -WindowStyle Hidden -PassThru
    $service = 'http://127.0.0.1:19392'
    $reachable = $false
    for ($attempt = 0; $attempt -lt 60 -and !$running.HasExited; $attempt++) {
        try {
            $session = Get-Content -LiteralPath (Join-Path $runtime 'session.json') -ErrorAction Stop | ConvertFrom-Json
            if ($session.url -eq $service -and (Invoke-WebRequest "$service/_stcore/health" -TimeoutSec 2).StatusCode -eq 200) {
                $reachable = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    }
    if (!$reachable) { throw "Installed server did not start. See $runtime\server.log." }
    if ((Invoke-WebRequest $service -TimeoutSec 5).Content -notmatch '<title>Streamlit</title>') {
        throw 'Installed server did not serve its browser frontend.'
    }
    Set-Content -LiteralPath (Join-Path $library 'preserve.txt') -Value 'existing driver data'
    Install-Product
    if (!$running.WaitForExit(15000)) { throw 'Upgrade did not stop the existing server.' }

    $remove = Get-ChildItem -LiteralPath $program -Filter 'unins*.exe' | Select-Object -First 1
    $result = Start-Process -FilePath $remove.FullName -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -Wait -PassThru
    if ($result.ExitCode -ne 0 -or (Test-Path -LiteralPath $launcher)) { throw 'Uninstall failed.' }
    if (!(Test-Path -LiteralPath (Join-Path $library 'preserve.txt'))) { throw 'Uninstall removed driver data.' }
    Write-Output "Installation, local startup, upgrade, and data-preserving uninstall passed. Log: $work"
}
finally {
    if ($running -and !$running.HasExited -and (Test-Path -LiteralPath $launcher)) {
        Start-Process -FilePath $launcher -ArgumentList '--stop-and-wait' -WindowStyle Hidden -Wait
    }
    $env:ENDURANCE_DATA_DIR = $priorData
    $env:ENDURANCE_NO_WATCHER = $priorWatcher
    $env:ENDURANCE_NO_LIVE = $priorLive
}
