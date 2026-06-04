[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$StartupDir = '',
  [string]$EntryName = 'MOON-STOCK-Backend-8000.cmd'
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $StartupDir) {
  $StartupDir = [Environment]::GetFolderPath('Startup')
}

if (-not (Test-Path $StartupDir)) {
  throw "Startup folder not found: $StartupDir"
}

$batchPath = Join-Path $PWD 'scripts\start-backend-8000.bat'
if (-not (Test-Path $batchPath)) {
  throw "Batch launcher not found: $batchPath"
}

$entryPath = Join-Path $StartupDir $EntryName
$entryContent = @(
  '@echo off',
  ('call "{0}" >nul 2>&1' -f $batchPath)
)

if ($PSCmdlet.ShouldProcess($entryPath, 'Create startup launcher')) {
  [System.IO.File]::WriteAllLines($entryPath, $entryContent, [System.Text.UTF8Encoding]::new($false))
  Write-Output ("Installed startup launcher: {0}" -f $entryPath)
}
