# 사용자 무입력(idle) 시간대에 narrative 미충족 종목을 claude -p(MAX 구독)로 채우는 스케줄러.
#
# 목적: MAX 5시간/주간 한도를 인터랙티브 사용과 경쟁시키지 않고, 사용자가 자리를 비운
#       유휴 시간대에만 narrative(LLM none·빈 aiReport) 종목을 1순위 claude 경로로 보충한다.
#
# 동작(keyboard-idle-deploy.ps1 의 GetLastInputInfo 패턴 재활용):
#   1) CheckIntervalSec 간격으로 유휴초 점검. 직전 구간 입력 없으면 '무반응' 1회 누적.
#   2) 연속 무반응 RequiredMisses 회(기본 ~10분) 도달 시 '채우기 윈도우' 진입.
#   3) 윈도우 안에서 narrate_one.py --list 로 우선순위(관심종목·발행추천 먼저) 대상을 받아
#      한 종목씩 claude 1순위 경로(narrate_one.py --code)로 처리.
#   4) 매 종목 처리 직전·간격 대기 중 유휴를 재점검해, 사용자 입력이 감지되면 '즉시 일시정지'
#      (윈도우 종료, 카운터 리셋) — 인터랙티브 MAX 사용과 경쟁 방지.
#   5) MAX 한도 가드: 윈도우당 처리 상한(MaxPerWindow) + 일/주간 누적 호출 카운트
#      (logs/claude-usage.json). 주간/일일 상한 근접 시 윈도우 중단.
#
# 사용 패턴 메모(logs/idle-git-save.log·keyboard-idle-deploy.log 관찰):
#   - 유휴 사이클이 1시간 단위로 드물게 관측됨(예: 16:14 저장→17:15 입력 감지).
#   - keyboard-idle 은 ~2분 무입력부터 카운트가 안정적으로 누적됨.
#   - 따라서 정적 시간대 고정보다 동적 유휴 감지가 적합 — 본 스케줄러는 idle 실시간 적응.
#     기본 임계(10분)·윈도우 상한(20종목)은 위 관측 기준의 보수적 출발값이며, 한도 가드가
#     상한을 강제하므로 과사용 위험은 카운트 파일로 차단된다.
#
# 로그: C:\stock\logs\idle-narrative-filler.log
# 카운트: C:\stock\logs\claude-usage.json
#
# 비고: claude.cmd 는 단일 사용자 MAX 구독 전용(개발단계 전제). 외부 공개 서비스 전환 시
#       backend/market_compass._call_claude_cli 의 TODO 대로 정식 Anthropic API 로 교체할 것.
param(
  [int]$CheckIntervalSec = 60,    # 유휴 점검 간격(초)
  [int]$RequiredMisses   = 10,    # 연속 무반응 N회 → 채우기 시작(기본 ~10분)
  [int]$MaxPerWindow     = 20,    # 1회 idle 윈도우당 처리 상한(5시간 창 보호)
  # [레거시] 일/주 카운트 캡 — 롤링 5h 예산 게이트(backend/market_compass._claude_budget_exhausted)
  # 로 대체됨. 0(기본)이면 이 스크립트의 count 캡을 끄고 rolling 게이트에 위임한다. narrate_one
  # --code 호출이 예산 소진 시 자동으로 폴백(exit 1)을 받으므로 claude 사용은 전역 예산 내로 묶인다.
  # >0 으로 설정하면 추가 보조 브레이크로 동작(환경변수 CLAUDE_DAILY_CAP/CLAUDE_WEEKLY_CAP).
  [int]$DailyCap         = $(if ($env:CLAUDE_DAILY_CAP)  { [int]$env:CLAUDE_DAILY_CAP }  else { 0 }),
  [int]$WeeklyCap        = $(if ($env:CLAUDE_WEEKLY_CAP) { [int]$env:CLAUDE_WEEKLY_CAP } else { 0 }),
  [int]$StockIntervalSec = 40,    # 종목 간 간격(초) — KIS 일봉 + MAX rate 보호
  [switch]$Once                   # 1회 윈도우만 실행 후 종료(테스트용)
)
$ErrorActionPreference = 'Continue'
$repo = Split-Path $PSScriptRoot -Parent
$Py   = Join-Path $repo 'backend\.venv\Scripts\python.exe'
$helper = Join-Path $repo 'scripts\narrate_one.py'
$log  = Join-Path $repo 'logs\idle-narrative-filler.log'
$usageFile = Join-Path $repo 'logs\claude-usage.json'
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

