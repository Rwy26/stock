[CmdletBinding()]
param(
    [string]$BaseUrl = 'http://127.0.0.1:5001',
    [string]$AdminEmail = 'administrator',
    [securestring]$AdminPassword,
    [string]$TargetUserEmail = 'wind2500@gmail.com',
    [securestring]$TargetUserPassword,
    [switch]$ResetTargetUserPassword = $false,
    [switch]$SkipGenerateRecommendations = $false,
    [switch]$SkipRecommendationsCheck = $false
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

function Read-DotEnv([string]$path) {
    if (-not (Test-Path $path)) { return @{} }
    $map = @{}
    Get-Content -LiteralPath $path | ForEach-Object {
        $line = ($_ -as [string]).Trim()
        if (-not $line) { return }
        if ($line.StartsWith('#')) { return }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { return }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim()
        if ($k) { $map[$k] = $v }
    }
    return $map
}

function Ok([string]$msg) { Write-Output ("OK  " + $msg) }
function Warn([string]$msg) { Write-Output ("WARN " + $msg) }
function Fail([string]$msg) { Write-Output ("FAIL " + $msg); $script:HadFail = $true }

$HadFail = $false

# 0) Local config checks
$repoRoot = (Split-Path $PSScriptRoot -Parent)
$envPath = Join-Path $repoRoot 'backend\.env'
$env = Read-DotEnv $envPath

$strictPrice = $env['KIS_STRICT_PRICE']
$strictBalance = $env['KIS_STRICT_BALANCE']
$killSwitch = $env['AUTOTRADING_KILL_SWITCH']
$liveOrders = $env['AUTOTRADING_LIVE_ORDERS']

if ($strictPrice -eq '1') { Ok "KIS_STRICT_PRICE=1" } else { Fail "KIS_STRICT_PRICE is not 1 (actual='$strictPrice')" }
if ($strictBalance -eq '1') { Ok "KIS_STRICT_BALANCE=1" } else { Fail "KIS_STRICT_BALANCE is not 1 (actual='$strictBalance')" }

# Safety: keep trading blocked unless the operator explicitly enables it.
if ($killSwitch -eq '1') { Ok "AUTOTRADING_KILL_SWITCH=1 (engine ticks blocked)" } else { Warn "AUTOTRADING_KILL_SWITCH is not 1 (actual='$killSwitch')" }
if ($liveOrders -eq '0') { Ok "AUTOTRADING_LIVE_ORDERS=0 (live orders blocked)" } else { Warn "AUTOTRADING_LIVE_ORDERS is not 0 (actual='$liveOrders')" }

# 1) Health
try {
    $h = Invoke-Json -method 'Get' -path '/health' -timeoutSec 5
    if ($h.ok -eq $true) { Ok "/health" } else { Fail "/health returned ok!=true" }
}
catch {
    Fail ("/health failed: " + $_.Exception.Message)
}

# 2) Admin login
if ($null -eq $AdminPassword) {
    # Local dev convenience only.
    $AdminPassword = ConvertTo-SecureString -String 'ChangeMe!' -AsPlainText -Force
    Warn "AdminPassword not provided; using default 'ChangeMe!'"
}

$adminToken = $null
try {
    $admin = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{ email = $AdminEmail; password = (ConvertFrom-SecureStringToPlain $AdminPassword) } -timeoutSec 15
    $adminToken = $admin.accessToken
    if (-not $adminToken) { throw 'accessToken missing' }
    Ok "Admin login" 
}
catch {
    Fail ("Admin login failed: " + $_.Exception.Message)
}

if (-not $adminToken) {
    if ($HadFail) { exit 1 }
    exit 2
}

$adminAuth = @{ Authorization = ('Bearer ' + $adminToken) }

# 2.5) (Optional) Generate today's recommendations as admin (idempotent upsert)
if (-not $SkipGenerateRecommendations) {
    try {
        $gen = Invoke-Json -method 'Post' -path '/api/admin/recommendations/generate-today' -headers $adminAuth -body @{} -timeoutSec 60
        if ($gen.ok -eq $true) {
            Ok ("Generated today's recommendations (date=" + $gen.date + ", upserted=" + $gen.upserted + ")")
        }
        else {
            Fail ("Generate-today returned ok!=true: " + ($gen | ConvertTo-Json -Compress))
        }
    }
    catch {
        Fail ("Generate-today failed: " + $_.Exception.Message)
    }
}
else {
    Warn "Skipping admin generate-today recommendations (-SkipGenerateRecommendations)."
}

# 3) Locate target user
$userId = $null
try {
    $users = Invoke-Json -method 'Get' -path '/api/admin/users' -headers $adminAuth -timeoutSec 20
    $target = $users.items | Where-Object { $_.email -eq $TargetUserEmail } | Select-Object -First 1
    if (-not $target) { throw "Target user not found: $TargetUserEmail" }
    $userId = [int]$target.id
    Ok "Target user found (userId=$userId)"
}
catch {
    Fail ("Target user lookup failed: " + $_.Exception.Message)
}

# 4) User login (prefer provided password; otherwise optionally reset)
$userToken = $null
if ($userId -and $TargetUserPassword) {
    try {
        $u = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{ email = $TargetUserEmail; password = (ConvertFrom-SecureStringToPlain $TargetUserPassword) } -timeoutSec 15
        $userToken = $u.accessToken
        if (-not $userToken) { throw 'accessToken missing' }
        Ok "User login (password provided)"
    }
    catch {
        Fail ("User login failed: " + $_.Exception.Message)
    }
}
elseif ($userId -and $ResetTargetUserPassword) {
    Warn "ResetTargetUserPassword is ON: admin will reset target password (side effect)."
    try {
        $reset = Invoke-Json -method 'Post' -path ("/api/admin/users/{0}/reset-password" -f $userId) -headers $adminAuth -body @{} -timeoutSec 20
        $tmp = $reset.tempPassword
        if (-not $tmp) { throw 'tempPassword missing' }

        $u = Invoke-Json -method 'Post' -path '/api/auth/login' -body @{ email = $TargetUserEmail; password = $tmp } -timeoutSec 15
        $userToken = $u.accessToken
        if (-not $userToken) { throw 'accessToken missing' }
        Ok "User login (via admin reset)"
    }
    catch {
        Fail ("User login via reset failed: " + $_.Exception.Message)
    }
}
else {
    Warn "Skipping user-authenticated checks (provide -TargetUserPassword or set -ResetTargetUserPassword)."
}

if ($userToken) {
    $userAuth = @{ Authorization = ('Bearer ' + $userToken) }

    # 5) KIS token status
    try {
        $ts = Invoke-Json -method 'Get' -path '/api/kis/token-status' -headers $userAuth -timeoutSec 20
        if ($ts.ok -eq $true -and $ts.hasProfile -eq $true) {
            Ok ("KIS token-status ok (tradeType=" + $ts.tradeType + ")")
        }
        else {
            Fail ("KIS token-status not ok/hasProfile=false: " + ($ts | ConvertTo-Json -Compress))
        }
    }
    catch {
        Fail ("/api/kis/token-status failed: " + $_.Exception.Message)
    }

    # 6) Dashboard (strict mode should not return sample)
    try {
        $dash = Invoke-Json -method 'Get' -path '/api/dashboard' -headers $userAuth -timeoutSec 60
        $tv = [int]($dash.kpis.totalValue.amount)
        if ($tv -eq 184380000) {
            Fail "Dashboard appears to return sample KPI (totalValue=184,380,000)"
        }
        else {
            Ok ("Dashboard KPIs ok (totalValue=" + $tv + ")")
        }

        $recsCount = 0
        if ($dash.topRecommendations) { $recsCount = ($dash.topRecommendations | Measure-Object).Count }
        if ($recsCount -gt 0) { Ok ("Dashboard topRecommendations count=" + $recsCount) } else { Warn "Dashboard topRecommendations is empty (DB recommendations may not be generated yet)" }
    }
    catch {
        Fail ("/api/dashboard failed: " + $_.Exception.Message)
    }

    # 7) Portfolio (strict mode should not silently degrade)
    try {
        $pf = Invoke-Json -method 'Get' -path '/api/portfolio' -headers $userAuth -timeoutSec 120
        $posCount = 0
        if ($pf.positions) { $posCount = ($pf.positions | Measure-Object).Count }
        Ok ("Portfolio positions_count=" + $posCount)

        if ($posCount -gt 0) {
            $sample = $pf.positions | Select-Object -First 5
            $codeNames = @($sample | Where-Object { $_.name -eq $_.code })
            if ($codeNames.Count -gt 0) { Warn "Some position names still equal codes (stock master may be placeholder for those)" } else { Ok "Position names look hydrated" }
        }
    }
    catch {
        Fail ("/api/portfolio failed: " + $_.Exception.Message)
    }

    # 8) Recommendations (strict price mode may fail loudly if KIS quote/token is not OK)
    if (-not $SkipRecommendationsCheck) {
        try {
            $recs = Invoke-Json -method 'Get' -path '/api/recommendations' -headers $userAuth -timeoutSec 60
            $count = 0
            if ($recs.items) { $count = ($recs.items | Measure-Object).Count }
            if ($count -gt 0) {
                $top = $recs.items | Select-Object -First 1
                $topCode = $top.code
                $topName = $top.name
                $topScore = $top.score
                $topPrice = $top.price
                $topChg = $top.changeRate
                Ok ("Recommendations ok (items_count=" + $count + "; top=" + $topCode + " " + $topName + ", score=" + $topScore + ", price=" + $topPrice + ", changeRate=" + $topChg + ")")
            }
            else {
                Warn "Recommendations returned empty items (may be not generated yet)."
            }
        }
        catch {
            Fail ("/api/recommendations failed: " + $_.Exception.Message)
        }
    }
    else {
        Warn "Skipping recommendations check (-SkipRecommendationsCheck)."
    }
}

if ($HadFail) {
    Write-Output 'RESULT=FAIL'
    exit 1
}

Write-Output 'RESULT=OK'
exit 0
