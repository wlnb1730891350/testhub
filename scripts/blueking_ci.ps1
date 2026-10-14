[CmdletBinding()]
param(
    [ValidateSet('all', 'check', 'test', 'build')]
    [string]$Stage = 'all',
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$artifactRoot = Join-Path $repoRoot 'ci-artifacts'
$junitPath = Join-Path $artifactRoot 'backend-junit.xml'
$summaryPath = Join-Path $artifactRoot 'ci-summary.json'
$pytestTemp = Join-Path $artifactRoot 'pytest-temp'

function Write-Step([string]$message) {
    Write-Host "[TestHub CI] $message"
}

function Require-Command([string]$name, [string]$installHint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name is required on the BlueKing Windows agent. $installHint"
    }
}

function Invoke-Checked([string]$file, [string[]]$arguments) {
    & $file @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $file $($arguments -join ' ')"
    }
}

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null

Require-Command 'python' 'Install Python 3.12+ and expose it in PATH.'
Require-Command 'npm' 'Install Node.js 20+ and expose npm in PATH.'

$pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
$nodeVersion = (& node --version).Trim()
$npmVersion = (& npm --version).Trim()
Write-Step "Python $pythonVersion / Node $nodeVersion / npm $npmVersion"

$env:DJANGO_SETTINGS_MODULE = 'backend.settings'
$env:PYTHONPATH = "$repoRoot;$($env:PYTHONPATH)"
$env:PYTHONUTF8 = '1'
$env:TESTHUB_CI = '1'

# CI only needs Django to load for checks and unit tests. Keep credentials out of
# the pipeline and let a dedicated integration environment provide MySQL later.
if (-not $env:SECRET_KEY) { $env:SECRET_KEY = 'testhub-blueking-ci-only' }
if (-not $env:DEBUG) { $env:DEBUG = 'False' }

Push-Location $repoRoot
try {
    if ($SkipInstall) {
        Write-Step 'Skipping backend dependency installation (--SkipInstall)'
    }
    else {
        Write-Step 'Installing backend dependencies'
        Invoke-Checked 'python' @('-m', 'pip', 'install', '-r', 'requirements.txt')
    }

    if ($Stage -in @('all', 'check')) {
        Write-Step 'Running Django system checks'
        Invoke-Checked 'python' @('manage.py', 'check')
    }

    if ($Stage -in @('all', 'test')) {
        Write-Step 'Running deterministic backend tests'
        $testPaths = @(
            'apps/ui_automation/tests',
            'apps/api_testing/tests'
        )
        New-Item -ItemType Directory -Force -Path $pytestTemp | Out-Null
        Invoke-Checked 'python' @('-m', 'pytest') + $testPaths + @('-q', "--basetemp=$pytestTemp", "--junitxml=$junitPath")
    }

    if ($Stage -in @('all', 'build')) {
        Write-Step 'Installing frontend dependencies'
        Push-Location (Join-Path $repoRoot 'frontend')
        try {
            if ($SkipInstall) {
                Write-Step 'Skipping frontend dependency installation (--SkipInstall)'
            }
            else {
                Invoke-Checked 'npm' @('ci', '--no-audit', '--no-fund')
            }
            Write-Step 'Building frontend'
            Invoke-Checked 'npm' @('run', 'build')
        }
        finally {
            Pop-Location
        }
    }

    $summary = [ordered]@{
        status = 'success'
        branch = if ($env:BK_CI_BRANCH) { $env:BK_CI_BRANCH } elseif ($env:GIT_BRANCH) { $env:GIT_BRANCH } else { 'user/nn-uicase-auto' }
        stage = $Stage
        python = $pythonVersion
        node = $nodeVersion
        npm = $npmVersion
        artifacts = @(
            'ci-artifacts/backend-junit.xml',
            'frontend/dist'
        )
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -Path $summaryPath -Encoding UTF8
    Write-Step 'Pipeline completed successfully'
}
catch {
    $summary = [ordered]@{
        status = 'failed'
        stage = $Stage
        error = $_.Exception.Message
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -Path $summaryPath -Encoding UTF8
    Write-Error $_
    exit 1
}
finally {
    Pop-Location
}
