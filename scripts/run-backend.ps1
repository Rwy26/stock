$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

$pythonExe = Join-Path $PWD 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
  throw "backend venv python not found: $pythonExe"
}

& $pythonExe -m uvicorn main:app --reload --app-dir backend --host 127.0.0.1 --port 5001
