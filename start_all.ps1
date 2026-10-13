# TestHub 一键启动脚本
# 使用方式：PowerShell 中运行 .\start_all.ps1

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $root "frontend"
$pythonExe = Join-Path $root "venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
$djangoTaskRunner = Join-Path $root "scripts\run_django_service.cmd"
$mysqld = "C:\Users\a\scoop\apps\mysql\current\bin\mysqld.exe"
$redisServer = "C:\Users\a\scoop\apps\redis\current\redis-server.exe"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-PortListening {
    param([int]$Port)

    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-ListeningProcess {
    param([int]$Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        return $null
    }

    return Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
}

function Start-ProjectDjango {
    if (Test-Path $djangoTaskRunner) {
        try {
            $shell = New-Object -ComObject Shell.Application
            $shell.ShellExecute($djangoTaskRunner, $null, $root, 'open', 0)
            return
        } catch {
            Write-Host "  Windows Shell service launch unavailable; using direct process fallback." -ForegroundColor Yellow
        }
    }

    $stdoutLog = Join-Path $logDir "django-8000.stdout.log"
    $stderrLog = Join-Path $logDir "django-8000.stderr.log"

    Start-Process -FilePath $pythonExe `
        -ArgumentList @("manage.py", "runserver", "127.0.0.1:8000", "--noreload") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
}

function Start-ProjectRedis {
    $stdoutLog = Join-Path $logDir "redis-6379.stdout.log"
    $stderrLog = Join-Path $logDir "redis-6379.stderr.log"

    Start-Process -FilePath $redisServer `
        -ArgumentList @("--bind", "127.0.0.1", "--port", "6379", "--dir", $logDir) `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
}

function Test-CeleryWorkerRunning {
    $expectedPython = [regex]::Escape($pythonExe)
    return [bool](Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^python(?:\.exe)?$' -and
        $_.CommandLine -match $expectedPython -and
        $_.CommandLine -match '-m\s+celery\s+-A\s+backend\s+worker'
    } | Select-Object -First 1)
}

function Start-ProjectCelery {
    $stdoutLog = Join-Path $logDir "celery.stdout.log"
    $stderrLog = Join-Path $logDir "celery.stderr.log"

    Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "celery", "-A", "backend", "worker", "-l", "info", "-P", "solo") `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
}

Write-Host "=== TestHub Start ===" -ForegroundColor Cyan
Write-Host "Project: $root" -ForegroundColor DarkCyan

Write-Host "[1/5] Checking MySQL..." -ForegroundColor Yellow
if (Test-PortListening -Port 3306) {
    Write-Host "  MySQL already running on 3306" -ForegroundColor Green
} elseif (Test-Path $mysqld) {
    Start-Process -FilePath $mysqld -ArgumentList "MySQL" -WindowStyle Hidden
    Write-Host "  MySQL starting..." -ForegroundColor Green
} else {
    Write-Host "  mysqld.exe not found: $mysqld" -ForegroundColor Red
}

Write-Host "[2/5] Checking Redis..." -ForegroundColor Yellow
if (Test-PortListening -Port 6379) {
    Write-Host "  Redis already running on 6379" -ForegroundColor Green
} elseif (Test-Path $redisServer) {
    Start-ProjectRedis
    Start-Sleep -Milliseconds 800
    if (Test-PortListening -Port 6379) {
        Write-Host "  Redis started on 6379" -ForegroundColor Green
    } else {
        Write-Host "  Redis failed to start; check $logDir\redis-6379.stderr.log" -ForegroundColor Red
    }
} else {
    Write-Host "  redis-server.exe not found: $redisServer" -ForegroundColor Red
}

Write-Host "[3/5] Checking Django..." -ForegroundColor Yellow
if (Test-PortListening -Port 8000) {
    $djangoProcess = Get-ListeningProcess -Port 8000
    $expectedPython = [regex]::Escape($pythonExe)
    $isProjectDjango = $djangoProcess -and
        $djangoProcess.CommandLine -match $expectedPython -and
        $djangoProcess.CommandLine -match 'manage\.py\s+runserver\s+127\.0\.0\.1:8000'

    if ($isProjectDjango) {
        Write-Host "  Django already running from project venv on 8000" -ForegroundColor Green
    } elseif ($djangoProcess -and $djangoProcess.CommandLine -match 'manage\.py\s+runserver') {
        Write-Host "  Replacing stale Django process on 8000 (PID $($djangoProcess.ProcessId))" -ForegroundColor Yellow
        Stop-Process -Id $djangoProcess.ProcessId -Force
        Start-Sleep -Milliseconds 500
        Start-ProjectDjango
        Write-Host "  Django restarting with project venv..." -ForegroundColor Green
    } else {
        Write-Host "  Port 8000 is occupied by a non-Django process (PID $($djangoProcess.ProcessId)); Django was not replaced." -ForegroundColor Red
    }
} elseif (Test-Path $pythonExe) {
    Start-ProjectDjango
    Write-Host "  Django starting..." -ForegroundColor Green
} else {
    Write-Host "  Python not found: $pythonExe" -ForegroundColor Red
}

Write-Host "[4/5] Checking Celery worker..." -ForegroundColor Yellow
if (Test-CeleryWorkerRunning) {
    Write-Host "  Celery worker already running" -ForegroundColor Green
} elseif ((Test-Path $pythonExe) -and (Test-PortListening -Port 6379)) {
    Start-ProjectCelery
    Write-Host "  Celery worker starting..." -ForegroundColor Green
} else {
    Write-Host "  Celery was not started because Python or Redis is unavailable" -ForegroundColor Red
}

Write-Host "[5/5] Checking Vite..." -ForegroundColor Yellow
if (Test-PortListening -Port 3000) {
    Write-Host "  Vite already running on 3000" -ForegroundColor Green
} elseif (Test-Path $frontendDir) {
    $viteCommand = "Set-Location '$frontendDir'; npm.cmd run dev *>> '$logDir\vite_console.log'"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $viteCommand) -WorkingDirectory $frontendDir -WindowStyle Normal
    Write-Host "  Vite starting..." -ForegroundColor Green
} else {
    Write-Host "  Frontend directory not found: $frontendDir" -ForegroundColor Red
}

Start-Sleep -Seconds 8

Write-Host "`n=== Service Status ===" -ForegroundColor Cyan
$ports = netstat -ano | Select-String ":3306|:6379|:8000|:3000" | Select-String "LISTENING"
if ($ports) {
    Write-Host $ports -ForegroundColor Green
} else {
    Write-Host "No expected listening ports detected yet, please check the service windows/logs." -ForegroundColor Red
}

Write-Host "`nFrontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Backend : http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "Logs    : $logDir" -ForegroundColor Cyan
