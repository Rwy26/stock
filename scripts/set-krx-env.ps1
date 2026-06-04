[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$KrxId,
  [string]$KrxPw,
  [ValidateSet('BackendEnv', 'UserEnv', 'Both')]
  [string]$Target = 'Both',
  [string]$BackendEnvPath = '',
  [switch]$NoPrompt = $false
)

$ErrorActionPreference = 'Stop'

Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $BackendEnvPath) {
  $BackendEnvPath = Join-Path $PWD 'backend/.env'
}

function Mask-Value([string]$v) {
  if (-not $v) { return '(empty)' }
  if ($v.Length -le 4) { return ('*' * $v.Length) }
  return ($v.Substring(0, 2) + ('*' * ($v.Length - 4)) + $v.Substring($v.Length - 2))
}

function Read-Secret([string]$prompt) {
  $secure = Read-Host -Prompt $prompt -AsSecureString
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  }
  finally {
    if ($bstr -ne [IntPtr]::Zero) {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
  }
}

function Upsert-EnvLine([string[]]$lines, [string]$key, [string]$value) {
  $pattern = '^{0}=' -f [regex]::Escape($key)
  $newLine = '{0}={1}' -f $key, $value
  $found = $false
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($line in $lines) {
    if ($line -match $pattern) {
      if (-not $found) {
        $out.Add($newLine)
        $found = $true
      }
      continue
    }
    $out.Add($line)
  }
  if (-not $found) {
    $out.Add($newLine)
  }
  return ,$out.ToArray()
}

if (-not $KrxId) {
  $KrxId = [Environment]::GetEnvironmentVariable('KRX_ID', 'Process')
}
if (-not $KrxId) {
  $KrxId = [Environment]::GetEnvironmentVariable('KRX_ID', 'User')
}
if (-not $KrxPw) {
  $KrxPw = [Environment]::GetEnvironmentVariable('KRX_PW', 'Process')
}
if (-not $KrxPw) {
  $KrxPw = [Environment]::GetEnvironmentVariable('KRX_PW', 'User')
}

if (-not $NoPrompt) {
  if (-not $KrxId) { $KrxId = Read-Host -Prompt 'Enter KRX_ID' }
  if (-not $KrxPw) { $KrxPw = Read-Secret -prompt 'Enter KRX_PW' }
}

if (-not $KrxId -or -not $KrxPw) {
  throw 'KRX_ID and KRX_PW are required. Pass parameters, set env vars, or run without -NoPrompt to enter them interactively.'
}

if ($Target -in @('BackendEnv', 'Both')) {
  $dir = Split-Path $BackendEnvPath -Parent
  if (-not (Test-Path $dir)) {
    throw "backend env directory not found: $dir"
  }

  $lines = @()
  if (Test-Path $BackendEnvPath) {
    $lines = @(Get-Content -Path $BackendEnvPath -Encoding UTF8)
  }
  $lines = Upsert-EnvLine -lines $lines -key 'KRX_ID' -value $KrxId
  $lines = Upsert-EnvLine -lines $lines -key 'KRX_PW' -value $KrxPw

  if ($PSCmdlet.ShouldProcess($BackendEnvPath, 'Write KRX_ID/KRX_PW to backend/.env')) {
    [System.IO.File]::WriteAllLines($BackendEnvPath, $lines, [System.Text.UTF8Encoding]::new($false))
    Write-Output ("backend/.env updated: KRX_ID={0} KRX_PW={1}" -f (Mask-Value $KrxId), (Mask-Value $KrxPw))
  }
}

if ($Target -in @('UserEnv', 'Both')) {
  if ($PSCmdlet.ShouldProcess('User environment', 'Set KRX_ID/KRX_PW')) {
    [Environment]::SetEnvironmentVariable('KRX_ID', $KrxId, 'User')
    [Environment]::SetEnvironmentVariable('KRX_PW', $KrxPw, 'User')
    $env:KRX_ID = $KrxId
    $env:KRX_PW = $KrxPw
    Write-Output ("User env updated: KRX_ID={0} KRX_PW={1}" -f (Mask-Value $KrxId), (Mask-Value $KrxPw))
  }
}

Write-Output 'Done'
