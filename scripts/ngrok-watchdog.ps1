# ngrok 터널 감시 — 죽어 있으면 재시작한다.
# 호출 경로 2곳: ① 작업 스케줄러 MOON-STOCK-ngrok-Watchdog (5분마다)
#               ② 시작프로그램 MOON-STOCK-ngrok.cmd (부팅 시 1회)
# ngrok 본체: C:\stock\tools\ngrok.exe (실제 파일시스템 — AppData 설치본은 샌드박스 격리로 작업 스케줄러에서 안 보였음)
# 인증토큰: backend\.env 의 NGROK_AUTHTOKEN (git 제외 — 커밋 금지)

$ErrorActionPreference = "SilentlyContinue"

$LogFile  = "C:\stock\logs\ngrok-watchdog.log"
$Domain   = "cost-negligee-violate.ngrok-free.dev"
$NgrokExe = "C:\stock\tools\ngrok.exe"
$EnvFile  = "C:\stock\backend\.env"

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    try { Add-Content -Path $LogFile -Value $line -Encoding UTF8 } catch {}
}

# 1) 터널 살아있는지 확인
$alive = $false
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:4040/api/tunnels" -UseBasicParsing -TimeoutSec 5
    $tunnels = ($resp.Content | ConvertFrom-Json).tunnels
    if ($tunnels -and ($tunnels | Where-Object { $_.public_url -like "*$Domain*" })) {
        $alive = $true
    }
} catch {}

if ($alive) { exit 0 }  # 정상 — 로그 남기지 않음 (5분 주기 소음 방지)

# 2) 죽어 있음 — 토큰 로드, 잔여 프로세스 정리 후 재시작
Write-Log "tunnel DOWN - restarting"

$token = ""
foreach ($line in (Get-Content $EnvFile -ErrorAction SilentlyContinue)) {
    if ($line -match '^\s*NGROK_AUTHTOKEN\s*=\s*(.+)\s*$') { $token = $Matches[1].Trim(); break }
}
if (-not $token) {
    Write-Log "ERROR: NGROK_AUTHTOKEN not found in backend\.env"
    exit 1
}
$env:NGROK_AUTHTOKEN = $token

Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

try {
    Start-Process -WindowStyle Hidden -FilePath $NgrokExe -ArgumentList "http", "--domain=$Domain", "--log=C:\stock\logs\ngrok.log", "8000" -ErrorAction Stop
} catch {
    Write-Log ("ERROR: failed to launch {0} - {1}" -f $NgrokExe, $_.Exception.Message)
    exit 1
}
Start-Sleep -Seconds 5

# 3) 재시작 확인
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:4040/api/tunnels" -UseBasicParsing -TimeoutSec 5
    $tunnels = ($resp.Content | ConvertFrom-Json).tunnels
    if ($tunnels -and ($tunnels | Where-Object { $_.public_url -like "*$Domain*" })) {
        Write-Log "restart OK - https://$Domain"
        exit 0
    }
} catch {}
Write-Log "restart FAILED - will retry on next run"
exit 1
