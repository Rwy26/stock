param(
  [switch]$SkipBootstrap = $false,
  [switch]$SkipInitDb = $false,
  [switch]$SkipFrontendBuild = $false,
  [switch]$SkipStartBackend = $false,
  [switch]$ForceRestartBackend = $false,

  [string]$MysqlHost = '127.0.0.1',
  [int]$MysqlPort = 3306,
  [string]$MysqlDb = 'apollo_db',
  [string]$MysqlUser = 'apollo',
  [SecureString]$MysqlPassword,
  [switch]$NoPrompt = $false
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

function Ensure-ValidTemp {
  $fallbackTemp = Join-Path $env:LOCALAPPDATA 'Temp'
  if (-not (Test-Path $fallbackTemp)) {
    New-Item -ItemType Directory -Force -Path $fallbackTemp | Out-Null
  }
  if (-not $env:TEMP -or -not (Test-Path $env:TEMP)) { $env:TEMP = $fallbackTemp }
  if (-not $env:TMP -or -not (Test-Path $env:TMP)) { $env:TMP = $fallbackTemp }
}

Ensure-ValidTemp

function New-RandomHex([int]$numBytes) {
  $bytes = New-Object byte[] $numBytes
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  return ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

function Ensure-BackendEnv {
  $envPath = Join-Path $PWD 'backend\.env'

  if (-not (Test-Path $envPath)) {
    if (-not $MysqlPassword) {
      if ($NoPrompt) {
        throw "backend/.env not found and -NoPrompt was specified. Provide -MysqlPassword or create backend/.env first."
      }
      $MysqlPassword = Read-Host -AsSecureString "Enter MySQL password for app user '$MysqlUser'"
    }

    & pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\write-backend-env.ps1 -MysqlHost $MysqlHost -Port $MysqlPort -DbName $MysqlDb -User $MysqlUser -Password $MysqlPassword -NoPrompt:$NoPrompt
  }

  $text = Get-Content -Path $envPath -Raw -ErrorAction Stop

  if ($text -notmatch "(?m)^JWT_SECRET=") {
    $secret = New-RandomHex 32
    Add-Content -Path $envPath -Value "`nJWT_SECRET=$secret" -Encoding UTF8
    $text = Get-Content -Path $envPath -Raw
  }

  if ($text -notmatch "(?m)^JWT_EXPIRE_MINUTES=") {
    Add-Content -Path $envPath -Value "`nJWT_EXPIRE_MINUTES=720" -Encoding UTF8
  }
}

Write-Output "[setup] Repo: $PWD"

if (-not $SkipBootstrap) {
  Write-Output "[setup] Running bootstrap.ps1"
  & pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
}

Write-Output "[setup] Ensuring backend/.env (MYSQL_* + JWT_*)"
Ensure-BackendEnv

if (-not $SkipInitDb) {
  Write-Output "[setup] Running init-db.ps1"
  & pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\init-db.ps1
}

if (-not $SkipFrontendBuild) {
  Write-Output "[setup] Building frontend"
  Push-Location .\frontend
  try {
    npm run build
  }
  finally {
    Pop-Location
  }
}

if (-not $SkipStartBackend) {
  Write-Output "[setup] Starting backend (detached)"
  if ($ForceRestartBackend) {
    $c = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c -and ([int]$c.OwningProcess -gt 0)) {
      Write-Output "[setup] Stopping existing 5001 listener PID=$($c.OwningProcess)"
      Stop-Process -Id ([int]$c.OwningProcess) -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 300
    }
  }
  try {
    & pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-backend-prod.ps1 -Detach
    if ($LASTEXITCODE -ne 0) {
      throw "run-backend-prod.ps1 failed (exit code $LASTEXITCODE)"
    }
  }
  catch {
    Write-Warning ("[setup] Backend start skipped/failed: " + $_.Exception.Message)
  }
}

Write-Output "[setup] Health checks"
try {
  $health = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/health -TimeoutSec 5
  Write-Output ("[setup] /health: " + $health.StatusCode)
}
catch {
  throw ("[setup] /health failed: " + $_.Exception.Message)
}

try {
  $db = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/api/db/health -TimeoutSec 5
  Write-Output "[setup] /api/db/health: OK"
}
catch {
  throw ("[setup] /api/db/health failed: " + $_.Exception.Message)
}

Write-Output "[setup] Open: http://127.0.0.1:5001/login" 
