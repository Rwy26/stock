param(
  [string]$MysqlHost = '127.0.0.1',
  [int]$Port = 3306,
  [string]$DbName = 'apollo_db',
  [string]$User = 'apollo',
  [SecureString]$Password,
  [switch]$NoPrompt = $false
)

$ErrorActionPreference = 'Stop'

function Get-PlainText([Security.SecureString]$secure) {
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try {
    return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

if (-not $Password) {
  if ($NoPrompt) {
    throw 'Password is required when -NoPrompt is specified.'
  }
  $Password = Read-Host -AsSecureString "Enter MySQL password for app user '$User'"
}

$plain = Get-PlainText $Password

$repoRoot = Split-Path $PSScriptRoot -Parent
$backendEnvPath = Join-Path $repoRoot 'backend\.env'

$lines = @(
  "MYSQL_HOST=$MysqlHost",
  "MYSQL_PORT=$Port",
  "MYSQL_DB=$DbName",
  "MYSQL_USER=$User",
  "MYSQL_PASSWORD=$plain"
)

$lines | Set-Content -Path $backendEnvPath -Encoding UTF8
Write-Output "Wrote: $backendEnvPath"
