# TestHub 一键启动脚本
# 使用方式：PowerShell 中运行 .\start_all.ps1

$ErrorActionPreference = "Continue"

Write-Host "=== TestHub Start ===" -ForegroundColor Cyan

# 1. 启动 MySQL
Write-Host "[1/3] Starting MySQL..." -ForegroundColor Yellow
$mysqld = "C:\Users\a\scoop\apps\mysql\current\bin\mysqld.exe"
if (Test-Path $mysqld) {
    Start-Process -FilePath $mysqld -WindowStyle Normal
    Write-Host "  MySQL starting..." -ForegroundColor Green
} else {
    Write-Host "  mysqld.exe not found: $mysqld" -ForegroundColor Red
}

# 2. 启动 Django (独立窗口) - 用数组传参避免 -NoExit 被错误解析
Write-Host "[2/3] Starting Django..." -ForegroundColor Yellow
$djangoArgs = @(
    "-NoExit",
    "-Command",
    "cd C:\Users\a\.qclaw\workspace\testhub_platform; .\venv\Scripts\Activate.ps1; python manage.py runserver 127.0.0.1:8000 --noreload"
)
Start-Process -FilePath "powershell.exe" -ArgumentList $djangoArgs -WindowStyle Normal
Write-Host "  Django starting..." -ForegroundColor Green

# 3. 启动 Vite (独立窗口)
Write-Host "[3/3] Starting Vite..." -ForegroundColor Yellow
$viteArgs = @(
    "-NoExit",
    "-Command",
    "cd C:\Users\a\.qclaw\workspace\testhub_platform\frontend; npm.cmd run dev"
)
Start-Process -FilePath "powershell.exe" -ArgumentList $viteArgs -WindowStyle Normal
Write-Host "  Vite starting..." -ForegroundColor Green

# 等待并检查
Start-Sleep -Seconds 8

Write-Host "`n=== Service Status ===" -ForegroundColor Cyan
$ports = netstat -ano | Select-String ":3306|:8000|:3000" | Select-String "LISTENING"
if ($ports) {
    Write-Host $ports -ForegroundColor Green
} else {
    Write-Host "Some services may not have started, please check" -ForegroundColor Red
}

Write-Host "`nDone! Visit http://localhost:3000" -ForegroundColor Cyan
Write-Host "Press Enter to exit..." -ForegroundColor Gray
Read-Host
