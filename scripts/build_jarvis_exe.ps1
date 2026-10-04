$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) {
    throw 'Le compilateur .NET Framework de Windows est introuvable.'
}
$launcherSource = Join-Path $PSScriptRoot 'desktop\JarvisLauncher.cs'
$launcherOutput = Join-Path $projectRoot 'Jarvis.exe'
& $compiler /nologo /target:winexe /platform:anycpu /optimize+ /utf8output /reference:System.Windows.Forms.dll "/out:$launcherOutput" $launcherSource
if ($LASTEXITCODE -ne 0) {
    throw 'Compilation impossible. Fermez Jarvis avant de reconstruire son executable.'
}
Get-Item -LiteralPath $launcherOutput | Select-Object FullName, Length
