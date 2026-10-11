@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m backend.presentation
if errorlevel 1 goto :error
echo Presentacion preparada. Reinicia la web con iniciar.cmd.
pause
goto :eof
:error
echo No se pudo preparar la presentacion. Revisa el mensaje anterior.
pause
