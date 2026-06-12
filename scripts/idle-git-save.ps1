# 키보드/마우스 무입력 10분 감지 → git commit + push
#
# 동작:
#   - 30초마다 유휴 시간 측정
#   - 유휴 >= 600초(10분) 도달 → git-auto-save.ps1 -Push 실행
#   - 저장 후 사용자 입력이 다시 감지될 때까지 대기 → 재감시 반복
#   - 저장소: $Repos 배열 (현재 C:\stock)
# 로그: C:\stock\logs\idle-git-save.log

param(
    [int]$IdleThresholdSec = 600,
    [int]$CheckIntervalSec = 60
)

$ErrorActionPreference = 'Continue'
$scriptDir  = Split-Path $PSScriptRoot -Parent   # C:\stock
$logPath    = Join-Path $scriptDir 'logs\idle-git-save.log'
$saveScript = Join-Path $scriptDir 'scripts\git-auto-save.ps1'

# 저장 대상 저장소 목록 (git 저장소 경로)
$Repos = @(
    'C:\stock'
)

New-Item -ItemType Directory -Force (Split-Path $logPath) | Out-Null

function Log($m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'), $m
    Write-Output $line
    Add-Content -Path $logPath -Value $line -Encoding UTF8
}

# Windows API: 마지막 입력(키보드/마우스) 이후 경과 초
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class IdleDetector {
    [StructLayout(LayoutKind.Sequential)]
    struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO p);
    public static uint IdleSeconds() {
        var lii = new LASTINPUTINFO();
        lii.cbSize = (uint)Marshal.SizeOf(lii);
        GetLastInputInfo(ref lii);
        return ((uint)Environment.TickCount - lii.dwTime) / 1000;
    }
}
'@ -ErrorAction SilentlyContinue   # 재실행 시 이미 정의된 경우 무시

function Save-AllRepos {
    foreach ($repo in $Repos) {
        if (-not (Test-Path "$repo\.git")) {
            Log "건너뜀 (git 저장소 아님): $repo"
            continue
        }
        Log "저장 시작: $repo"
        try {
            $out = & pwsh -NoProfile -ExecutionPolicy Bypass `
                -File $saveScript `
                -RepoPath $repo `
                -MessagePrefix 'idle-save' `
                -Push 2>&1
            $out | ForEach-Object { Log "  $_" }
            Log "저장 완료: $repo"
        } catch {
            Log "저장 오류 ($repo): $($_.Exception.Message)"
        }
    }
}

Log "=== idle-git-save 시작 (임계값 ${IdleThresholdSec}초, 점검 ${CheckIntervalSec}초 간격) ==="

$saved = $false   # 이번 유휴 사이클에서 이미 저장했는지 여부

while ($true) {
    Start-Sleep -Seconds $CheckIntervalSec
    $idle = [IdleDetector]::IdleSeconds()

    if ($idle -lt 60) {
        # 사용자 활동 감지 → 저장 플래그 초기화
        if ($saved) {
            Log "입력 감지 (유휴 ${idle}초) — 다음 유휴 사이클 대기"
            $saved = $false
        }
        continue
    }

    if ($idle -ge $IdleThresholdSec -and -not $saved) {
        Log "무입력 ${idle}초 — 자동 저장 실행"
        Save-AllRepos
        $saved = $true
        Log "=== 저장 완료, 다음 입력 후 재감시 ==="
    }
}
