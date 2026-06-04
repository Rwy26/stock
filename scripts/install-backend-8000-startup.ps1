[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$StartupDir = '',
  [string]$EntryName = 'MOON-STOCK-Backend-8000.cmd',
  [switch]$EnableLog = $false,
  [string]$LogDir = ''
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

if ($EnableLog) {
  if (-not $LogDir) {
    $LogDir = Join-Path $PWD 'logs'
  }
  $entryContent = @(
    '@echo off',
    ('if not exist "{0}" mkdir "{0}"' -f $LogDir),
    'for /f %%i in (''powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"'') do set "LOG_DATE=%%i"',
    ('set "LOG_FILE={0}\\startup-backend-8000-%LOG_DATE%.log"' -f $LogDir),
    'echo [%date% %time%] startup-run>>"%LOG_FILE%"',
    ('call "{0}" >>"%LOG_FILE%" 2>&1' -f $batchPath)
  )
} else {
  $entryContent = @(
    '@echo off',
    ('call "{0}" >nul 2>&1' -f $batchPath)
  )
}

if ($PSCmdlet.ShouldProcess($entryPath, 'Create startup launcher')) {
  [System.IO.File]::WriteAllLines($entryPath, $entryContent, [System.Text.UTF8Encoding]::new($false))
  Write-Output ("Installed startup launcher: {0}" -f $entryPath)
}
