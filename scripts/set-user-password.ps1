[CmdletBinding()]
param(
  [string]$BaseUrl = 'http://127.0.0.1:5001',
  [string]$AdminEmail = 'administrator',
  [securestring]$AdminPassword,

  [string]$TargetUserEmail = 'wind2500@gmail.com',

  # Provide either NewPassword OR -GenerateRandom
  [securestring]$NewPassword,
  [switch]$GenerateRandom,

  # If set, prints NEW_PASSWORD=... in output (use with caution).
  [switch]$PrintPassword
)

$ErrorActionPreference = 'Stop'

function ConvertFrom-SecureStringToPlain([securestring]$sec) {
  if ($null -eq $sec) { return '' }
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Invoke-Json([string]$method, [string]$path, [object]$body = $null, [hashtable]$headers = @{}) {
  $uri = ($BaseUrl.TrimEnd('/') + $path)
  $params = @{
    Method     = $method
    Uri        = $uri
    Headers    = $headers
    TimeoutSec = 15
  }
  if ($null -ne $body) {
    $params.ContentType = 'application/json'
    $params.Body = ($body | ConvertTo-Json -Depth 10)
  }
  return Invoke-RestMethod @params
}

function New-RandomPassword([int]$length = 16) {
  $alphabet = 'abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*_-'
  $bytes = New-Object byte[] ($length)
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  $chars = for ($i = 0; $i -lt $length; $i++) { $alphabet[ $bytes[$i] % $alphabet.Length ] }
  return -join $chars
}

# Admin password default (local dev)
if ($null -eq $AdminPassword) {
  $AdminPassword = ConvertTo-SecureString -String 'ChangeMe!' -AsPlainText -Force
}

if (-not $GenerateRandom -and $null -eq $NewPassword) {
  throw 'Specify -GenerateRandom or -NewPassword.'
}
if ($GenerateRandom -and $null -ne $NewPassword) {
  throw 'Use only one of -GenerateRandom or -NewPassword.'
}

$nextPlain = $null
if ($GenerateRandom) {
  $nextPlain = New-RandomPassword -length 18
} else {
  $nextPlain = ConvertFrom-SecureStringToPlain $NewPassword
}
if (-not $nextPlain) { throw 'Password must be non-empty.' }

# 1) Admin login
$admin = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{
  email = $AdminEmail
  password = (ConvertFrom-SecureStringToPlain $AdminPassword)
}
$adminToken = $admin.accessToken
if (-not $adminToken) { throw 'Admin login succeeded but accessToken missing.' }
$adminAuth = @{ Authorization = ('Bearer ' + $adminToken) }

# 2) Resolve userId
$users = Invoke-Json -method 'Get' -path '/api/admin/users' -headers $adminAuth
$target = $users.items | Where-Object { $_.email -eq $TargetUserEmail } | Select-Object -First 1
if (-not $target) { throw "Target user not found: $TargetUserEmail" }
$userId = [int]$target.id

# 3) Set password
$resp = Invoke-Json -method 'Post' -path ("/api/admin/users/{0}/reset-password" -f $userId) -headers $adminAuth -body @{ password = $nextPlain }

Write-Output ("OK: password updated for userId={0} email={1}" -f $userId, $TargetUserEmail)
if ($PrintPassword) {
  Write-Output ("NEW_PASSWORD={0}" -f $nextPlain)
}
