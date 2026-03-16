[CmdletBinding()]
param(
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

$markerBegin = '# BEGIN STOCK_AI_CACHE_ENV'
$markerEnd = '# END STOCK_AI_CACHE_ENV'

$block = @(
  $markerBegin,
  'try {',
  '  $names = @(''HF_HOME'',''HUGGINGFACE_HUB_CACHE'',''TRANSFORMERS_CACHE'',''TORCH_HOME'',''PIP_CACHE_DIR'',''TEMP'',''TMP'')',
  '  foreach ($n in $names) {',
  '    $v = [Environment]::GetEnvironmentVariable($n, ''User'')',
  '    if ($v) { Set-Item -Path (''Env:'' + $n) -Value $v }',
  '  }',
  '} catch { }',
  $markerEnd,
  ''
) -join "`r`n"

$profilePath = $PROFILE.CurrentUserAllHosts
$profileDir = Split-Path $profilePath -Parent

if (-not (Test-Path $profileDir)) {
  New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
}

if (-not (Test-Path $profilePath)) {
  New-Item -ItemType File -Force -Path $profilePath | Out-Null
}

$content = Get-Content -Path $profilePath -Raw -ErrorAction Stop
$hasBlock = ($content -match [Regex]::Escape($markerBegin)) -and ($content -match [Regex]::Escape($markerEnd))

if ($hasBlock -and -not $Force) {
  Write-Host "Already configured: $profilePath"
  Write-Host 'Use -Force to replace the existing block.'
  exit 0
}

if ($hasBlock) {
  $pattern = [regex]::Escape($markerBegin) + '([\s\S]*?)' + [regex]::Escape($markerEnd)
  $content = [regex]::Replace($content, $pattern, [System.Text.RegularExpressions.MatchEvaluator] { param($m) $block })
}
else {
  if ($content -and -not $content.EndsWith("`r`n")) { $content += "`r`n" }
  $content += $block
}

Set-Content -Path $profilePath -Value $content -Encoding utf8

Write-Host "Updated profile: $profilePath"
Write-Host 'New PowerShell sessions will inherit User-scoped D:\AI cache env vars automatically.'
Write-Host 'Note: sessions started with -NoProfile will not run the profile.'
