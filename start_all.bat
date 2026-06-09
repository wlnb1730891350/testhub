@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "FRONTEND_DIR=%ROOT%\frontend"
set "PYTHON_EXE=%ROOT%\venv\Scripts\python.exe"
set "LOG_DIR=%ROOT%\logs"
set "MYSQL_EXE=C:\Users\a\scoop\apps\mysql\current\bin\mysqld.exe"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo === TestHub Start ===
echo Project: %ROOT%
echo.

call :start_mysql
call :start_django
call :start_vite

echo.
echo Waiting for services...
ping -n 9 127.0.0.1 >nul

echo.
echo === Service Status ===
netstat -ano | findstr /r /c:":3306 .*LISTENING" /c:":8001 .*LISTENING" /c:":3000 .*LISTENING"

echo.
echo Frontend: http://localhost:3000
echo Backend : http://127.0.0.1:8001
echo Logs    : %LOG_DIR%
goto :eof

:start_mysql
echo [1/3] Checking MySQL...
netstat -ano | findstr /r /c:":3306 .*LISTENING" >nul
if not errorlevel 1 (
  echo   MySQL already running on 3306
  goto :eof
)
if exist "%MYSQL_EXE%" (
  start "TestHub MySQL" "%MYSQL_EXE%" MySQL
  echo   MySQL starting...
) else (
  echo   mysqld.exe not found: %MYSQL_EXE%
)
goto :eof

:start_django
echo [2/3] Checking Django...
netstat -ano | findstr /r /c:":8001 .*LISTENING" >nul
if not errorlevel 1 (
  echo   Django already running on 8001
  goto :eof
)
if exist "%PYTHON_EXE%" (
  start "TestHub Django" cmd /k "cd /d ""%ROOT%"" && ""%PYTHON_EXE%"" manage.py runserver 127.0.0.1:8001 --noreload 1>>""%LOG_DIR%\django_stdout.log"" 2>>""%LOG_DIR%\django_stderr.log"""
  echo   Django starting...
) else (
  echo   Python not found: %PYTHON_EXE%
)
goto :eof

:start_vite
echo [3/3] Checking Vite...
netstat -ano | findstr /r /c:":3000 .*LISTENING" >nul
if not errorlevel 1 (
  echo   Vite already running on 3000
  goto :eof
)
if exist "%FRONTEND_DIR%" (
  start "TestHub Vite" cmd /k "cd /d ""%FRONTEND_DIR%"" && npm.cmd run dev 1>>""%LOG_DIR%\vite_stdout.log"" 2>>""%LOG_DIR%\vite_stderr.log"""
  echo   Vite starting...
) else (
  echo   Frontend directory not found: %FRONTEND_DIR%
)
goto :eof
