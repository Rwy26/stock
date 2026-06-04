[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$StartupDir = '',
  [string]$EntryName = 'MOON-STOCK-Backend-8000.cmd'
)

$ErrorActionPreference = 'Stop'

if (-not $StartupDir) {
  $StartupDir = [Environment]::GetFolderPath('Startup')
}

$entryPath = Join-Path $StartupDir $EntryName
if (-not (Test-Path $entryPath)) {
  Write-Output ("Startup launcher not found: {0}" -f $entryPath)
  exit 0
}

if ($PSCmdlet.ShouldProcess($entryPath, 'Remove startup launcher')) {
  Remove-Item -Path $entryPath -Force
  Write-Output ("Removed startup launcher: {0}" -f $entryPath)
}
