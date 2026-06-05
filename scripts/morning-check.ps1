[CmdletBinding()]
param(
  [string]$BaseUrl = 'http://127.0.0.1:8000',
  [string]$LogDir  = '',
  [switch]$Silent  = $false
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $LogDir) {
  $LogDir = Join-Path $PWD 'logs'
}
if (-not (Test-Path $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$stamp = Get-Date -Format 'yyyyMMdd'
$ts    = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$logFile = Join-Path $LogDir ("morning-check-{0}.log" -f $stamp)

function Write-Log([string]$level, [string]$msg) {
  $line = "[{0}] {1}  {2}" -f $ts, $level.PadRight(4), $msg
  Add-Content -Path $logFile -Value $line -Encoding UTF8
  if (-not $Silent) { Write-Output $line }
}

function Ok([string]$msg)   { Write-Log 'OK  ' $msg }
function Warn([string]$msg) { Write-Log 'WARN' $msg }
function Fail([string]$msg) { Write-Log 'FAIL' $msg; $script:HadFail = $true }

$HadFail = $false

Write-Log 'INFO' ("=== Morning check started: {0} ===" -f $ts)

# 1) .env 파일 존재 확인
$envPath = Join-Path $PWD 'backend\.env'
if (Test-Path $envPath) { Ok "backend/.env found" }
else { Fail "backend/.env NOT FOUND" }

# 2) KRX 환경변수 확인
foreach ($key in @('KRX_ID', 'KRX_PW')) {
  $v = ''
  if (Test-Path $envPath) {
    $line = Get-Content -Path $envPath -Encoding UTF8 | Where-Object { $_ -match "^{0}=" -f $key } | Select-Object -First 1
    if ($line) { $v = $line.Split('=', 2)[1] }
  }
  if (-not $v) { $v = [Environment]::GetEnvironmentVariable($key, 'User') }
  if (-not $v) { $v = [Environment]::GetEnvironmentVariable($key, 'Process') }

  if ($v) { Ok ("{0} is set (len={1})" -f $key, $v.Length) }
  else     { Warn ("{0} is NOT SET" -f $key) }
}

# 3) 백엔드 프로세스 확인 + 없으면 자동 기동
$conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
  Ok ("backend listening on :8000 PID={0}" -f ($conn | Select-Object -ExpandProperty OwningProcess -Unique | Select-Object -First 1))
} else {
  Warn "backend not running on :8000 — attempting auto-start"
  try {
    $startScript = Join-Path $PWD 'scripts\start-backend-8000.ps1'
    & $startScript -Detach
    Start-Sleep -Seconds 5
    $conn2 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($conn2) { Ok "backend started successfully" }
    else        { Fail "backend auto-start failed" }
  } catch {
    Fail ("backend auto-start error: " + $_.Exception.Message)
  }
}

# 4) /health 확인
try {
  $h = Invoke-RestMethod -Uri ("{0}/health" -f $BaseUrl.TrimEnd('/')) -TimeoutSec 5
  if ($h.ok -eq $true) { Ok "/health ok" }
  else                  { Fail "/health returned ok!=true" }
} catch {
  Fail ("/health failed: " + $_.Exception.Message)
}

# 5) /api/db/health 확인
try {
  $dbh = Invoke-RestMethod -Uri ("{0}/api/db/health" -f $BaseUrl.TrimEnd('/')) -TimeoutSec 8
  if ($dbh.ok -eq $true) { Ok "/api/db/health ok" }
  else                    { Fail ("/api/db/health returned: " + ($dbh | ConvertTo-Json -Compress)) }
} catch {
  Fail ("/api/db/health failed: " + $_.Exception.Message)
}

# 6) /api/kis/health 확인 (KIS 연결 상태)
try {
  $kish = Invoke-RestMethod -Uri ("{0}/api/kis/health" -f $BaseUrl.TrimEnd('/')) -TimeoutSec 10
  if ($kish.ok -eq $true) { Ok "/api/kis/health ok" }
  else                     { Warn ("/api/kis/health: " + ($kish | ConvertTo-Json -Compress)) }
} catch {
  Warn ("/api/kis/health failed (non-fatal): " + $_.Exception.Message)
}

# 7) venv python 존재 확인
$pythonExe = Join-Path $PWD 'backend\.venv\Scripts\python.exe'
if (Test-Path $pythonExe) { Ok "backend venv python found" }
else                      { Fail "backend venv python NOT FOUND: $pythonExe" }

# 8) backend/main.py 문법 검사
try {
  $result = & $pythonExe -m py_compile (Join-Path $PWD 'backend\main.py') 2>&1
  if ($LASTEXITCODE -eq 0) { Ok "main.py syntax ok" }
  else                     { Fail ("main.py syntax error: " + $result) }
} catch {
  Fail ("main.py compile check failed: " + $_.Exception.Message)
}

$summary = if ($HadFail) { 'FAIL' } else { 'PASS' }
Write-Log 'INFO' ("=== Morning check done: {0} ===" -f $summary)

if ($HadFail) { exit 1 }
exit 0
