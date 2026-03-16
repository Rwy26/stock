$ErrorActionPreference = 'SilentlyContinue'

function Write-Header($title) {
  Write-Output ""
  Write-Output "=== $title ==="
}

Write-Header 'Admin'
([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Header 'MySQL Services'
Get-Service -Name 'MySQL*' -ErrorAction SilentlyContinue | Select-Object Name,Status,DisplayName | Format-Table -AutoSize | Out-String | Write-Output

Write-Header 'Port 3306 Listener'
Get-NetTCPConnection -LocalPort 3306 -ErrorAction SilentlyContinue | Select-Object -First 10 | Format-Table -AutoSize | Out-String | Write-Output

Write-Header 'Binaries'
$paths = @(
  "$env:ProgramFiles\MySQL\MySQL Server 8.4\bin",
  "$env:ProgramFiles\MySQL\MySQL Server 8.3\bin",
  "$env:ProgramFiles\MySQL\MySQL Server 8.2\bin",
  "$env:ProgramFiles\MySQL\MySQL Server 8.1\bin",
  "$env:ProgramFiles\MySQL\MySQL Server 8.0\bin"
)
foreach ($p in $paths) {
  if (Test-Path $p) { Write-Output "[FOUND] $p" }
}

where.exe mysql 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output 'mysql.exe not on PATH' }
where.exe mysqld 2>$null
if ($LASTEXITCODE -ne 0) { Write-Output 'mysqld.exe not on PATH' }

Write-Header 'backend/.env'
$repoRoot = Split-Path $PSScriptRoot -Parent
$envPath = Join-Path $repoRoot 'backend\.env'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (Test-Path $envPath) {
  Write-Output "[FOUND] $envPath"
  Get-Content $envPath | ForEach-Object {
    if ($_ -match '^MYSQL_PASSWORD=') { 'MYSQL_PASSWORD=***' } else { $_ }
  }
} else {
  Write-Output "[MISSING] $envPath"
  $svc = Get-Service -Name 'MySQL*' -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Running' } | Select-Object -First 1
  if (-not $isAdmin -and $svc) {
    Write-Output ''
    Write-Output 'Tip: MySQL service is running but backend/.env is missing.'
    Write-Output '     Run this (no admin needed) to create DB/user + backend/.env:'
    Write-Output '     pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-mysql-service.ps1 -DbOnly'
  }
}

Write-Output ''
Write-Output 'Done.'
