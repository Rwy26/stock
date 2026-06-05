[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [switch]$Uninstall = $false
)

$ErrorActionPreference = 'Stop'

$taskName   = 'MOON-STOCK-MorningCheck'
$triggerHour = 7   # 07:00 KST

Set-Location (Split-Path $PSScriptRoot -Parent)
$repoRoot = $PWD.Path

$psExe    = 'powershell.exe'
$script   = Join-Path $repoRoot 'scripts\morning-check.ps1'
$logDir   = Join-Path $repoRoot 'logs'
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" -LogDir `"$logDir`""

if ($Uninstall) {
  if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output ("Unregistered task: {0}" -f $taskName)
  }
  return
}

$trigger = New-ScheduledTaskTrigger -Daily -At ("{0}:00" -f $triggerHour)

$action = New-ScheduledTaskAction `
  -Execute $psExe `
  -Argument $argument `
  -WorkingDirectory $repoRoot

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
  -StartWhenAvailable `
  -RunOnlyIfNetworkAvailable:$false `
  -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
  -UserId ([Environment]::UserName) `
  -LogonType Interactive `
  -RunLevel Limited

if ($PSCmdlet.ShouldProcess($taskName, 'Register scheduled task')) {
  Register-ScheduledTask `
    -TaskName $taskName `
    -Trigger $trigger `
    -Action $action `
    -Settings $settings `
    -Principal $principal `
    -Description "매일 07:00 KST MOON STOCK 운영 상태 자동 점검" `
    -Force | Out-Null

  Write-Output ("Registered task: {0}" -f $taskName)
  Write-Output ("Schedule: daily at {0:00}:00 KST" -f $triggerHour)
  Write-Output ("Log dir : {0}" -f $logDir)

  $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
  if ($task) {
    Write-Output ("State   : {0}" -f $task.State)
  }
}
