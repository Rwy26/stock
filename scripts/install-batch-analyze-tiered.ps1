# MOON-STOCK-Batch-Analyze 3티어 분산 등록 (관리자 권한 불필요)
#
# claude(MAX) 1순위 narrative 를 야간에 분산해, 우선순위(주도 섹터순×시총순) 상위부터
# 예산 내에서만 claude 품질을 부여한다. 예산(settings.claude_daily_cap/weekly_cap)을
# claude_usage.py 공유 원장으로 idle 필러와 함께 적용 — 소진 시 gemini/groq 로 강등.
#
#   21:00  tier=leaders  큐[0:30]   (ETF 9 + 주도주 상위 21)
#   01:00  tier=next     큐[30:70]  (다음 40)
#   03:00  tier=rest     큐[70:]    (나머지 전부)
#
# 비고: done_today() 스킵으로 티어 간 중복 분석은 자동 회피된다(재실행 안전). 일일 캡은
#       자정 리셋이라 21:00(당일)과 01:00·03:00(익일)은 서로 다른 일일 예산을 쓴다.
#       주간 캡이 전체 상한이며, 실제 소비는 logs/claude-usage.json 으로 관찰해 조정한다.
# 사용법:  .\scripts\install-batch-analyze-tiered.ps1
$ErrorActionPreference = 'Stop'
$Py = "C:\stock\backend\.venv\Scripts\python.exe"
$script = "C:\stock\scripts\batch_analyze.py"

$common = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 4)

# 기존 단일 21:00 작업은 티어 작업으로 대체 — 중복 실행 방지를 위해 제거
Unregister-ScheduledTask -TaskName "MOON-STOCK-Batch-Analyze" -Confirm:$false -ErrorAction SilentlyContinue

$tiers = @(
  @{ Name = "MOON-STOCK-Batch-Analyze-Leaders"; At = "21:00"; Tier = "leaders"; Offset = 0;  Limit = 30 },
  @{ Name = "MOON-STOCK-Batch-Analyze-Next";    At = "01:00"; Tier = "next";    Offset = 30; Limit = 40 },
  @{ Name = "MOON-STOCK-Batch-Analyze-Rest";    At = "03:00"; Tier = "rest";    Offset = 70; Limit = 0  }
)

foreach ($t in $tiers) {
  $limitArg = if ($t.Limit -gt 0) { " --limit $($t.Limit)" } else { "" }
  $arg = '"{0}" --tier {1} --offset {2}{3}' -f $script, $t.Tier, $t.Offset, $limitArg
  $action = New-ScheduledTaskAction -Execute $Py -Argument $arg -WorkingDirectory "C:\stock\backend"
  Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName $t.Name `
    -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At $t.At) -Settings $common | Out-Null
  Write-Host ("등록 완료: {0} ({1}, [{2}:{3}])" -f $t.Name, $t.At, $t.Offset, ($t.Offset + $t.Limit))
}

Get-ScheduledTask -TaskName "MOON-STOCK-Batch-Analyze-*" | Select-Object TaskName, State