function Get-IsoStamp {
  $now = Get-Date
  $isoYear = [System.Globalization.ISOWeek]::GetYear($now)
  $isoWeek = [System.Globalization.ISOWeek]::GetWeekOfYear($now)
  return @{
    Week = ('{0}-W{1:D2}' -f $isoYear, $isoWeek)
    Day  = $now.ToString('yyyy-MM-dd')
  }
}

# 사용 카운트 로드 — 주/일 경계가 바뀌었으면 해당 카운터를 0으로 리셋해 반환.
function Read-Usage {
  $stamp = Get-IsoStamp
  $u = [pscustomobject]@{ week = $stamp.Week; weekCount = 0; day = $stamp.Day; dayCount = 0; updatedAt = '' }
  if (Test-Path $usageFile) {
    try {
      $j = Get-Content $usageFile -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($j.week -eq $stamp.Week)  { $u.weekCount = [int]$j.weekCount }
      if ($j.day  -eq $stamp.Day)   { $u.dayCount  = [int]$j.dayCount }
    } catch { Log "usage 파일 읽기 실패(초기화): $($_.Exception.Message)" }
  }
  return $u
}

# (Save-Usage 제거됨) 원장 쓰기는 backend/market_compass._record_claude_usage 가 호출 지점에서
# 단일 소스로 담당한다. 이 스크립트는 Read-Usage 로 재조회만 해 윈도우 게이팅·표시에 쓴다.

# 유휴 대기 — total 초를 5초 청크로 쪼개 대기하되, 입력이 감지되면 즉시 $false 반환(중단 신호).
function Wait-WhileIdle([int]$total) {
  $elapsed = 0
  while ($elapsed -lt $total) {
    $chunk = [Math]::Min(5, $total - $elapsed)
    Start-Sleep -Seconds $chunk
    $elapsed += $chunk
    if ([InputIdle]::IdleSeconds() -lt $chunk) { return $false }  # 입력 감지 → 중단
  }
  return $true
}

