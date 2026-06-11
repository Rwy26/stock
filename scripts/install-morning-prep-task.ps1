# 아침 일정 재구성 (관리자 권한 불필요):
#   06:00  MOON-STOCK-Fundamentals-Sync  — 데이터 확인 (KIS·네이버 대조, VKOSPI, 뉴스)  [기존 07:00 → 06:00]
#   06:30  MOON-STOCK-MorningPrep        — 직전 영업일 스냅샷 + 캐시 워밍 + 검증        [신규]
#   06:50  MOON-STOCK-MorningCheck       — 최종 헬스 체크                              [기존 07:00 → 06:50]
#   20:10  MOON-STOCK-Fundamentals-Sync  — 저녁 동기화 (유지)
#
# 사용법:  .\scripts\install-morning-prep-task.ps1

$ErrorActionPreference = 'Stop'
$Py = "C:\stock\backend\.venv\Scripts\python.exe"

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 25)

# ── 1) Fundamentals-Sync: 06:00 + 20:10 으로 재등록 ──
$syncAction = New-ScheduledTaskAction -Execute $Py `
  -Argument '"C:\stock\scripts\fundamentals_sync.py"' `
  -WorkingDirectory "C:\stock\backend"
$syncTriggers = @(
  (New-ScheduledTaskTrigger -Daily -At 06:00),
  (New-ScheduledTaskTrigger -Daily -At 20:10)
)
Unregister-ScheduledTask -TaskName "MOON-STOCK-Fundamentals-Sync" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "MOON-STOCK-Fundamentals-Sync" `
  -Action $syncAction -Trigger $syncTriggers -Settings $settings | Out-Null
Write-Host "재등록: MOON-STOCK-Fundamentals-Sync (06:00, 20:10)"

# ── 2) MorningPrep: 06:30 신규 ──
$prepAction = New-ScheduledTaskAction -Execute $Py `
  -Argument '"C:\stock\scripts\morning_prep.py"' `
  -WorkingDirectory "C:\stock\backend"
Unregister-ScheduledTask -TaskName "MOON-STOCK-MorningPrep" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "MOON-STOCK-MorningPrep" `
  -Action $prepAction -Trigger (New-ScheduledTaskTrigger -Daily -At 06:30) -Settings $settings | Out-Null
Write-Host "등록: MOON-STOCK-MorningPrep (06:30)"

# ── 3) MorningCheck: 06:50 으로 이동 ──
$checkAction = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\stock\scripts\morning-check.ps1" -Silent'
Unregister-ScheduledTask -TaskName "MOON-STOCK-MorningCheck" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "MOON-STOCK-MorningCheck" `
  -Action $checkAction -Trigger (New-ScheduledTaskTrigger -Daily -At 06:50) -Settings $settings | Out-Null
Write-Host "재등록: MOON-STOCK-MorningCheck (06:50)"

Get-ScheduledTask -TaskName "MOON-STOCK-Fundamentals-Sync","MOON-STOCK-MorningPrep","MOON-STOCK-MorningCheck" |
  Select-Object TaskName, State | Format-Table -AutoSize
