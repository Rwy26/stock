# MOON-STOCK-Renarrate-None 등록 (관리자 권한 불필요)
# 매일 17:00 — gemini 무료 일일쿼터 리셋(PT 자정 ≈ 16:00 KST) 직후, 아침/야간 배치에서
# LLM-none(3중 폴백 레이트리밋)으로 서술이 빈 행을 renarrate_llm_none.py 무인자 동적 경로로
# 자동 재서술한다(ai_analysis_cache 에서 aiProvider='none*'/aiReport 빈 행 자동 타깃).
#
# 주의: 같은 날 21:00 batch_analyze 와 gemini 일일쿼터를 공유 → 저녁 배치 429 증가 가능.
#       문제 시 이 작업을 비활성화하거나 시각을 분산할 것.
# 사용법:  .\scripts\install-renarrate-task.ps1

$ErrorActionPreference = 'Stop'
$Py = "C:\stock\backend\.venv\Scripts\python.exe"

$action = New-ScheduledTaskAction -Execute $Py `
  -Argument '"C:\stock\scripts\renarrate_llm_none.py"' `
  -WorkingDirectory "C:\stock\backend"

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Unregister-ScheduledTask -TaskName "MOON-STOCK-Renarrate-None" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "MOON-STOCK-Renarrate-None" `
  -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 17:00) -Settings $settings | Out-Null

Write-Host "등록 완료: MOON-STOCK-Renarrate-None (매일 17:00)"
Get-ScheduledTask -TaskName "MOON-STOCK-Renarrate-None" | Select-Object TaskName, State
