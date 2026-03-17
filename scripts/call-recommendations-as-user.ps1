[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:5001',
    [string]$UserEmail = 'wind2500@gmail.com',
    [securestring]$UserPassword,
    [switch]$OnlyTokenStatus = $false,
    [switch]$OnlyRecommendations = $false
)

$ErrorActionPreference = 'Stop'

function ConvertFrom-SecureStringToPlain([securestring]$sec) {
    if ($null -eq $sec) { return '' }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

function Invoke-Json([string]$method, [string]$path, [object]$body = $null, [hashtable]$headers = @{}, [int]$timeoutSec = 30) {
    $uri = ($BaseUrl.TrimEnd('/') + $path)
    $params = @{ Method = $method; Uri = $uri; Headers = $headers; TimeoutSec = $timeoutSec }
    if ($null -ne $body) {
        $params.ContentType = 'application/json'
        $params.Body = ($body | ConvertTo-Json -Depth 10)
    }
    return Invoke-RestMethod @params
}

if ($null -eq $UserPassword) {
    $UserPassword = Read-Host -Prompt ("Password for {0}" -f $UserEmail) -AsSecureString
}

# 1) Login
$login = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{ email = $UserEmail; password = (ConvertFrom-SecureStringToPlain $UserPassword) } -timeoutSec 20
$token = $login.accessToken
if (-not $token) { throw 'Login succeeded but accessToken missing' }
$auth = @{ Authorization = ('Bearer ' + $token) }

$doToken = $true
$doRecs = $true
if ($OnlyTokenStatus -and -not $OnlyRecommendations) { $doRecs = $false }
if ($OnlyRecommendations -and -not $OnlyTokenStatus) { $doToken = $false }

if ($doToken) {
    Write-Output '=== /api/kis/token-status ==='
    $ts = Invoke-Json -method 'Get' -path '/api/kis/token-status' -headers $auth -timeoutSec 20
    $ts | ConvertTo-Json -Depth 6
}

if ($doRecs) {
    Write-Output '=== /api/recommendations ==='
    $recs = Invoke-Json -method 'Get' -path '/api/recommendations' -headers $auth -timeoutSec 60
    $recs | ConvertTo-Json -Depth 8
}
