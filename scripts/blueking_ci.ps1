[CmdletBinding()]
param(
    [ValidateSet('all', 'check', 'test', 'build', 'web')]
    [string]$Stage = 'all',
    [switch]$SkipInstall,
    [ValidateRange(0, 1000)]
    [int]$WebCaseLimit = 3,
    [string]$WebCaseIds = '',
    [switch]$SkipArticles
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$artifactRoot = Join-Path $repoRoot 'ci-artifacts'
$junitPath = Join-Path $artifactRoot 'backend-junit.xml'
$failurePath = Join-Path $artifactRoot 'backend-failures.txt'
$pytestLogPath = Join-Path $artifactRoot 'backend-pytest.log'
$ciLogPath = Join-Path $artifactRoot 'blueking-ci.log'
$summaryPath = Join-Path $artifactRoot 'ci-summary.json'
$pytestTemp = Join-Path $artifactRoot 'pytest-temp'

function Write-Step([string]$message) {
    $line = "[TestHub CI] $message"
    Write-CapturedLine $line @($ciLogPath)
}

function Write-CapturedLine([object]$value, [string[]]$paths) {
    if ($value -is [System.Management.Automation.ErrorRecord]) {
        $line = $value.Exception.Message
    }
    else {
        $line = [string]$value
    }
    foreach ($path in $paths) {
        Add-Content -Path $path -Value $line -Encoding UTF8
    }
    # BlueKing Batch Script reliably collects stdout; keep the same text in
    # the archived UTF-8 log without relying on Tee-Object's UTF-16 default.
    Write-Output $line
    [Console]::Out.Flush()
}

function Require-Command([string]$name, [string]$installHint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name is required on the BlueKing Windows agent. $installHint"
    }
}

function Invoke-Checked([string]$file, [string[]]$arguments) {
    Write-Step "Executing: $file $($arguments -join ' ')"
    $previousErrorAction = $ErrorActionPreference
    try {
        # Windows PowerShell turns native stderr into ErrorRecord objects. With
        # ErrorActionPreference=Stop, harmless warnings can abort the CI step.
        $ErrorActionPreference = 'Continue'
        & $file @arguments 2>&1 |
            ForEach-Object { Write-CapturedLine $_ @($ciLogPath) }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    Write-Step "Completed with exit code ${exitCode}: $file"
    if ($exitCode -ne 0) {
        throw "Command failed with exit code $exitCode`: $file $($arguments -join ' ')"
    }
}

function Get-GitValue([string[]]$arguments) {
    $value = & git @('-C', $repoRoot) @arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return ''
    }
    return (($value | Out-String).Trim())
}

New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
if (Test-Path $ciLogPath) { Remove-Item -Force $ciLogPath }
Write-Step "CI script started: Stage=$Stage SkipInstall=$SkipInstall"
if ($Stage -eq 'web') {
    Write-Step "Web debug selection: limit=$WebCaseLimit case_ids=$WebCaseIds skip_articles=$SkipArticles"
}

Require-Command 'git' 'Git is required to verify the checked-out revision.'
Require-Command 'python' 'Install Python 3.12+ and expose it in PATH.'
Require-Command 'npm' 'Install Node.js 20+ and expose npm in PATH.'

$gitRevision = Get-GitValue @('rev-parse', 'HEAD')
if (-not $gitRevision) {
    throw "The BlueKing workspace is not a Git checkout: $repoRoot"
}
$checkoutBranch = Get-GitValue @('symbolic-ref', '--short', '-q', 'HEAD')
if (-not $checkoutBranch) {
    $checkoutBranch = '(detached)'
}
$expectedBranch = if ($env:BK_CI_BRANCH) { $env:BK_CI_BRANCH } elseif ($env:GIT_BRANCH) { $env:GIT_BRANCH } else { 'user/nn-uicase-auto' }
$expectedBranch = $expectedBranch -replace '^refs/heads/', ''
$expectedBranch = $expectedBranch -replace '^origin/', ''
$gitUpstream = Get-GitValue @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}')
Write-Step "Checkout $gitRevision / Branch $checkoutBranch / Upstream $(if ($gitUpstream) { $gitUpstream } else { '(none)' })"

