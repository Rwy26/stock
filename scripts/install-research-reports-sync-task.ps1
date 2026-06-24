[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$taskName = 'MOON-STOCK-Research-Reports-Sync'

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$pyExe  = Join-Path $repoRoot 'backend\.venv\Scripts\python.exe'
$script = Join-Path $repoRoot 'scripts\research_reports_sync.py'

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered task: {0}" -f $taskName)
  }
  return
}

if (-not (Test-Path $pyExe)) { throw "venv python not found: $pyExe (run scripts/bootstrap.ps1 first)" }
if (-not (Test-Path $script)) { throw "sync script not found: $script" }

# 매일 19:00 (KST) — 장 마감 후. 네이버 금융 종목분석 리포트(목표가·투자의견) 수집.
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At '19:00')
)

$action = New-ScheduledTaskAction `
  -Execute $pyExe `
  -Argument ('"{0}"' -f $script) `
  -WorkingDirectory $repoRoot

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 60) `
  -StartWhenAvailable `
  -WakeToRun `
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
    -Description '매일 19:00 KST 장 마감 후 네이버 금융 종목분석 리포트(증권사 목표가·투자의견·요약) 다이렉트 수집(kr_research_reports UPSERT). 네이버 단일 1차 출처 — KIS/주문 무관(영웅문4 거래 무방해).' `
    -Force | Out-Null

  Write-Output ("Registered task: {0}" -f $taskName)
  Write-Output 'Schedule: daily at 19:00 KST'
  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($task) { Write-Output ("State   : {0}" -f $task.State) }
}
