[CmdletBinding()]
param(
  # Show matches only (default). Use -Apply to actually delete files.
  [switch]$Apply,

  # Regex for shortcut display name or target path.
  [string]$Pattern = '(?i)powershell|pwsh|windows powershell|powershell 7|ise',

  # If set, matching shortcuts are kept (not deleted) even when -Apply is used.
  # Default keeps the PowerShell 7 shortcut.
  [string]$KeepPattern = '(?i)^PowerShell 7'
)

$ErrorActionPreference = 'Stop'

function Combine-PathSafe {
  param(
    [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Base,
    [Parameter(Mandatory = $true)][string]$Child
  )
  if ([string]::IsNullOrWhiteSpace($Base)) { return $null }
  return (Join-Path -Path $Base -ChildPath $Child)
}

function Get-ShortcutTarget {
  param([Parameter(Mandatory)][string]$Path)

  try {
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($Path)
    return [pscustomobject]@{
      TargetPath       = $sc.TargetPath
      Arguments        = $sc.Arguments
      WorkingDirectory = $sc.WorkingDirectory
      IconLocation     = $sc.IconLocation
    }
  } catch {
    return [pscustomobject]@{
      TargetPath       = $null
      Arguments        = $null
      WorkingDirectory = $null
      IconLocation     = $null
    }
  }
}

$locations = @(
  Combine-PathSafe -Base $env:APPDATA -Child 'Microsoft\Windows\Start Menu\Programs'
  Combine-PathSafe -Base $env:ProgramData -Child 'Microsoft\Windows\Start Menu\Programs'
  Combine-PathSafe -Base $env:USERPROFILE -Child 'Desktop'
  Combine-PathSafe -Base $env:PUBLIC -Child 'Desktop'
) | Where-Object { $_ -and (Test-Path $_) }

$shortcutLinks = foreach ($root in $locations) {
  Get-ChildItem -Path $root -Recurse -Filter *.lnk -ErrorAction SilentlyContinue
}

$shortcutMatches = foreach ($lnk in $shortcutLinks) {
  $meta = Get-ShortcutTarget -Path $lnk.FullName

  $haystack = @(
    $lnk.Name,
    $lnk.FullName,
    $meta.TargetPath,
    $meta.Arguments
  ) -join "\n"

  if ($haystack -match $Pattern) {
    [pscustomobject]@{
      Name       = $lnk.Name
      Location   = $lnk.DirectoryName
      FullPath   = $lnk.FullName
      TargetPath = $meta.TargetPath
      Arguments  = $meta.Arguments
    }
  }
}

if (-not $shortcutMatches -or $shortcutMatches.Count -eq 0) {
  Write-Output "No PowerShell shortcuts matched pattern: $Pattern"
  return
}

$kept = @()
$toDelete = @()
foreach ($m in $shortcutMatches) {
  if ($KeepPattern -and ($m.Name -match $KeepPattern)) {
    $kept += $m
  } else {
    $toDelete += $m
  }
}

Write-Output "Matched shortcuts (Pattern=$Pattern):"
$shortcutMatches | Sort-Object Location, Name | Format-Table -Auto

if ($KeepPattern) {
  Write-Output ""
  Write-Output "Kept (KeepPattern=$KeepPattern):"
  if ($kept.Count -eq 0) {
    Write-Output "  (none)"
  } else {
    $kept | Sort-Object Location, Name | Format-Table -Auto
  }

  Write-Output ""
  Write-Output "Will delete:" 
  if ($toDelete.Count -eq 0) {
    Write-Output "  (none)"
  } else {
    $toDelete | Sort-Object Location, Name | Format-Table -Auto
  }
}

if (-not $Apply) {
  Write-Output ""
  Write-Output "Dry-run only. To delete these shortcuts, re-run with:"
  Write-Output "  pwsh -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\cleanup-powershell-shortcuts.ps1 -Apply"
  return
}

Write-Output ""
Write-Output "Deleting matched shortcuts..."
foreach ($m in $toDelete) {
  try {
    Remove-Item -LiteralPath $m.FullPath -Force
    Write-Output "[DELETED] $($m.FullPath)"
  } catch {
    Write-Output "[FAILED]  $($m.FullPath) :: $($_.Exception.Message)"
  }
}
