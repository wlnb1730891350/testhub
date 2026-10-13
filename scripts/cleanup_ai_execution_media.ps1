param(
    [ValidateRange(0, 100000)]
    [int]$KeepLatest = 100,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'venv\Scripts\python.exe'
$logDir = Join-Path $root 'logs'
$logFile = Join-Path $logDir 'ai_execution_media_cleanup.log'

if (-not (Test-Path $python)) {
    throw "Python runtime was not found: $python"
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$arguments = @('manage.py', 'cleanup_ai_execution_media', '--keep-latest', $KeepLatest)
if ($DryRun) {
    $arguments += '--dry-run'
}

Push-Location $root
try {
    "[$(Get-Date -Format s)] Starting AI execution media cleanup." | Tee-Object -FilePath $logFile -Append
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python @arguments 2>&1 | Tee-Object -FilePath $logFile -Append
    $cleanupExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    if ($cleanupExitCode -ne 0) {
        throw "AI execution media cleanup failed with exit code $cleanupExitCode"
    }
} finally {
    Pop-Location
}
