[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:5001',

    # If set, do not prompt. Missing values will throw.
    [switch]$NoPrompt,

    # Admin login
    [string]$AdminEmail,
    [securestring]$AdminPassword,

    # Target user (whose automation config we will save + tick)
    [string]$UserEmail,
    [securestring]$UserPassword,
    [int]$UserId = 3,

    # Engines to test
    [ValidateSet('sa', 'plus', 'both')]
    [string]$Engine = 'both',

    # Config knobs we can safely test without order placement (no budgets)
    [int]$MaxPositions = 2,
    [int]$RotationCheckMinutes = 1,

    # How many logs to show
    [int]$LogLimit = 25,

    # If set, disables the tested engine(s) at the end to avoid ongoing tick/error logs.
    [switch]$DisableAfter
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
    $params = @{ Method = $method; Uri = $uri; Headers = $headers; TimeoutSec = 20 }
    if ($null -ne $body) {
        $params.ContentType = 'application/json'
        $params.Body = ($body | ConvertTo-Json -Depth 10)
    }
    return Invoke-RestMethod @params
}

function Read-BackendEnvFile([string]$path) {
    $map = @{}
    if (-not (Test-Path -LiteralPath $path)) { return $map }
    foreach ($line in (Get-Content -LiteralPath $path)) {
        $t = ($line ?? '').Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $idx = $t.IndexOf('=')
        if ($idx -lt 1) { continue }
        $k = $t.Substring(0, $idx).Trim()
        $v = $t.Substring($idx + 1)
        if ($k) { $map[$k] = $v }
    }
    return $map
}

function Get-Default([string]$key, [hashtable]$fileEnv) {
    $v = [Environment]::GetEnvironmentVariable($key)
    if ($v) { return $v }
    if ($fileEnv.ContainsKey($key)) { return $fileEnv[$key] }
    return $null
}

function ConvertTo-OptionalSecureString([string]$plain) {
    if (-not $plain) { return $null }
    return (ConvertTo-SecureString -String $plain -AsPlainText -Force)
}

function Test-RequiredInputsOrThrow([string[]]$names) {
    $msg = "Missing required inputs: {0}. Provide parameters, set env vars, or add them to backend/.env." -f ($names -join ', ')
    throw $msg
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendEnvPath = Join-Path $root 'backend/.env'
$backendEnv = Read-BackendEnvFile -path $backendEnvPath

# Defaults from env/backend/.env
if (-not $AdminEmail) { $AdminEmail = (Get-Default -key 'ADMIN_EMAIL' -fileEnv $backendEnv) }
if ($null -eq $AdminPassword) {
    $p = (Get-Default -key 'ADMIN_PASSWORD' -fileEnv $backendEnv)
    if ($p) { $AdminPassword = ConvertTo-OptionalSecureString -plain $p }
}

if (-not $UserEmail) { $UserEmail = (Get-Default -key 'SEED_USER_EMAIL' -fileEnv $backendEnv) }
if ($null -eq $UserPassword) {
    $p = (Get-Default -key 'SEED_USER_PASSWORD' -fileEnv $backendEnv)
    if ($p) { $UserPassword = ConvertTo-OptionalSecureString -plain $p }
}

# Dev convenience fallbacks
if (-not $AdminEmail) { $AdminEmail = 'administrator' }
if ($null -eq $AdminPassword) { $AdminPassword = (ConvertTo-SecureString -String 'ChangeMe!' -AsPlainText -Force) }

if (-not $UserEmail) { $UserEmail = 'wind2500@gmail.com' }

if ($NoPrompt) {
    $missing = @()
    if (-not $AdminEmail) { $missing += 'AdminEmail (or ADMIN_EMAIL)' }
    if ($null -eq $AdminPassword) { $missing += 'AdminPassword (or ADMIN_PASSWORD)' }
    if (-not $UserEmail) { $missing += 'UserEmail (or SEED_USER_EMAIL)' }
    if ($null -eq $UserPassword) { $missing += 'UserPassword (or SEED_USER_PASSWORD)' }
    if ($missing.Count -gt 0) { Test-RequiredInputsOrThrow -names $missing }
}
else {
    if ($null -eq $UserPassword) {
        $UserPassword = Read-Host -Prompt "User password for $UserEmail" -AsSecureString
    }
}

# Resolve engines
$engines = @()
if ($Engine -eq 'both') { $engines = @('sa', 'plus') } else { $engines = @($Engine) }

# 1) User login
$userLogin = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{
    email    = $UserEmail
    password = (ConvertFrom-SecureStringToPlain $UserPassword)
}
$userToken = $userLogin.accessToken
if (-not $userToken) { throw 'User login succeeded but accessToken missing.' }
$userAuth = @{ Authorization = ('Bearer ' + $userToken) }

# 2) Save configs (no budgets, just knobs that affect logic)
if ($engines -contains 'sa') {
    $saBody = @{ enabled = $true; config = @{ maxPositions = [int]$MaxPositions } }
    $saSave = Invoke-Json -method 'Post' -path '/api/automation/sa' -body $saBody -headers $userAuth
    if (-not $saSave.ok) { throw 'Failed to save SA config.' }
}
if ($engines -contains 'plus') {
    $plusBody = @{ enabled = $true; config = @{ maxPositions = [int]$MaxPositions; rotationCheckMinutes = [int]$RotationCheckMinutes } }
    $plusSave = Invoke-Json -method 'Post' -path '/api/automation/plus' -body $plusBody -headers $userAuth
    if (-not $plusSave.ok) { throw 'Failed to save Plus config.' }
}

# 3) Admin login
$adminLogin = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{
    email    = $AdminEmail
    password = (ConvertFrom-SecureStringToPlain $AdminPassword)
}
$adminToken = $adminLogin.accessToken
if (-not $adminToken) { throw 'Admin login succeeded but accessToken missing.' }
$adminAuth = @{ Authorization = ('Bearer ' + $adminToken) }

# 4) Manual tick
$tickBody = @{ userId = [int]$UserId; engines = $engines }
$tick = Invoke-Json -method 'Post' -path '/api/admin/engine/tick-once' -body $tickBody -headers $adminAuth

# 5) Show logs
$logs = Invoke-Json -method 'Get' -path ("/api/admin/engine-logs?userId={0}&limit={1}" -f $UserId, $LogLimit) -headers $adminAuth

# 6) Optionally disable configs after rehearsal
if ($DisableAfter) {
    if ($engines -contains 'sa') {
        $null = Invoke-Json -method 'Post' -path '/api/automation/sa' -body @{ enabled = $false; config = @{ maxPositions = [int]$MaxPositions } } -headers $userAuth
    }
    if ($engines -contains 'plus') {
        $null = Invoke-Json -method 'Post' -path '/api/automation/plus' -body @{ enabled = $false; config = @{ maxPositions = [int]$MaxPositions; rotationCheckMinutes = [int]$RotationCheckMinutes } } -headers $userAuth
    }
}

@{
    ok         = $true
    userId     = [int]$UserId
    engines    = $engines
    disabledAfter = [bool]$DisableAfter
    tick       = $tick
    lastEvents = ($logs.items | Select-Object -First 12 | Select-Object engine, event, message, at)
} | ConvertTo-Json -Depth 8
