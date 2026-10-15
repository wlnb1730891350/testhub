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
$failurePath = Join-Path $artifactRoot 'backend-failures.txt'
$pytestLogPath = Join-Path $artifactRoot 'backend-pytest.log'
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

$pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
$pytestVersion = (& python -m pytest --version).Trim()
$djangoVersion = (& python -c "import django; print(django.get_version())").Trim()
$nodeVersion = (& node --version).Trim()
$npmVersion = (& npm --version).Trim()
$gitRevision = (& git rev-parse HEAD 2>$null).Trim()
$runnerIdentity = (& whoami 2>$null).Trim()
Write-Step "Git $gitRevision / Python $pythonVersion / pytest $pytestVersion / Django $djangoVersion / Node $nodeVersion / npm $npmVersion"
Write-Step "Runner $runnerIdentity / Workspace $repoRoot"

$env:DJANGO_SETTINGS_MODULE = 'backend.settings'
$env:PYTHONPATH = "$repoRoot;$($env:PYTHONPATH)"
$env:PYTHONUTF8 = '1'
$env:TESTHUB_CI = '1'

# CI only needs Django to load for checks and unit tests. Keep credentials out of
# the pipeline and let a dedicated integration environment provide MySQL later.
if (-not $env:SECRET_KEY) { $env:SECRET_KEY = 'testhub-blueking-ci-only' }
if (-not $env:DEBUG) { $env:DEBUG = 'False' }
if (-not $env:ALLOWED_HOSTS) { $env:ALLOWED_HOSTS = 'testserver,localhost,127.0.0.1' }

$dbInfo = (& python -c "import django; django.setup(); from django.conf import settings; db=settings.DATABASES['default']; print(db['ENGINE']+' / name='+str(db['NAME'])+' / host='+str(db['HOST'])+' / port='+str(db['PORT']))").Trim()
Write-Step "Django database $dbInfo"

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
        $env:TMP = $pytestTemp
        $env:TEMP = $pytestTemp
        $env:PYTEST_DEBUG_TEMPROOT = $pytestTemp
        if (Test-Path $failurePath) { Remove-Item -Force $failurePath }
        $pytestArguments = @('-m', 'pytest') + $testPaths + @(
            '-q',
            '--tb=long',
            '--show-capture=all',
            "--basetemp=$pytestTemp",
            "--junitxml=$junitPath"
        )
        try {
            & python @pytestArguments 2>&1 | Tee-Object -FilePath $pytestLogPath
            if ($LASTEXITCODE -ne 0) {
                throw "Command failed with exit code $LASTEXITCODE`: python $($pytestArguments -join ' ')"
            }
        }
        catch {
            $failureLines = @(
                "Pytest command failed: $($_.Exception.Message)",
                "Git revision: $gitRevision",
                "Python: $pythonVersion",
                "Database: $dbInfo"
            )
            if (Test-Path $junitPath) {
                try {
                    $junit = [xml](Get-Content -Raw -Path $junitPath)
                    $failedCases = @($junit.testsuites.testsuite.testcase | Where-Object { $_.failure -or $_.error })
                    if ($failedCases.Count -gt 0) {
                        $failureLines += 'Failed test cases:'
                        foreach ($case in $failedCases) {
                            $detail = if ($case.failure) { $case.failure.InnerText } else { $case.error.InnerText }
                            $failureLines += ("{0}.{1}: {2}" -f $case.classname, $case.name, (($detail -replace '\s+', ' ').Trim()))
                        }
                    }
                }
                catch {
                    $failureLines += "Could not parse pytest JUnit report: $($_.Exception.Message)"
                }
            }
            $failureLines | Set-Content -Path $failurePath -Encoding UTF8
            throw
        }
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
            'ci-artifacts/backend-failures.txt',
            'ci-artifacts/backend-pytest.log',
            'frontend/dist'
        )
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -Path $summaryPath -Encoding UTF8
    Write-Step 'Pipeline completed successfully'
}
catch {
    if (Test-Path $pytestLogPath) {
        Write-Host '[TestHub CI] Pytest log tail:'
        Get-Content -Path $pytestLogPath -Tail 120 | ForEach-Object { Write-Host "[TestHub CI] $_" }
    }
    if (Test-Path $junitPath) {
        try {
            $junit = [xml](Get-Content -Raw -Path $junitPath)
            $failedCases = @($junit.testsuites.testsuite.testcase | Where-Object { $_.failure -or $_.error })
            if ($failedCases.Count -gt 0) {
                Write-Host '[TestHub CI] Pytest failure details:'
                $failureLines = @('Pytest failure details:')
                foreach ($case in $failedCases) {
                    $detail = if ($case.failure) { $case.failure.InnerText } else { $case.error.InnerText }
                    $line = ("{0}.{1}: {2}" -f $case.classname, $case.name, (($detail -replace '\s+', ' ').Trim()))
                    Write-Host "[TestHub CI] $line"
                    $failureLines += $line
                }
                $failureLines | Set-Content -Path $failurePath -Encoding UTF8
            }
        }
        catch {
            Write-Host "[TestHub CI] Could not parse pytest JUnit report: $($_.Exception.Message)"
        }
    }
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
