# TestHub 一键启动脚本
# 使用方式：PowerShell 中运行 .\start_all.ps1

$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $root "frontend"
$pythonExe = Join-Path $root "venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
$mysqld = "C:\Users\a\scoop\apps\mysql\current\bin\mysqld.exe"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-PortListening {
    param([int]$Port)

    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "=== TestHub Start ===" -ForegroundColor Cyan
Write-Host "Project: $root" -ForegroundColor DarkCyan

Write-Host "[1/3] Checking MySQL..." -ForegroundColor Yellow
if (Test-PortListening -Port 3306) {
    Write-Host "  MySQL already running on 3306" -ForegroundColor Green
} elseif (Test-Path $mysqld) {
    Start-Process -FilePath $mysqld -ArgumentList "MySQL" -WindowStyle Hidden
    Write-Host "  MySQL starting..." -ForegroundColor Green
} else {
    Write-Host "  mysqld.exe not found: $mysqld" -ForegroundColor Red
}

Write-Host "[2/3] Checking Django..." -ForegroundColor Yellow
if (Test-PortListening -Port 8001) {
    Write-Host "  Django already running on 8001" -ForegroundColor Green
} elseif (Test-Path $pythonExe) {
    $djangoCommand = "Set-Location '$root'; & '$pythonExe' manage.py runserver 127.0.0.1:8001 --noreload *>> '$logDir\django_console.log'"
    Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $djangoCommand) -WorkingDirectory $root -WindowStyle Normal
    Write-Host "  Django starting..." -ForegroundColor Green
} else {
    Write-Host "  Python not found: $pythonExe" -ForegroundColor Red
}

Write-Host "[3/3] Checking Vite..." -ForegroundColor Yellow
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
$ports = netstat -ano | Select-String ":3306|:8001|:3000" | Select-String "LISTENING"
if ($ports) {
    Write-Host $ports -ForegroundColor Green
} else {
    Write-Host "No expected listening ports detected yet, please check the service windows/logs." -ForegroundColor Red
}

Write-Host "`nFrontend: http://localhost:3000" -ForegroundColor Cyan
Write-Host "Backend : http://127.0.0.1:8001" -ForegroundColor Cyan
Write-Host "Logs    : $logDir" -ForegroundColor Cyan
