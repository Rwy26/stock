$ErrorActionPreference = 'Stop'

Write-Output "Bootstrapping Apollo workspace..."

function Sync-ProcessPath {
  $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  $combined = @($machinePath, $userPath, $env:Path) -join ';'
  $parts = $combined -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }

  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  $deduped = foreach ($p in $parts) {
    if ($seen.Add($p)) { $p }
  }

  $env:Path = ($deduped -join ';')
}

Sync-ProcessPath

function Resolve-Exe($name, $candidates) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }

  return $null
}

function Invoke-NativeOrThrow(
  [Parameter(Mandatory = $true)][string]$FilePath,
  [Parameter(Mandatory = $true)][string[]]$ArgumentList,
  [Parameter(Mandatory = $true)][string]$Context
) {
  & $FilePath @ArgumentList
  if ($LASTEXITCODE -ne 0) {
    throw "$Context (exit code $LASTEXITCODE)"
  }
}

function Get-PythonInvoker {
  $pythonFromKnownPath = Resolve-Exe 'python' @(
    "$env:LocalAppData\Programs\Python\Python311\python.exe",
    "$env:LocalAppData\Programs\Python\Python312\python.exe",
    "$env:ProgramFiles\Python311\python.exe",
    "$env:ProgramFiles\Python312\python.exe"
  )

  if ($pythonFromKnownPath) {
    return @{ Cmd = $pythonFromKnownPath; PrefixArgs = @() }
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python -and ($python.Source -notmatch 'WindowsApps\\python\.exe$')) {
    return @{ Cmd = 'python'; PrefixArgs = @() }
  }

  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @{ Cmd = 'py'; PrefixArgs = @('-3') }
  }

  throw "python not found. Install Python 3.10+ first (or enable the Python Launcher 'py')."
}

# 1) Validate runtimes
$nodeExe = Resolve-Exe 'node' @(
  "$env:ProgramFiles\nodejs\node.exe",
  "$env:ProgramFiles(x86)\nodejs\node.exe"
)
$npmExe = Resolve-Exe 'npm' @(
  "$env:ProgramFiles\nodejs\npm.cmd",
  "$env:ProgramFiles\nodejs\npm.ps1",
  "$env:ProgramFiles(x86)\nodejs\npm.cmd",
  "$env:ProgramFiles(x86)\nodejs\npm.ps1"
)
$npxExe = Resolve-Exe 'npx' @(
  "$env:ProgramFiles\nodejs\npx.cmd",
  "$env:ProgramFiles\nodejs\npx.ps1",
  "$env:ProgramFiles(x86)\nodejs\npx.cmd",
  "$env:ProgramFiles(x86)\nodejs\npx.ps1"
)

if (-not $nodeExe) { throw "node not found. Install Node.js LTS first." }
if (-not $npmExe) { throw "npm not found. Install Node.js LTS first." }
if (-not $npxExe) { throw "npx not found. Reinstall Node.js or ensure corepack/npx is installed." }

$pythonInvoker = Get-PythonInvoker
$pythonCmd = $pythonInvoker.Cmd
$pythonPrefixArgs = $pythonInvoker.PrefixArgs

$pythonVersionOut = & $pythonCmd @($pythonPrefixArgs + @('--version')) 2>&1
$pythonVersionStr = ($pythonVersionOut | Out-String).Trim()
if ($pythonVersionStr -notmatch 'Python\s+3\.(1\d|[2-9]\d)') {
  throw "Python 3.10+ required. Detected: $pythonVersionStr. If you see a Microsoft Store prompt, disable the 'python' App Execution Alias in Windows Settings."
}

# 2) Frontend scaffold (Vite React TS)
if (-not (Test-Path -Path .\frontend)) {
  Write-Output "Creating frontend (Vite React TS)..."
  & $npxExe --yes create-vite@latest frontend --template react-ts
}

if (Test-Path -Path .\frontend\package.json) {
  $nodeModulesPath = Join-Path $PWD "frontend\node_modules"
  if (-not (Test-Path $nodeModulesPath)) {
    Write-Output "Installing frontend deps..."
    Push-Location .\frontend
    try {
      & $npmExe install
    } finally {
      Pop-Location
    }
  }
}

# 3) Backend scaffold (FastAPI)
if (-not (Test-Path -Path .\backend)) {
  Write-Output "Creating backend (FastAPI)..."
  New-Item -ItemType Directory -Path .\backend | Out-Null
}

if (-not (Test-Path -Path .\backend\.venv)) {
  Write-Output "Creating backend venv..."
  & $pythonCmd @($pythonPrefixArgs + @('-m', 'venv', '--upgrade-deps', '.\backend\.venv'))
}

$pythonExe = Join-Path $PWD "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
  throw "Virtual environment python not found at $pythonExe"
}

Write-Output "Ensuring pip in backend venv..."
& $pythonExe -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
  Invoke-NativeOrThrow $pythonExe @('-m', 'ensurepip', '--upgrade') "Failed to bootstrap pip (ensurepip)"
}

Write-Output "Installing backend deps..."
Invoke-NativeOrThrow $pythonExe @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel') "Failed to upgrade pip tooling"
Invoke-NativeOrThrow $pythonExe @('-m', 'pip', 'install', 'fastapi', 'uvicorn[standard]') "Failed to install backend dependencies"

# 4) Minimal backend app file (idempotent)
$mainPath = Join-Path $PWD "backend\main.py"
if (-not (Test-Path $mainPath)) {
  @'
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Apollo Stock Trading System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}
'@ | Set-Content -Encoding UTF8 $mainPath
}

Write-Output ""
Write-Output "Bootstrap complete."
Write-Output "Next:"
Write-Output "  Frontend: cd frontend; npm install; npm run dev"
Write-Output "  Backend:   .\\backend\\.venv\\Scripts\\python.exe -m uvicorn main:app --reload --app-dir backend --host 127.0.0.1 --port 5001"
