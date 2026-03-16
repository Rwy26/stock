[CmdletBinding()]
param(
  [string]$TaskName = 'stock-git-auto-save'
)

$ErrorActionPreference = 'Stop'

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed Scheduled Task: $TaskName"
