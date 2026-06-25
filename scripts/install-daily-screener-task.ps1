# MOON-STOCK-Daily-Screener 예약작업 등록
# 매일 16:35 KST (일봉 적재 16:10 이후) 약세·과열 스크리너 실행·저장.
#   설치:   .\scripts\install-daily-screener-task.ps1
#   제거:   .\scripts\install-daily-screener-task.ps1 -Uninstall
[CmdletBinding(SupportsShouldProcess = $true)]
param([switch]$Uninstall = $false)

$ErrorActionPreference = 'Stop'
$taskName = 'MOON-STOCK-Daily-Screener'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\run_daily_screener.py'

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Output "Unregistered $taskName"
  return
}

# 일봉 적재(16:10) 이후 16:35 실행
$trigger = New-ScheduledTaskTrigger -Daily -At '16:35'

$action = New-ScheduledTaskAction `
  -Execute $pyExe `
  -Argument ('"{0}" --expand 150 --compress 60' -f $script) `
  -WorkingDirectory (Join-Path $repoRoot 'backend')

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -WakeToRun `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal `
  -UserId ([Environment]::UserName) `
  -LogonType Interactive `
  -RunLevel Limited

Register-ScheduledTask `
  -TaskName $taskName `
  -Trigger $trigger `
  -Action $action `
  -Settings $settings `
  -Principal $principal `
  -Description '매일 16:35 KST 약세·과열 적출형 일일 스크리너 (관심종목+확장풀 → daily_screener_results)' `
  -Force | Out-Null

Write-Output "Registered $taskName (Daily 16:35 KST)"
