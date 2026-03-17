[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
  [string]$ServiceName = 'MySQL84',
  [int]$Port = 3306,
  [string]$DbName = 'apollo_db',
  [string]$AppUser = 'apollo',
  [switch]$AutoInstallMySQL = $false
)

$ErrorActionPreference = 'Stop'

function Assert-Admin {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $isAdmin) {
    throw 'Administrator privileges are required. Re-run PowerShell/VS Code as Administrator.'
  }
}

function Resolve-Exe($name, $candidates) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
  return $null
}

Set-Location (Split-Path $PSScriptRoot -Parent)

if ($WhatIfPreference) {
  Write-Output 'WhatIf mode: no changes will be made.'
  Write-Output "Would ensure MySQL binaries are installed (AutoInstallMySQL=$AutoInstallMySQL)"
  Write-Output "Would run setup-mysql-service.ps1 for service=$ServiceName port=$Port db=$DbName user=$AppUser (with -ReinitDataDir)"
  Write-Output 'Would run init-db.ps1 to create tables'
  return
}

Assert-Admin

# Check if MySQL is installed (mysqld.exe present)
$mysqldExe = Resolve-Exe 'mysqld' @(
  "$env:ProgramFiles\MySQL\MySQL Server 8.4\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.3\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.2\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.1\bin\mysqld.exe",
  "$env:ProgramFiles\MySQL\MySQL Server 8.0\bin\mysqld.exe"
)

if (-not $mysqldExe) {
  if (-not $AutoInstallMySQL) {
    throw 'MySQL Server binaries not found. Install MySQL first (recommended): winget install -e --id Oracle.MySQL --source winget'
  }

  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw 'winget not found. Install MySQL manually, then re-run this script.'
  }

  Write-Output 'Installing MySQL via winget...'
  if (-not $PSCmdlet.ShouldProcess('winget', 'Install Oracle.MySQL')) {
    Write-Output 'Cancelled.'
    return
  }
  winget install -e --id Oracle.MySQL --source winget --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) { throw "winget install failed (exit code $LASTEXITCODE)" }
}

Write-Output 'Provisioning MySQL Windows service + backend env...'
if (-not $PSCmdlet.ShouldProcess('setup-mysql-service.ps1', 'Provision MySQL service + backend env')) {
  Write-Output 'Cancelled.'
  return
}
& .\scripts\setup-mysql-service.ps1 -ServiceName $ServiceName -Port $Port -DbName $DbName -AppUser $AppUser -ReinitDataDir

Write-Output 'Initializing DB schema (create tables)...'
if (-not $PSCmdlet.ShouldProcess('init-db.ps1', 'Initialize DB schema')) {
  Write-Output 'Cancelled.'
  return
}
& .\scripts\init-db.ps1

Write-Output ''
Write-Output 'Done.'
Write-Output "Backend DB health URL (after backend start): http://127.0.0.1:5001/api/db/health"
