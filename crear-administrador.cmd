@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ejecuta iniciar.cmd primero para preparar las dependencias.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m backend.create_admin
pause
