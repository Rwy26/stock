[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Script,
  [string]$Args = ''
)

$ErrorActionPreference = 'Stop'

$scriptPath = Resolve-Path $Script
$argList = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" $Args"

Start-Process -FilePath pwsh.exe -Verb RunAs -ArgumentList $argList
Write-Host "Launched elevated PowerShell: $scriptPath"
