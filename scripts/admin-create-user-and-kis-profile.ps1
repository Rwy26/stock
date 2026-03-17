[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:5001',

    # If set, do not prompt. Missing values will throw.
    [switch]$NoPrompt,

    # Admin login (email/password)
    [string]$AdminEmail,
    [securestring]$AdminPassword,

    # User to create/update
    [string]$UserEmail,
    [securestring]$UserPassword,
    [string]$UserNickname,
    [ValidateSet('user', 'admin')]
    [string]$UserRole = 'user',
    [Nullable[bool]]$UserIsActive,

    # KIS profile (stored per user)
    [string]$KisAppKey,
    [securestring]$KisAppSecret,
    [string]$AccountPrefix,
    [string]$AccountProductCode = '01',
    [ValidateSet('실계좌', '모의투자')]
    [string]$TradeType = '실계좌'
)

$ErrorActionPreference = 'Stop'

function ConvertFrom-SecureStringToPlain([securestring]$sec) {
    if ($null -eq $sec) { return '' }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Read-Required([string]$prompt) {
    $v = Read-Host -Prompt $prompt
    if (-not $v) { throw "Required: $prompt" }
    return $v
}

function Read-RequiredSecure([string]$prompt) {
    $v = Read-Host -Prompt $prompt -AsSecureString
    if ($null -eq $v -or (ConvertFrom-SecureStringToPlain $v).Length -eq 0) { throw "Required: $prompt" }
    return $v
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

function Try-Invoke-Json([string]$method, [string]$path, [object]$body = $null, [hashtable]$headers = @{}) {
    try {
        $r = Invoke-Json -method $method -path $path -body $body -headers $headers
        return @{ ok = $true; result = $r }
    }
    catch {
        $status = $null
        try {
            if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
                $status = [int]$_.Exception.Response.StatusCode
            }
        }
        catch { }
        return @{ ok = $false; status = $status; error = $_.Exception.Message }
    }
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

function To-Secure([string]$plain) {
    if (-not $plain) { return $null }
    return (ConvertTo-SecureString -String $plain -AsPlainText -Force)
}

function Throw-Missing([string[]]$names) {
    $msg = "Missing required inputs: {0}. Provide parameters, set env vars, or add them to backend/.env." -f ($names -join ', ')
    throw $msg
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$backendEnvPath = Join-Path $root 'backend/.env'
$backendEnv = Read-BackendEnvFile -path $backendEnvPath

# Load defaults from process env or backend/.env (without overriding explicit parameters)
if (-not $AdminEmail) { $AdminEmail = (Get-Default -key 'ADMIN_EMAIL' -fileEnv $backendEnv) }
if ($null -eq $AdminPassword) {
    $p = (Get-Default -key 'ADMIN_PASSWORD' -fileEnv $backendEnv)
    if ($p) { $AdminPassword = To-Secure -plain $p }
}

if (-not $UserEmail) { $UserEmail = (Get-Default -key 'SEED_USER_EMAIL' -fileEnv $backendEnv) }
if ($null -eq $UserPassword) {
    $p = (Get-Default -key 'SEED_USER_PASSWORD' -fileEnv $backendEnv)
    if ($p) { $UserPassword = To-Secure -plain $p }
}
if (-not $UserNickname) { $UserNickname = (Get-Default -key 'SEED_USER_NICKNAME' -fileEnv $backendEnv) }
if ($UserNickname -eq $null -or $UserNickname -eq '') { if ($UserEmail) { $UserNickname = $UserEmail } }

if ($null -eq $UserIsActive) {
    $raw = (Get-Default -key 'SEED_USER_IS_ACTIVE' -fileEnv $backendEnv)
    if ($raw -ne $null) {
        $UserIsActive = ($raw.Trim().ToLowerInvariant() -notin @('0', 'false', 'no', 'off', ''))
    }
}
if ($null -eq $UserIsActive) { $UserIsActive = $true }

$roleRaw = (Get-Default -key 'SEED_USER_ROLE' -fileEnv $backendEnv)
if ($roleRaw) {
    $r = $roleRaw.Trim().ToLowerInvariant()
    if ($r -in @('user', 'admin')) { $UserRole = $r }
}

if (-not $KisAppKey) { $KisAppKey = (Get-Default -key 'KIS_APP_KEY' -fileEnv $backendEnv) }
if ($null -eq $KisAppSecret) {
    $p = (Get-Default -key 'KIS_APP_SECRET' -fileEnv $backendEnv)
    if ($p) { $KisAppSecret = To-Secure -plain $p }
}
if (-not $AccountPrefix) { $AccountPrefix = (Get-Default -key 'KIS_ACCOUNT_PREFIX' -fileEnv $backendEnv) }
if (-not $AccountProductCode -or $AccountProductCode -eq '01') {
    $p = (Get-Default -key 'KIS_ACCOUNT_PRODUCT_CODE' -fileEnv $backendEnv)
    if ($p) { $AccountProductCode = $p }
}
$tt = (Get-Default -key 'KIS_TRADE_TYPE' -fileEnv $backendEnv)
if ($tt) {
    $t = $tt.Trim()
    if ($t -in @('실계좌', '모의투자')) { $TradeType = $t }
}

# --- Prompt for missing inputs ---
if ($NoPrompt) {
    $missing = @()
    if (-not $AdminEmail) { $missing += 'AdminEmail (or ADMIN_EMAIL)' }
    if ($null -eq $AdminPassword) { $missing += 'AdminPassword (or ADMIN_PASSWORD)' }
    if (-not $UserEmail) { $missing += 'UserEmail (or SEED_USER_EMAIL)' }
    if ($null -eq $UserPassword) { $missing += 'UserPassword (or SEED_USER_PASSWORD)' }
    if (-not $KisAppKey) { $missing += 'KisAppKey (or KIS_APP_KEY)' }
    if ($null -eq $KisAppSecret) { $missing += 'KisAppSecret (or KIS_APP_SECRET)' }
    if (-not $AccountPrefix) { $missing += 'AccountPrefix (or KIS_ACCOUNT_PREFIX)' }
    if ($missing.Count -gt 0) { Throw-Missing -names $missing }
}
else {
    if (-not $AdminEmail) { $AdminEmail = Read-Required '관리자 이메일(로그인 아이디) (예: administrator)' }
    if ($null -eq $AdminPassword) { $AdminPassword = Read-RequiredSecure '관리자 비밀번호' }

    if (-not $UserEmail) { $UserEmail = Read-Required '생성/설정할 사용자 이메일' }
    if ($null -eq $UserPassword) { $UserPassword = Read-RequiredSecure '생성/설정할 사용자 비밀번호' }
    if (-not $UserNickname) { $UserNickname = $UserEmail }

    if (-not $KisAppKey) {
        # Treat App Key as sensitive when entered interactively (avoid console echo).
        $KisAppKey = (ConvertFrom-SecureStringToPlain (Read-RequiredSecure 'KIS App Key'))
    }
    if ($null -eq $KisAppSecret) { $KisAppSecret = Read-RequiredSecure 'KIS App Secret' }
    if (-not $AccountPrefix) { $AccountPrefix = Read-Required '계좌번호 앞 8자리(Account Prefix)' }
}

# Basic validation (fail early)
if ($AccountPrefix -and ($AccountPrefix -notmatch '^[0-9]{8}$')) {
    throw "AccountPrefix must be exactly 8 digits (got: '$AccountPrefix')"
}
if ($AccountProductCode -and ($AccountProductCode -notmatch '^[0-9]{2}$')) {
    throw "AccountProductCode must be 2 digits (e.g., 01)"
}

# --- 1) Admin login ---
$loginBody = @{
    email    = $AdminEmail
    password = (ConvertFrom-SecureStringToPlain $AdminPassword)
}
$login = Try-Invoke-Json -method 'Post' -path '/api/auth/login' -body $loginBody
if (-not $login.ok) {
    if ($login.status) { throw "Admin login failed (HTTP $($login.status)). Check admin email/password." }
    throw "Admin login failed: $($login.error)"
}

$token = $login.result.accessToken
if (-not $token) { throw 'Admin login succeeded but accessToken missing.' }

$authHeaders = @{ Authorization = ('Bearer ' + $token) }
Write-Host "OK: Admin login as '$AdminEmail'" 

# --- 2) Create user (or re-use existing if email already exists) ---
$createBody = @{
    email    = $UserEmail
    password = (ConvertFrom-SecureStringToPlain $UserPassword)
    nickname = $UserNickname
    role     = $UserRole
    isActive = [bool]$UserIsActive
}

$created = Try-Invoke-Json -method 'Post' -path '/api/admin/users' -body $createBody -headers $authHeaders
$userId = $null

if ($created.ok) {
    $userId = [int]$created.result.id
    Write-Host "OK: User created id=$userId email='$UserEmail' role='$UserRole'" 
}
else {
    if ($created.status -eq 409) {
        Write-Host "INFO: User already exists for email='$UserEmail' (409). Will look up userId." 
        $list = Try-Invoke-Json -method 'Get' -path '/api/admin/users' -headers $authHeaders
        if (-not $list.ok) {
            throw "Failed to list users to resolve existing userId (HTTP $($list.status))."
        }
        $match = $list.result.items | Where-Object { $_.email -eq $UserEmail } | Select-Object -First 1
        if (-not $match) { throw "User email exists but not found in list: '$UserEmail'" }
        $userId = [int]$match.id
        Write-Host "OK: Using existing user id=$userId email='$UserEmail'" 
    }
    else {
        if ($created.status) { throw "User create failed (HTTP $($created.status)): $($created.error)" }
        throw "User create failed: $($created.error)"
    }
}

# --- 3) Upsert KIS profile for that user ---
$kisBody = @{
    appKey             = $KisAppKey
    appSecret          = (ConvertFrom-SecureStringToPlain $KisAppSecret)
    accountPrefix      = $AccountPrefix
    accountProductCode = $AccountProductCode
    tradeType          = $TradeType
}

$up = Try-Invoke-Json -method 'Put' -path ("/api/admin/users/{0}/kis-profile" -f $userId) -body $kisBody -headers $authHeaders
if (-not $up.ok) {
    if ($up.status) { throw "KIS profile upsert failed (HTTP $($up.status)): $($up.error)" }
    throw "KIS profile upsert failed: $($up.error)"
}

Write-Host ("OK: KIS profile saved for userId={0} (kisConfigured={1})" -f $userId, $up.result.kisConfigured)

# --- 4) Read back (does not return secret) ---
$get = Try-Invoke-Json -method 'Get' -path ("/api/admin/users/{0}/kis-profile" -f $userId) -headers $authHeaders
if ($get.ok) {
    $hasSecret = [bool]$get.result.hasAppSecret
    $tradeTypeEcho = $get.result.tradeType
    $accountPrefixEcho = $get.result.accountPrefix
    $prdtEcho = $get.result.accountProductCode
    Write-Host ("OK: KIS profile verify (hasAppSecret={0}, tradeType={1}, accountPrefix={2}, accountProductCode={3})" -f $hasSecret, $tradeTypeEcho, $accountPrefixEcho, $prdtEcho)
}
else {
    Write-Warning "WARN: Could not verify KIS profile via GET (HTTP $($get.status))"
}

Write-Host 'DONE.'
