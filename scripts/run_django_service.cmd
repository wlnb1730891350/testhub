@echo off
setlocal
cd /d C:\Users\a\testhub_workspace\testhub_platform

:run
"C:\Users\a\testhub_workspace\testhub_platform\venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000 --noreload >> "C:\Users\a\testhub_workspace\testhub_platform\logs\django-service.stdout.log" 2>> "C:\Users\a\testhub_workspace\testhub_platform\logs\django-service.stderr.log"
timeout /t 3 /nobreak >nul
goto run
