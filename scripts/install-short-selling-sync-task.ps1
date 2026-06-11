[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$taskName = 'MOON-STOCK-Short-Selling-Sync'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\short_selling_sync.py'

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered task: {0}" -f $taskName)
  }
  return
}

if (-not (Test-Path $pyExe)) { throw "venv python not found: $pyExe (run scripts/bootstrap.ps1 first)" }
if (-not (Test-Path $script)) { throw "sync script not found: $script" }

# 매일 18:40 KST — 공매도 거래량(T+1)·잔고(T+2)는 장 마감 후 공표
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At '18:40')
)

$action = New-ScheduledTaskAction `
  -Execute $pyExe `
  -Argument ('"{0}"' -f $script) `
  -WorkingDirectory $repoRoot

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
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
    -Description '매일 18:40 KST 전 종목 공매도 거래량(KIS)·잔고(KRX) short_selling_daily 동기화 — 스코어링 위험2(공매도 급증) 데이터' `
    -Force | Out-Null

  Write-Output ("Registered task: {0}" -f $taskName)
  Write-Output 'Schedule: daily at 18:40 KST'
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($task) { Write-Output ("State   : {0}" -f $task.State) }
}
