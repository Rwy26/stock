[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Test-IsAdmin {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $p = New-Object Security.Principal.WindowsPrincipal($id)
  return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$regPath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'

Write-Host '=== Windows Developer Mode (AppModelUnlock) ==='
Write-Host "Admin: $(Test-IsAdmin)"

if (-not (Test-IsAdmin)) {
  Write-Host 'Not running as Administrator.'
  Write-Host 'Run this script elevated (UAC) using:'
  Write-Host '  pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-as-admin.ps1 -Script .\scripts\enable-developer-mode.ps1'
  exit 1
}

if (-not (Test-Path $regPath)) {
  New-Item -Path $regPath -Force | Out-Null
}

$before = Get-ItemProperty -Path $regPath -ErrorAction SilentlyContinue
$beforeDev = $before.AllowDevelopmentWithoutDevLicense
$beforeTrusted = $before.AllowAllTrustedApps
Write-Host ("Before: AllowDevelopmentWithoutDevLicense={0}, AllowAllTrustedApps={1}" -f ($beforeDev ?? '<null>'), ($beforeTrusted ?? '<null>'))

New-ItemProperty -Path $regPath -Name 'AllowDevelopmentWithoutDevLicense' -PropertyType DWord -Value 1 -Force | Out-Null
New-ItemProperty -Path $regPath -Name 'AllowAllTrustedApps' -PropertyType DWord -Value 1 -Force | Out-Null

$after = Get-ItemProperty -Path $regPath
Write-Host ("After:  AllowDevelopmentWithoutDevLicense={0}, AllowAllTrustedApps={1}" -f $after.AllowDevelopmentWithoutDevLicense, $after.AllowAllTrustedApps)

Write-Host 'Done. Newly started processes can create symlinks without admin (typically no reboot required).'
Write-Host 'If you still see symlink warnings, restart VS Code/terminal and retry the HF download.'
