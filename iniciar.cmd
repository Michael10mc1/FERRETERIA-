@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error
if not exist "node_modules" call npm.cmd ci
if errorlevel 1 goto :error
call npm.cmd run build
if errorlevel 1 goto :error
echo.
echo Ferreteria Horizonte: http://127.0.0.1:8000
echo Manten esta ventana abierta mientras usas la tienda.
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
goto :eof
:error
echo No se pudo iniciar la aplicacion. Revisa el mensaje anterior.
pause