$remoteName = if ($checkoutBranch -ne '(detached)') { Get-GitValue @('config', '--get', "branch.$checkoutBranch.remote") } else { '' }
if (-not $remoteName -or $remoteName -eq '.') {
    $remoteName = 'origin'
}
$remoteShaLine = & git -C $repoRoot ls-remote $remoteName "refs/heads/$expectedBranch" 2>$null | Select-Object -First 1
if ($LASTEXITCODE -eq 0 -and $remoteShaLine) {
    $remoteSha = (($remoteShaLine -split '\s+')[0]).Trim()
    Write-Step "Remote $remoteName/$expectedBranch $remoteSha"
    if ($remoteSha -ne $gitRevision) {
        throw "Stale checkout detected: workspace has $gitRevision but $remoteName/$expectedBranch is $remoteSha"
    }
}
else {
    Write-Step "Could not verify remote $remoteName/$expectedBranch; set BK_CI_EXPECTED_SHA to require an exact revision"
}

if ($env:BK_CI_EXPECTED_SHA -and $gitRevision -ne $env:BK_CI_EXPECTED_SHA.Trim()) {
    throw "Unexpected checkout revision: expected $($env:BK_CI_EXPECTED_SHA.Trim()) but found $gitRevision"
}

$pythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
$pytestVersion = (& python -m pytest --version).Trim()
$djangoVersion = (& python -c "import django; print(django.get_version())").Trim()
$nodeVersion = (& node --version).Trim()
$npmVersion = (& npm --version).Trim()
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
            Write-Step "Executing: python $($pytestArguments -join ' ')"
            $previousErrorAction = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                & python @pytestArguments 2>&1 |
                    ForEach-Object { Write-CapturedLine $_ @($pytestLogPath, $ciLogPath) }
                $pytestExitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $previousErrorAction
            }
            Write-Step "Completed with exit code ${pytestExitCode}: python pytest"
            if ($pytestExitCode -ne 0) {
                throw "Command failed with exit code $pytestExitCode`: python $($pytestArguments -join ' ')"
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

    if ($Stage -eq 'web') {
        # Preflight: confirm an opted-in webhook bot for AI testing exists, so the
        # run never silently skips the enterprise-WeChat/Feishu/DingTalk summary.
        # Uses the same predicate the notifier itself uses (_enabled_ai_bots).
        Write-Step 'Preflight: checking opted-in webhook bot config for AI testing'
        $preflight = & python -c "import django; django.setup(); from apps.ui_automation.ai_notifications import _enabled_ai_bots; print(len(_enabled_ai_bots()))" 2>&1
        $preflightExit = $LASTEXITCODE
        $preflightCount = 0
        if ($preflightExit -eq 0 -and ($preflight -match '^\d+$')) {
            $preflightCount = [int]$preflight
        }
        if ($preflightCount -gt 0) {
            Write-Step "Preflight OK: $preflightCount opted-in webhook bot(s) found; AI run will send summary notifications."
        }
        else {
            Write-Step "WARNING: no opted-in webhook bot for AI testing (raw='$preflight', exit=$preflightExit). The run will proceed, but NO summary notification will be sent. Configure UnifiedNotificationConfig (config_type in webhook_wechat/webhook_feishu/webhook_dingtalk, is_active=True, bot enabled + enable_ai_testing=True + webhook_url) in the CI database."
        }

        $webArguments = @('scripts/run_all_web_ai_cases.py')
        if ($WebCaseIds.Trim()) {
            $webArguments += @('--case-ids', $WebCaseIds.Trim())
        }
        else {
            $webArguments += @('--limit', [string]$WebCaseLimit)
        }
        if ($SkipArticles) {
            $webArguments += '--skip-articles'
        }
        Write-Step 'Running selected Web AI cases only (desktop cases are excluded)'
        Invoke-Checked 'python' $webArguments
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
            'ci-artifacts/blueking-ci.log',
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
