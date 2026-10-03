param([switch]$Targeted)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project Python missing: $pythonPath"
}
$auditRoot = Join-Path $projectRoot ".cache\codex-validation"
New-Item -ItemType Directory -Path (Join-Path $auditRoot "tmp"), (Join-Path $auditRoot "data") -Force | Out-Null
$changes = @{
    TEMP = (Join-Path $auditRoot "tmp")
    TMP = (Join-Path $auditRoot "tmp")
    LOCALAPPDATA = (Join-Path $auditRoot "data")
    QT_QPA_PLATFORM = "offscreen"
    PYTHONIOENCODING = "utf-8"
    PYTHONUTF8 = "1"
    JARVIS_COMPATIBILITY_BASELINE = "1"
    JARVIS_OPERATIONAL_LEARNING_ENABLED = "0"
    JARVIS_VISION_ENABLED = "0"
    JARVIS_STRICT_PROOF_ENABLED = "0"
    JARVIS_STRUCTURED_TRACING_ENABLED = "0"
    JARVIS_RUNTIME_OBSERVABILITY_ENABLED = "0"
    JARVIS_KERNEL_SHADOW_ENABLED = "0"
}
$originalValues = @{}
foreach ($name in $changes.Keys) {
    $originalValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    [Environment]::SetEnvironmentVariable($name, $changes[$name], "Process")
}
$validationExit = 1
Push-Location -LiteralPath $projectRoot
try {
    $testArguments = if ($Targeted) {
        "tests.test_runtime_observability -v"
    } else {
        "discover -s tests -v"
    }
    # Merge unittest's normal stderr before PowerShell 5.1 interprets it as an
    # error record. The interpreter and arguments are fixed trusted inputs.
    $command = '"' + $pythonPath + '" -m unittest ' + $testArguments + " 2>&1"
    cmd.exe /d /s /c $command
    $validationExit = $LASTEXITCODE
}
finally {
    Pop-Location
    foreach ($name in $originalValues.Keys) {
        [Environment]::SetEnvironmentVariable($name, $originalValues[$name], "Process")
    }
}
exit $validationExit
