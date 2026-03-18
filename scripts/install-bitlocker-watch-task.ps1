[CmdletBinding()]
param(
  [string]$RepoPath = 'C:\stock',
  [string]$TaskName = 'stock-bitlocker-watch',
  [string]$DriveLetter = 'D'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $RepoPath)) {
  throw "RepoPath not found: $RepoPath"
}

$scriptPath = Join-Path $RepoPath 'scripts\bitlocker-watch.ps1'
if (-not (Test-Path $scriptPath)) {
  throw "Missing script: $scriptPath"
}

$pwsh = (Get-Command pwsh.exe -ErrorAction Stop).Source

$argList = @(
  '-NoProfile',
  '-ExecutionPolicy', 'Bypass',
  '-File', "`"$scriptPath`"",
  '-RepoPath', "`"$RepoPath`"",
  '-DriveLetter', $DriveLetter
)

$action = New-ScheduledTaskAction -Execute $pwsh -Argument ($argList -join ' ') -WorkingDirectory $RepoPath

# Run daily; first run ~1 minute from now.
$start = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Daily -At $start -DaysInterval 1

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew

# Run as SYSTEM with highest privileges (no password prompt, has access to BitLocker status)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal

try {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
} catch { }

Register-ScheduledTask -TaskName $TaskName -InputObject $task | Out-Null

Write-Host "Installed Scheduled Task: $TaskName"
Write-Host "- RepoPath: $RepoPath"
Write-Host "- Volume: ${DriveLetter}:"
Write-Host "- Log: $RepoPath\logs\bitlocker-watch.log"
