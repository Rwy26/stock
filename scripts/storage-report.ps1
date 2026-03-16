[CmdletBinding()]
param(
  [string]$WorkspaceRoot = "$PSScriptRoot\.."
)

$ErrorActionPreference = 'Continue'

$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = (Resolve-Path $WorkspaceRoot).Path
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$out = Join-Path $logDir "storage-report-$ts.txt"

function WriteSection([string]$title) {
  "" | Out-File -Append -Encoding utf8 $out
  ("==== {0} ====" -f $title) | Out-File -Append -Encoding utf8 $out
}

function DirSize([string]$path) {
  if (-not (Test-Path $path)) { return $null }
  try {
    $bytes = (Get-ChildItem -LiteralPath $path -Force -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if (-not $bytes) { $bytes = 0 }
    return [int64]$bytes
  } catch {
    return $null
  }
}

function FormatBytes([int64]$bytes) {
  if ($bytes -ge 1TB) { return "{0:N2} TB" -f ($bytes / 1TB) }
  if ($bytes -ge 1GB) { return "{0:N2} GB" -f ($bytes / 1GB) }
  if ($bytes -ge 1MB) { return "{0:N2} MB" -f ($bytes / 1MB) }
  return "$bytes B"
}

"==== Storage Report ($ts) ====" | Out-File -Encoding utf8 $out
("Workspace: {0}" -f $root) | Out-File -Append -Encoding utf8 $out

WriteSection "Volumes"
try {
  $props = @(
    @{Name='Drive';Expression={ if ($_.DriveLetter) { "$($_.DriveLetter):" } else { '(none)' } }}
    @{Name='FS';Expression={$_.FileSystemType}}
    @{Name='SizeGB';Expression={ [math]::Round(($_.Size/1GB),2) }}
    @{Name='FreeGB';Expression={ [math]::Round(($_.SizeRemaining/1GB),2) }}
    @{Name='Status';Expression={$_.OperationalStatus}}
    @{Name='Health';Expression={$_.HealthStatus}}
  )

  Get-Volume |
    Sort-Object DriveLetter |
    Select-Object -Property $props |
    Format-Table -AutoSize | Out-String | Out-File -Append -Encoding utf8 $out
} catch {
  $_ | Out-String | Out-File -Append -Encoding utf8 $out
}

WriteSection "Workspace Key Folders"
$paths = @(
  (Join-Path $root '.venv-ai'),
  (Join-Path $root 'backend\.venv'),
  (Join-Path $root 'frontend\node_modules'),
  (Join-Path $root 'frontend\dist'),
  (Join-Path $root 'logs')
)

$folderRows = foreach ($p in $paths) {
  $size = DirSize $p
  if ($null -ne $size) {
    [pscustomobject]@{ Path = $p; Size = FormatBytes $size }
  }
}
if ($folderRows) {
  $folderRows | Format-Table -AutoSize | Out-String | Out-File -Append -Encoding utf8 $out
} else {
  "(no folders found)" | Out-File -Append -Encoding utf8 $out
}

WriteSection "Common AI Caches (likely)"
$candidates = @(
  (Join-Path $env:USERPROFILE '.cache'),
  (Join-Path $env:USERPROFILE '.cache\huggingface'),
  (Join-Path $env:USERPROFILE '.cache\torch'),
  (Join-Path $env:LOCALAPPDATA 'pip\Cache'),
  (Join-Path $env:LOCALAPPDATA 'huggingface'),
  (Join-Path $env:USERPROFILE '.keras'),
  (Join-Path $env:USERPROFILE '.nv')
)

$cacheRows = foreach ($p in $candidates) {
  $size = DirSize $p
  if ($null -ne $size) {
    [pscustomobject]@{ Path = $p; Size = FormatBytes $size }
  }
}
if ($cacheRows) {
  $cacheRows | Sort-Object Path | Format-Table -AutoSize | Out-String | Out-File -Append -Encoding utf8 $out
} else {
  "(no caches found)" | Out-File -Append -Encoding utf8 $out
}

WriteSection "Headroom Recommendations (rule-of-thumb)"
@(
  "- Keep >= 20% free on OS SSD for performance and updates.",
  "- For AI: reserve extra 100~300 GB for datasets/models and temporary files.",
  "- Keep a rollback buffer (restore point / driver rollback): 10~30 GB on C:."
) | Out-File -Append -Encoding utf8 $out

"Wrote: $out" | Write-Host
