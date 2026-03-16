$ErrorActionPreference = 'Stop'

function Sync-ProcessPath {
  $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
  $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
  $combined = @($machinePath, $userPath, $env:Path) -join ';'
  $parts = $combined -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ }

  $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
  $deduped = foreach ($p in $parts) {
    if ($seen.Add($p)) { $p }
  }

  $env:Path = ($deduped -join ';')
}

function Resolve-Exe($name, $candidates) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }

  return $null
}

Sync-ProcessPath

# Ensure `node` is resolvable for npm.cmd/node shims even if VS Code PATH is stale
$nodeDir = Join-Path $env:ProgramFiles 'nodejs'
if (Test-Path (Join-Path $nodeDir 'node.exe')) {
  if (-not (($env:Path -split ';') -contains $nodeDir)) {
    $env:Path = "$nodeDir;$env:Path"
  }
}

Set-Location (Split-Path $PSScriptRoot -Parent)
Set-Location .\frontend

$npmExe = Resolve-Exe 'npm.cmd' @(
  "$env:ProgramFiles\nodejs\npm.cmd",
  "$env:ProgramFiles(x86)\nodejs\npm.cmd"
)
if (-not $npmExe) {
  $npmExe = Resolve-Exe 'npm' @(
    "$env:ProgramFiles\nodejs\npm.cmd",
    "$env:ProgramFiles\nodejs\npm.ps1",
    "$env:ProgramFiles(x86)\nodejs\npm.cmd",
    "$env:ProgramFiles(x86)\nodejs\npm.ps1"
  )
}

if (-not $npmExe) {
  throw 'npm not found. Install Node.js first.'
}

& $npmExe run dev