# 한 번의 채우기 윈도우 실행. 처리한 claude 호출 수 반환.
function Invoke-FillWindow {
  $usage = Read-Usage
  if ($WeeklyCap -gt 0 -and $usage.weekCount -ge $WeeklyCap) { Log "주간 상한 도달($($usage.weekCount)/$WeeklyCap) — 윈도우 건너뜀"; return 0 }
  if ($DailyCap  -gt 0 -and $usage.dayCount  -ge $DailyCap)  { Log "일일 상한 도달($($usage.dayCount)/$DailyCap) — 윈도우 건너뜀"; return 0 }

  # 우선순위 대상 목록(관심종목·발행추천 먼저) — 윈도우 상한만큼만 요청
  $codes = @()
  try {
    Push-Location (Join-Path $repo 'backend')
    $codes = & $Py $helper '--list' $MaxPerWindow 2>&1 | Where-Object { $_ -match '^\d{6}$' }
    Pop-Location
  } catch { Log "대상 목록 조회 실패: $($_.Exception.Message)"; try { Pop-Location } catch {}; return 0 }

  if (-not $codes -or $codes.Count -eq 0) { Log "재서술 대상 없음 — 윈도우 종료"; return 0 }
  Log ("채우기 윈도우 시작 — 대상 {0}종목 (주간 {1}/{2}, 일일 {3}/{4}, 윈도우상한 {5})" -f `
        $codes.Count, $usage.weekCount, $WeeklyCap, $usage.dayCount, $DailyCap, $MaxPerWindow)

  $done = 0; $claudeCalls = 0; $i = 0
  foreach ($code in $codes) {
    $i++
    # 종목 처리 직전 입력 재점검 → 사용자 복귀 시 즉시 일시정지
    if ([InputIdle]::IdleSeconds() -lt $CheckIntervalSec) {
      Log "입력 감지 — 채우기 일시정지($i 번째 직전, 처리 $done / claude $claudeCalls)"
      break
    }
    # 한도 재확인(윈도우 진행 중 일/주 경계 변동 대비) — 캡 0 이면 rolling 게이트에 위임(스킵)
    $usage = Read-Usage
    if (($WeeklyCap -gt 0 -and $usage.weekCount -ge $WeeklyCap) -or `
        ($DailyCap  -gt 0 -and $usage.dayCount  -ge $DailyCap)) {
      Log "한도 도달(주간 $($usage.weekCount)/$WeeklyCap, 일일 $($usage.dayCount)/$DailyCap) — 윈도우 중단"
      break
    }
    if ($done -ge $MaxPerWindow) { Log "윈도우 상한 $MaxPerWindow 도달 — 종료"; break }

    Push-Location (Join-Path $repo 'backend')
    $out = & $Py $helper '--code' $code 2>&1
    $rc = $LASTEXITCODE
    Pop-Location
    $result = ($out | Where-Object { $_ -match "`t" } | Select-Object -Last 1)
    if (-not $result) { $result = ($out | Select-Object -Last 1) }

    switch ($rc) {
      0 {  # claude(MAX)가 narrative 생성 — 카운트는 backend/market_compass 가 호출 지점에서
           # 공유 원장에 이미 기록함(단일 소스). 여기선 재조회만 해 표시/게이팅에 반영(이중 카운트 방지).
        $claudeCalls++; $usage = Read-Usage
        Log "[$i/$($codes.Count)] $result | claude:max ✅ (주간 $($usage.weekCount)/$WeeklyCap, 일일 $($usage.dayCount)/$DailyCap)"
      }
      1 { Log "[$i/$($codes.Count)] $result | 폴백 생성(claude 외) — 카운트 미증가" }
      2 { Log "[$i/$($codes.Count)] $result | 여전히 none(전 프로바이더 실패)" }
      3 { Log "[$i/$($codes.Count)] $result | 제외/예외 스킵" }
      default { Log "[$i/$($codes.Count)] $result | 알 수 없는 종료코드 $rc" }
    }
    $done++

    if ($i -lt $codes.Count -and $done -lt $MaxPerWindow) {
      # 종목 간 간격 대기 — 대기 중 입력 감지 시 즉시 중단
      if (-not (Wait-WhileIdle $StockIntervalSec)) {
        Log "입력 감지 — 종목 간 대기 중 일시정지(처리 $done / claude $claudeCalls)"
        break
      }
    }
  }
  Log "채우기 윈도우 종료 — 처리 $done / claude 호출 $claudeCalls"
  return $claudeCalls
}

Log ("감시 시작 — {0}초 간격, 연속 무반응 {1}회 시 채우기 / 윈도우상한 {2} / 일일 {3} / 주간 {4}" -f `
      $CheckIntervalSec, $RequiredMisses, $MaxPerWindow, $DailyCap, $WeeklyCap)
$misses = 0
while ($true) {
  Start-Sleep -Seconds $CheckIntervalSec
  $idle = [InputIdle]::IdleSeconds()
  if ($idle -ge $CheckIntervalSec) {
    $misses++
    if ($misses -ge $RequiredMisses) {
      Log "연속 무반응 $misses 회 충족(유휴 ${idle}초) — 채우기 윈도우 진입"
      [void](Invoke-FillWindow)
      if ($Once) { Log "=== Once 모드 — 종료 ==="; break }
      $misses = 0   # 윈도우 후 리셋: 다음 채우기는 새 유휴 누적 필요(과사용 방지)
    }
  } elseif ($misses -gt 0) {
    Log "입력 감지 (유휴 ${idle}초) — 카운터 리셋 ($misses → 0)"
    $misses = 0
  }
}
