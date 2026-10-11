$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de Python' }
if (-not (Test-Path -LiteralPath 'node_modules')) { npm.cmd ci }
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'No se pudo compilar el frontend' }
Write-Host 'Ferretería Horizonte: http://127.0.0.1:8000'
& '.\.venv\Scripts\python.exe' -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
