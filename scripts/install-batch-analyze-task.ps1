# MOON-STOCK-Batch-Analyze 등록 (관리자 권한 불필요)
# 매일 21:00 — 장 마감 + 20:10 저녁 동기화 이후 전 관심종목 AI 분석 (약 3~4시간).
# 사용법:  .\scripts\install-batch-analyze-task.ps1

$ErrorActionPreference = 'Stop'
$Py = "C:\stock\backend\.venv\Scripts\python.exe"

$action = New-ScheduledTaskAction -Execute $Py `
  -Argument '"C:\stock\scripts\batch_analyze.py"' `
  -WorkingDirectory "C:\stock\backend"

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Unregister-ScheduledTask -TaskName "MOON-STOCK-Batch-Analyze" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "MOON-STOCK-Batch-Analyze" `
  -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At 21:00) -Settings $settings | Out-Null

Write-Host "등록 완료: MOON-STOCK-Batch-Analyze (매일 21:00)"
Get-ScheduledTask -TaskName "MOON-STOCK-Batch-Analyze" | Select-Object TaskName, State
