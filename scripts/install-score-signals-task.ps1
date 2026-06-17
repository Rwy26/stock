[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$taskName = 'MOON-STOCK-Score-Signals'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\score_signals.py'

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered task: {0}" -f $taskName)
  }
  return
}

if (-not (Test-Path $pyExe)) { throw "venv python not found: $pyExe (run scripts/bootstrap.ps1 first)" }
if (-not (Test-Path $script)) { throw "score script not found: $script" }

# 매일 16:20 KST — 일봉 적재(16:10) 직후. 전일/당일 예측의 다음 거래일 종가로 채점.
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At '16:20')
)

$action = New-ScheduledTaskAction `
  -Execute $pyExe `
  -Argument ('"{0}"' -f $script) `
  -WorkingDirectory $repoRoot

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
  -UserId ([Environment]::UserName) `
  -LogonType Interactive `
  -RunLevel Limited

if ($PSCmdlet.ShouldProcess($taskName, 'Register scheduled task')) {
  Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $triggers `
    -Action $action `
    -Settings $settings `
    -Principal $principal `
    -Description '매일 16:20 KST AI 시그널 적중 채점 — signal_outcomes 의 미채점 예측을 다음 거래일 종가(daily_prices)로 채점' `
    -Force | Out-Null

  Write-Output ("Registered task: {0}" -f $taskName)
  Write-Output 'Schedule: daily at 16:20 KST'
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($task) { Write-Output ("State   : {0}" -f $task.State) }
}
