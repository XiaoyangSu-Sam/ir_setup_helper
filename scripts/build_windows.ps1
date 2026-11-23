[CmdletBinding()]
param(
    [string]$Python = '',
    [string]$Iscc = '',
    [string]$RegistrationPackage = '',
    [switch]$BundleOnly,
    [switch]$ReuseSetupBundle
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (!$Python) {
        $localPython = Join-Path $root '.venv\Scripts\python.exe'
        $Python = if (Test-Path -LiteralPath $localPython) { $localPython } else { 'python' }
    }
    $version = & $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
    if ($LASTEXITCODE -ne 0 -or !$version) { throw 'Could not read the project version.' }

    $bundleArgs = @(
        '--noconfirm', '--clean', '--onedir', '--windowed', '--name', 'IRSetupHelper'
        '--distpath', 'build/windows', '--workpath', 'build/pyinstaller', '--specpath', 'build'
        '--paths', $root, '--hidden-import', 'app', '--collect-all', 'streamlit'
        '--recursive-copy-metadata', 'streamlit', '--collect-all', 'tzdata', '--collect-all', '_polars_runtime_32'
        '--copy-metadata', 'polars', '--copy-metadata', 'polars-runtime-32'
        '--copy-metadata', 'PyYAML', '--copy-metadata', 'duckdb'
        '--add-data', "$root/app.py:.", '--add-data', "$root/config:config"
        '--add-data', "$root/.streamlit/config.toml:.streamlit"
        '--add-data', "$root/endurance/ui_assets:endurance/ui_assets", 'launch.py'
    )
    if ($ReuseSetupBundle) {
        if (!(Test-Path -LiteralPath 'build/windows/IRSetupHelper/IRSetupHelper.exe' -PathType Leaf)) {
            throw 'No existing Windows setup-helper build to reuse.'
        }
    } else {
        & $Python -m PyInstaller @bundleArgs
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    }
    if ($BundleOnly) { return }

    if (!$Iscc) {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        $candidate = @(
            $command.Source
            (([Environment]::GetEnvironmentVariable('ProgramFiles(x86)')) + '\Inno Setup 6\ISCC.exe')
            "$env:ProgramFiles\Inno Setup 7\ISCC.exe"
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
        if (!$candidate) { throw 'Install Inno Setup or pass -Iscc with the path to ISCC.exe.' }
        $Iscc = $candidate
    }
    $installerArgs = @("/DAppVersion=$version")
    $product = 'IRSetupHelper'
    if ($RegistrationPackage) {
        $staging = & $Python -X utf8 scripts/stage_registration.py $RegistrationPackage build/windows
        if ($LASTEXITCODE -ne 0 -or !$staging) { throw 'Could not verify and stage the registration assistant.' }
        $installerArgs += "/DRegistrationRoot=$staging"
        $product = 'IRacingTools'
    }
    & $Iscc /Q @installerArgs 'packaging/windows.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

    $artifact = "$product-$version-windows-x64-setup.exe"
    $checksum = (Get-FileHash -LiteralPath "dist/$artifact" -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "dist/$artifact.sha256" -Encoding ascii -Value "$checksum  $artifact"
    Get-Item -LiteralPath "dist/$artifact", "dist/$artifact.sha256"
}
finally {
    Pop-Location
}
