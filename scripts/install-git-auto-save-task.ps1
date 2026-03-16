[CmdletBinding()]
param(
  [string]$RepoPath = 'C:\stock',
  [string]$TaskName = 'stock-git-auto-save',
  [int]$EveryMinutes = 60,
  [switch]$Push
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $RepoPath)) {
  throw "RepoPath not found: $RepoPath"
}

$scriptPath = Join-Path $RepoPath 'scripts\git-auto-save.ps1'
if (-not (Test-Path $scriptPath)) {
  throw "Missing script: $scriptPath"
}

$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source

$args = @(
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', "`"$scriptPath`"",
  '-RepoPath', "`"$RepoPath`"",
  '-MessagePrefix', 'auto-save'
)
if ($Push) { $args += '-Push' }

$action = New-ScheduledTaskAction -Execute $pwsh -Argument ($args -join ' ')

# Start 1 minute from now, then repeat forever
$start = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $start
$trigger.RepetitionInterval = New-TimeSpan -Minutes $EveryMinutes
$trigger.RepetitionDuration = [TimeSpan]::MaxValue

$settings = New-ScheduledTaskSettingsSet
  -AllowStartIfOnBatteries
  -DontStopIfGoingOnBatteries
  -StartWhenAvailable
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
  -MultipleInstances IgnoreNew

# Run as current user (no password prompt), only when logged on
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel LeastPrivilege

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

# Replace if exists
try {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch { }

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "Installed Scheduled Task: $TaskName"
Write-Host "- RepoPath: $RepoPath"
Write-Host "- Interval: every $EveryMinutes minutes"
Write-Host "- Push: $Push"
Write-Host 'Tip: use Task Scheduler UI to view last run result/output.'
