[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

& (Join-Path $PSScriptRoot 'stop-backend.ps1') -Port 8000
