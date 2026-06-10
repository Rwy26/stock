# MOON-STOCK-ngrok-Watchdog 작업 스케줄러 등록 (관리자 권한 불필요).
# 5분마다 scripts\ngrok-watchdog.ps1 실행 — 터널 죽으면 자동 재시작.
#
# 사용법:  .\scripts\install-ngrok-watchdog-task.ps1

$TaskName = "MOON-STOCK-ngrok-Watchdog"
$Script   = "C:\stock\scripts\ngrok-watchdog.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`""

# 5분 간격 무기한 반복 (시작: 등록 1분 후)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null

Write-Host "등록 완료: $TaskName (5분 간격)"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
