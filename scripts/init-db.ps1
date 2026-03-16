$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

$pythonExe = Join-Path $PWD 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
  throw "backend venv python not found: $pythonExe (run scripts/bootstrap.ps1 first)"
}

$envPath = Join-Path $PWD 'backend\.env'
if (-not (Test-Path $envPath)) {
  Write-Warning "backend/.env not found. Create it with MYSQL_* variables (or run scripts/setup-mysql-service.ps1 with -WriteBackendEnv)."
}

& $pythonExe .\backend\db_init.py
if ($LASTEXITCODE -ne 0) {
  throw "DB init failed (exit code $LASTEXITCODE)"
}

Write-Output "DB init complete."
