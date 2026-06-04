[CmdletBinding()]
param(
  [switch]$SetUserEnvFromBackendEnv = $false
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

function Read-BackendEnvFile([string]$path) {
  $map = @{}
  if (-not (Test-Path $path)) { return $map }
  foreach ($line in Get-Content -Path $path -Encoding UTF8) {
    $s = [string]$line
    if ([string]::IsNullOrWhiteSpace($s)) { continue }
    $s = $s.Trim()
    if ($s.StartsWith('#')) { continue }
    $idx = $s.IndexOf('=')
    if ($idx -le 0) { continue }
    $k = $s.Substring(0, $idx).Trim()
    $v = $s.Substring($idx + 1).Trim()
    if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
      if ($v.Length -ge 2) { $v = $v.Substring(1, $v.Length - 2) }
    }
    if ($k) { $map[$k] = $v }
  }
  return $map
}

function Mask-Value([string]$v) {
  if (-not $v) { return '(empty)' }
  if ($v.Length -le 4) { return ('*' * $v.Length) }
  return ($v.Substring(0,2) + ('*' * ($v.Length - 4)) + $v.Substring($v.Length - 2))
}

function Resolve-Var([string]$name, [hashtable]$fileEnv) {
  $proc = [Environment]::GetEnvironmentVariable($name, 'Process')
  if (-not [string]::IsNullOrWhiteSpace($proc)) {
    return [PSCustomObject]@{ Name = $name; Value = $proc; Source = 'ProcessEnv' }
  }

  $user = [Environment]::GetEnvironmentVariable($name, 'User')
  if (-not [string]::IsNullOrWhiteSpace($user)) {
    return [PSCustomObject]@{ Name = $name; Value = $user; Source = 'UserEnv' }
  }

  $machine = [Environment]::GetEnvironmentVariable($name, 'Machine')
  if (-not [string]::IsNullOrWhiteSpace($machine)) {
    return [PSCustomObject]@{ Name = $name; Value = $machine; Source = 'MachineEnv' }
  }

  if ($fileEnv.ContainsKey($name) -and -not [string]::IsNullOrWhiteSpace([string]$fileEnv[$name])) {
    return [PSCustomObject]@{ Name = $name; Value = [string]$fileEnv[$name]; Source = 'backend/.env' }
  }

  return [PSCustomObject]@{ Name = $name; Value = ''; Source = 'Missing' }
}

$backendEnvPath = Join-Path $PWD 'backend/.env'
$fileEnv = Read-BackendEnvFile -path $backendEnvPath

$vars = @('KRX_ID', 'KRX_PW')
$results = @()
foreach ($name in $vars) {
  $results += Resolve-Var -name $name -fileEnv $fileEnv
}

if ($SetUserEnvFromBackendEnv) {
  foreach ($r in $results) {
    if ($r.Source -eq 'backend/.env' -and -not [string]::IsNullOrWhiteSpace([string]$r.Value)) {
      [Environment]::SetEnvironmentVariable($r.Name, [string]$r.Value, 'User')
      $r.Source = 'UserEnv(from backend/.env)'
    }
  }
}

$ok = $true
Write-Output ('backend/.env: ' + (Test-Path $backendEnvPath))
foreach ($r in $results) {
  $present = -not [string]::IsNullOrWhiteSpace([string]$r.Value)
  if (-not $present) { $ok = $false }
  $status = if ($present) { 'OK' } else { 'MISSING' }
  $len = if ($present) { ([string]$r.Value).Length } else { 0 }
  Write-Output ("{0}: {1} source={2} len={3} value={4}" -f $r.Name, $status, $r.Source, $len, (Mask-Value -v ([string]$r.Value)))
}

if ($ok) {
  Write-Output 'KRX env check: PASS'
  exit 0
}

Write-Output 'KRX env check: FAIL (set KRX_ID/KRX_PW in backend/.env or user env)'
exit 1
