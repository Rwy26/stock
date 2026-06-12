# 키보드/마우스 무입력 10분 감지 → 프런트 재빌드 + 8000 백엔드 재시작
#
# 기준: 키보드 또는 마우스 — user32 GetLastInputInfo (시스템 마지막 입력 시각).
# 트리거 후: ① frontend npm run build ② start-backend-8000.ps1 -ForceRestart
#           ③ /health + /api/public/watchlist 확인 — 결과는 로그에 기록.
# 로그: C:\stock\logs\keyboard-idle-deploy.log
param(
  [int]$IdleSec = 600,
  [int]$PollMs = 5000
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

Log "감시 시작 — 키보드/마우스 무입력 $IdleSec 초 대기 (폴링 ${PollMs}ms)"
while ($true) {
  Start-Sleep -Milliseconds $PollMs
  if ([InputIdle]::IdleSeconds() -ge $IdleSec) { break }
}
Log "키보드/마우스 무입력 $IdleSec 초 충족 — 배포 시작"

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
