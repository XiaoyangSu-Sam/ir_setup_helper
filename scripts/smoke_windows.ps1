[CmdletBinding()]
param([string]$Installer = '', [switch]$WithRegistration)

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
$registration = Join-Path $program 'registration'
$registrationData = Join-Path $registration 'data'
$priorData = $env:ENDURANCE_DATA_DIR
$priorWatcher = $env:ENDURANCE_NO_WATCHER
$priorLive = $env:ENDURANCE_NO_LIVE
New-Item -ItemType Directory -Path $work | Out-Null

function Install-Product([switch]$ExpectBlocked) {
    $setupLog = Join-Path $work 'install.log'
    $result = Start-Process -FilePath $Installer -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
        ('/DIR="' + $program + '"'), ('/LOG="' + $setupLog + '"')
    ) -WindowStyle Hidden -Wait -PassThru
    if ($ExpectBlocked) {
        if ($result.ExitCode -eq 0) { throw 'Upgrade continued while the registration assistant was active.' }
        return
    }
    if ($result.ExitCode -ne 0) { throw "Installation exited with $($result.ExitCode). See $setupLog." }
}

try {
    $env:ENDURANCE_DATA_DIR = $library
    $env:ENDURANCE_NO_WATCHER = '1'
    $env:ENDURANCE_NO_LIVE = '1'
    Install-Product
    if (!(Test-Path -LiteralPath $launcher)) { throw 'Installer did not copy the executable.' }
    $assets = @(
        '_internal/app.py'
        '_internal/pyproject.toml'
        '_internal/config/setup_rules.json'
        '_internal/endurance/ui_assets/timing-wall.js'
        '_internal/endurance/ui_assets/video-reference.html'
        '_internal/endurance/ui_assets/video-reference.js'
    )
    foreach ($asset in $assets) {
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
    if ($WithRegistration) {
        $bridge = Join-Path $registration 'NativeBridge.exe'
        $node = Join-Path $registration 'runtime/node/node.exe'
        if (!(Test-Path -LiteralPath $bridge) -or !(Test-Path -LiteralPath $node) -or
            (Test-Path -LiteralPath $registrationData)) {
            throw 'Registration files are missing or the installer included an existing registration library.'
        }
        if (Get-NetTCPConnection -LocalPort 19390 -State Listen -ErrorAction SilentlyContinue) {
            throw 'Port 19390 is in use. Run the registration smoke test while that service is stopped.'
        }
        # Run only the backend with an empty test library. NativeBridge would also open iRacing.
        $registrationServer = Start-Process -FilePath $node -ArgumentList 'server.mjs' -WorkingDirectory $registration -WindowStyle Hidden -PassThru
        try {
            $console = $null
            for ($attempt = 0; $attempt -lt 30 -and !$registrationServer.HasExited; $attempt++) {
                try {
                    $console = Invoke-WebRequest 'http://127.0.0.1:19390/' -TimeoutSec 2
                    break
                } catch {
                    Start-Sleep -Milliseconds 400
                }
            }
            if ($console.StatusCode -ne 200 -or $console.Content -notmatch '报名' -or
                !(Test-Path -LiteralPath (Join-Path $registrationData 'tasks.sqlite'))) {
                throw 'The installed registration service did not load its UI and create an empty database.'
            }
            if ((Invoke-WebRequest "$service/_stcore/health" -TimeoutSec 5).StatusCode -ne 200) {
                throw 'The two installed services could not run together.'
            }
        }
        finally {
            if (!$registrationServer.HasExited) {
                Stop-Process -InputObject $registrationServer
                $registrationServer.WaitForExit()
            }
        }
        $created = $false
        $bridgeMutex = [Threading.Mutex]::new($true, 'Local\CodexIRacingNativeBridge', [ref]$created)
        try {
            if (!$created) { throw 'An existing registration assistant owns the bridge mutex.' }
            Install-Product -ExpectBlocked
            if ($running.HasExited) { throw 'The blocked upgrade stopped the setup helper.' }
        }
        finally {
            if ($created) { $bridgeMutex.ReleaseMutex() }
            $bridgeMutex.Dispose()
        }
    }
    Set-Content -LiteralPath (Join-Path $library 'preserve.txt') -Value 'existing driver data'
    Install-Product
    if (!$running.WaitForExit(15000)) { throw 'Upgrade did not stop the existing server.' }

    $remove = Get-ChildItem -LiteralPath $program -Filter 'unins*.exe' | Select-Object -First 1
    $result = Start-Process -FilePath $remove.FullName -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -Wait -PassThru
    if ($result.ExitCode -ne 0 -or (Test-Path -LiteralPath $launcher)) { throw 'Uninstall failed.' }
    if (!(Test-Path -LiteralPath (Join-Path $library 'preserve.txt'))) { throw 'Uninstall removed driver data.' }
    if ($WithRegistration -and !(Test-Path -LiteralPath (Join-Path $registrationData 'tasks.sqlite'))) {
        throw 'Uninstall removed the registration library.'
    }
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
