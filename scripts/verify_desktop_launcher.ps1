$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $projectRoot 'Jarvis.exe'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Construisez Jarvis.exe avant la verification.' }
$checkRoot = Join-Path $projectRoot ('.cache\desktop-launcher-check\' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checkRoot -Force | Out-Null
$localData = Join-Path $checkRoot 'data'
$otherDirectory = Join-Path $checkRoot 'other-working-directory'
New-Item -ItemType Directory -Path $localData, $otherDirectory -Force | Out-Null
$changes = @{
    LOCALAPPDATA = $localData
    JARVIS_MEMORY_DB_PATH = (Join-Path $localData 'memory.sqlite3')
    JARVIS_OPERATIONAL_LEARNING_ENABLED = '0'
    JARVIS_SEMANTIC_MISSIONS_ENABLED = '0'
    JARVIS_STRUCTURED_TRACING_ENABLED = '0'
}
$previous = @{}
foreach ($name in $changes.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $changes[$name], 'Process')
}

function Invoke-LauncherCheck([string]$Exe, [string]$Label, [bool]$Check = $true) {
    $stdout = Join-Path $checkRoot ($Label + '.stdout.txt')
    $stderr = Join-Path $checkRoot ($Label + '.stderr.txt')
    $startArguments = @{
        FilePath = $Exe; WorkingDirectory = $otherDirectory
        WindowStyle = 'Hidden'; PassThru = $true
        RedirectStandardOutput = $stdout; RedirectStandardError = $stderr
    }
    if ($Check) { $startArguments.ArgumentList = '--check' }
    $process = Start-Process @startArguments
    # Keep the native process handle so Windows PowerShell can read the exit
    # status even when the GUI executable has already exited.
    $null = $process.Handle
    if (-not $process.WaitForExit(45000)) {
        $process.Kill()
        throw "Le controle $Label a depasse 45 secondes."
    }
    return [PSCustomObject]@{
        ExitCode = $process.ExitCode
        Output = [IO.File]::ReadAllText($stdout, [Text.Encoding]::UTF8)
        Error = [IO.File]::ReadAllText($stderr, [Text.Encoding]::UTF8)
    }
}

try {
    $bytes = [IO.File]::ReadAllBytes($launcher)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    $subsystem = [BitConverter]::ToUInt16($bytes, $peOffset + 24 + 68)
    if ($bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a -or $subsystem -ne 2) {
        throw 'Le binaire doit etre un executable Windows GUI.'
    }
    $real = Invoke-LauncherCheck $launcher 'real-startup'
    if ($real.ExitCode -ne 0) { throw "Le controle reel a echoue : $($real.Error)" }
    $report = $real.Output | ConvertFrom-Json
    if ($report.status -ne 'ok' -or $report.ui -ne 'window_created_and_closed' -or
        $report.project_root -ne $projectRoot -or $report.memory_db_path -ne $changes.JARVIS_MEMORY_DB_PATH) {
        throw 'Le controle reel ne confirme pas les chemins et la fenetre attendus.'
    }

    # Exercise paths with spaces/Unicode and concurrent output using a small
    # interpreter fixture. This never launches the real microphone or model.
    $fixtureRoot = Join-Path $checkRoot ('path with space ' + [char]0x00e9)
    $fixturePythonDir = Join-Path $fixtureRoot '.venv\Scripts'
    $fixtureScripts = Join-Path $fixtureRoot 'scripts'
    New-Item -ItemType Directory -Path $fixturePythonDir, $fixtureScripts -Force | Out-Null
    $fixtureLauncher = Join-Path $fixtureRoot 'Jarvis.exe'
    Copy-Item -LiteralPath $launcher -Destination $fixtureLauncher
    Set-Content -LiteralPath (Join-Path $fixtureRoot 'run_jarvis.py') -Value '# fixture' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $fixtureScripts 'check_desktop_startup.py') -Value '# fixture' -Encoding UTF8
    $stubSource = Join-Path $checkRoot 'InterpreterFixture.cs'
    @'
using System;
using System.IO;
using System.Text;
class InterpreterFixture {
    static int Main(string[] args) {
        Console.OutputEncoding = Encoding.UTF8;
        if (args.Length != 2 || args[0] != "-u" || !File.Exists(args[1])) return 41;
        if (Path.GetDirectoryName(args[1]) != Environment.CurrentDirectory &&
            Path.GetDirectoryName(Path.GetDirectoryName(args[1])) != Environment.CurrentDirectory) return 42;
        if (Environment.GetEnvironmentVariable("VIRTUAL_ENV") != Path.Combine(Environment.CurrentDirectory, ".venv")) return 43;
        if (!Environment.GetEnvironmentVariable("PATH").StartsWith(Path.Combine(Environment.CurrentDirectory, ".venv", "Scripts"))) return 44;
        Console.WriteLine("script=" + args[1]);
        Console.WriteLine("cwd=" + Environment.CurrentDirectory);
        for (int i = 0; i < 500; i++) {
            Console.WriteLine("OUT " + new string('x', 256));
            Console.Error.WriteLine("ERR " + new string('y', 256));
        }
        return 0;
    }
}
'@ | Set-Content -LiteralPath $stubSource -Encoding UTF8
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    if (-not (Test-Path -LiteralPath $compiler)) {
        $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
    }
    & $compiler /nologo /target:exe "/out:$(Join-Path $fixturePythonDir 'python.exe')" $stubSource
    if ($LASTEXITCODE -ne 0) { throw 'La fixture de verification ne compile pas.' }
    $fixture = Invoke-LauncherCheck $fixtureLauncher 'unicode-streams'
    if ($fixture.ExitCode -ne 0 -or -not $fixture.Output.Contains($fixtureRoot) -or
        -not $fixture.Output.Contains('OUT ') -or -not $fixture.Error.Contains('ERR ')) {
        throw 'Le test des chemins et flux concurrents a echoue.'
    }
    $normal = Invoke-LauncherCheck $fixtureLauncher 'normal-entry' $false
    if ($normal.ExitCode -ne 0) { throw 'Le lancement normal ne choisit pas correctement run_jarvis.py.' }
    $logs = Get-ChildItem -LiteralPath (Join-Path $localData 'JarvisPersonal\logs') -File
    if (-not ($logs | Where-Object {
        $text = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8)
        $text.Contains('script=' + (Join-Path $fixtureRoot 'run_jarvis.py')) -and $text.Contains('[DESKTOP] exit=0')
    })) { throw 'Le journal du lancement normal est incomplet.' }

    $brokenRoot = Join-Path $checkRoot 'missing-environment'
    New-Item -ItemType Directory -Path $brokenRoot -Force | Out-Null
    $brokenLauncher = Join-Path $brokenRoot 'Jarvis.exe'
    Copy-Item -LiteralPath $launcher -Destination $brokenLauncher
    $broken = Invoke-LauncherCheck $brokenLauncher 'missing-environment'
    if ($broken.ExitCode -eq 0 -or -not $broken.Error.Contains('.venv')) {
        throw 'Un environnement absent doit retourner une erreur lisible.'
    }
    [PSCustomObject]@{
        status = 'ok'; checks = 5; gui_executable = $true
        real_ui = $report.ui; actual_voice_worker = 'not_started'
        unicode_paths = 'ok'; concurrent_streams = 'ok'
        normal_entry = 'ok'; missing_environment = 'reported'
    } | ConvertTo-Json
}
finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
