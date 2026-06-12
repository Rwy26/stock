# 키보드/마우스 무입력 감지 → 프런트 재빌드 + 8000 백엔드 재시작
#
# 기준: 1분 간격 점검 — 직전 1분간 입력(키보드/마우스, GetLastInputInfo)이 없으면
#       '무반응' 1회. 연속 10회(=연속 무입력 ~10분) 도달 시 배포 실행.
#       입력이 감지되면 카운터 0으로 리셋.
# 트리거 후: ① frontend npm run build ② start-backend-8000.ps1 -ForceRestart
#           ③ /health + /api/public/watchlist 확인 — 결과는 로그에 기록.
# 로그: C:\stock\logs\keyboard-idle-deploy.log
param(
  [int]$CheckIntervalSec = 60,
  [int]$RequiredMisses = 10
)
$ErrorActionPreference = 'Continue'
$repo = Split-Path $PSScriptRoot -Parent
$log = Join-Path $repo 'logs\keyboard-idle-deploy.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
function Log($m) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m
  Write-Output $line
  Add-Content -Path $log -Value $line -Encoding UTF8
}

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class InputIdle {
    [StructLayout(LayoutKind.Sequential)]
    struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
    public static uint IdleSeconds() {
        var lii = new LASTINPUTINFO();
        lii.cbSize = (uint)Marshal.SizeOf(lii);
        GetLastInputInfo(ref lii);
        return ((uint)Environment.TickCount - lii.dwTime) / 1000;
    }
}
'@

Log "감시 시작 — ${CheckIntervalSec}초 간격, 연속 무반응 ${RequiredMisses}회 시 배포"
$misses = 0
while ($true) {
  Start-Sleep -Seconds $CheckIntervalSec
  $idle = [InputIdle]::IdleSeconds()
  if ($idle -ge $CheckIntervalSec) {
    $misses++
    Log "무반응 $misses/$RequiredMisses (유휴 ${idle}초)"
    if ($misses -ge $RequiredMisses) { break }
  } elseif ($misses -gt 0) {
    Log "입력 감지 (유휴 ${idle}초) — 카운터 리셋 ($misses → 0)"
    $misses = 0
  }
}
Log "연속 무반응 ${RequiredMisses}회 충족 — 배포 시작"

# ① 프런트 재빌드 (실패해도 백엔드 재시작은 진행)
$buildOk = $false
try {
  Push-Location (Join-Path $repo 'frontend')
  $out = cmd /c "npm run build 2>&1"
  $buildOk = ($LASTEXITCODE -eq 0)
  Log ("프런트 빌드: " + ($buildOk ? "성공" : "실패(exit $LASTEXITCODE)"))
  if (-not $buildOk) { ($out | Select-Object -Last 15) | ForEach-Object { Log "  npm: $_" } }
  Pop-Location
} catch { Log "프런트 빌드 예외: $($_.Exception.Message)"; try { Pop-Location } catch {} }

# ② 백엔드 재시작 (공식 스크립트 — 정지→기동→헬스 대기 포함)
$restartOk = $false
try {
  $out = & (Join-Path $repo 'scripts\start-backend-8000.ps1') -ForceRestart -TimeoutSec 40 2>&1
  $restartOk = ($LASTEXITCODE -eq 0) -or ($out -match 'Started backend')
  $out | ForEach-Object { Log "  backend: $_" }
} catch { Log "백엔드 재시작 예외: $($_.Exception.Message)" }

# ③ 검증
$health = $false; $wl = $false
try {
  $h = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 10
  $health = ($h.ok -eq $true)
} catch {}
try {
  $w = Invoke-RestMethod 'http://127.0.0.1:8000/api/public/watchlist' -TimeoutSec 30
  $wl = ($null -ne $w.items)
} catch {}
Log "검증: health=$health watchlist=$wl build=$buildOk restart=$restartOk"
if ($health -and $restartOk) { Log "=== 배포 완료 ==="; exit 0 }
Log "=== 배포 불완전 — 확인 필요 ==="
exit 1
