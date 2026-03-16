[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Repo,
  [switch]$Public,
  [string]$Remote = 'origin'
)

$ErrorActionPreference = 'Stop'

Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw 'GitHub CLI (gh) not found. Install it first: winget install -e --id GitHub.cli'
}

# Ensure gh logged in
$null = & gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host 'Not logged in to GitHub.'
  Write-Host 'Run: gh auth login -h github.com -p https -w'
  throw 'Please login with gh first, then rerun this script.'
}

# If remote already exists, just show it
$existing = & git remote get-url $Remote 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) {
  Write-Host "Remote '$Remote' already set: $existing"
  Write-Host 'If you want to change it, remove and re-add the remote manually.'
  exit 0
}

$visibility = $Public ? '--public' : '--private'

# Create repo on GitHub and push current directory
& gh repo create $Repo $visibility --source . --remote $Remote --push
if ($LASTEXITCODE -ne 0) {
  throw 'gh repo create failed.'
}

Write-Host "Created and pushed to GitHub repo: $Repo (remote '$Remote')"
