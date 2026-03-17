[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:5001',
    [string]$AdminEmail = 'administrator',
    [securestring]$AdminPassword,
    [string]$TargetUserEmail = 'wind2500@gmail.com'
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

function Probe([string]$label, [scriptblock]$fn) {
    try {
        & $fn | Out-Null
        Write-Output ("{0}=OK" -f $label)
    }
    catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            Write-Output ("{0}=HTTP_{1}" -f $label, ([int]$_.Exception.Response.StatusCode))
        }
        else {
            Write-Output ("{0}=FAIL" -f $label)
        }
    }
}

if ($null -eq $AdminPassword) {
    # For local dev convenience only; do not echo.
    $AdminPassword = ConvertTo-SecureString -String 'ChangeMe!' -AsPlainText -Force
}

# 1) Admin login
$admin = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{
    email    = $AdminEmail
    password = (ConvertFrom-SecureStringToPlain $AdminPassword)
}
$adminToken = $admin.accessToken
if (-not $adminToken) { throw 'Admin login succeeded but accessToken missing.' }
$adminAuth = @{ Authorization = ('Bearer ' + $adminToken) }

# 2) Find target user
$users = Invoke-Json -method 'Get' -path '/api/admin/users' -headers $adminAuth
$target = $users.items | Where-Object { $_.email -eq $TargetUserEmail } | Select-Object -First 1
if (-not $target) { throw "Target user not found: $TargetUserEmail" }
$userId = [int]$target.id

# 3) Reset target password to a generated temp password (do not print)
$reset = Invoke-Json -method 'Post' -path ("/api/admin/users/{0}/reset-password" -f $userId) -headers $adminAuth -body @{}
$tempPassword = $reset.tempPassword
if (-not $tempPassword) { throw 'Expected tempPassword in reset-password response.' }

# 4) Target user login with temp password
$userLogin = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{
    email    = $TargetUserEmail
    password = $tempPassword
}
$userToken = $userLogin.accessToken
if (-not $userToken) { throw 'User login succeeded but accessToken missing.' }
$userAuth = @{ Authorization = ('Bearer ' + $userToken) }

# 5) Probes
Probe 'SA_CFG_GET' { Invoke-Json -method 'Get' -path '/api/automation/sa' -headers $userAuth }
Probe 'PLUS_CFG_GET' { Invoke-Json -method 'Get' -path '/api/automation/plus' -headers $userAuth }
Probe 'SA_POS_GET' { Invoke-Json -method 'Get' -path '/api/automation/sa/positions' -headers $userAuth }
Probe 'SA_LOGS_GET' { Invoke-Json -method 'Get' -path '/api/automation/sa/logs?limit=5' -headers $userAuth }
Probe 'PLUS_POS_GET' { Invoke-Json -method 'Get' -path '/api/automation/plus/positions' -headers $userAuth }
Probe 'PLUS_LOGS_GET' { Invoke-Json -method 'Get' -path '/api/automation/plus/logs?limit=5' -headers $userAuth }

Write-Output 'DONE'
