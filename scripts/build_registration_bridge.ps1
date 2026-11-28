[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$Output)

$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'registration/native/NativeBridge.cs'
$framework = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
$wpf = Join-Path $framework 'WPF'
if (!(Test-Path -LiteralPath $compiler -PathType Leaf)) { throw 'Windows .NET Framework C# compiler not found.' }
& $compiler /nologo /target:winexe "/out:$Output" /reference:System.Windows.Forms.dll `
    /reference:System.Drawing.dll /reference:System.Web.Extensions.dll `
    "/reference:$wpf/UIAutomationClient.dll" "/reference:$wpf/UIAutomationTypes.dll" "/reference:$wpf/WindowsBase.dll" $source
if ($LASTEXITCODE -ne 0) { throw 'NativeBridge compilation failed.' }
