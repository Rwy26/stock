[CmdletBinding()]
param(
  [string[]]$Extensions = @(
    'ms-python.python',
    'ms-python.vscode-pylance',
    'ms-toolsai.jupyter',
    'charliermarsh.ruff',
    'ms-python.black-formatter',
    'ms-python.isort',
    'eamodio.gitlens'
  )
)

$ErrorActionPreference = 'Continue'

function HasCodeCli {
  $cmd = Get-Command code -ErrorAction SilentlyContinue
  return [bool]$cmd
}

if (-not (HasCodeCli)) {
  Write-Host "VS Code의 'code' CLI가 PATH에 없습니다."
  Write-Host "해결: VS Code에서 Command Palette(Ctrl+Shift+P) -> 'Shell Command: Install 'code' command in PATH' 실행 후, 새 터미널에서 다시 실행하세요."
  exit 1
}

foreach ($ext in $Extensions) {
  Write-Host "Installing: $ext"
  code --install-extension $ext --force | Out-Null
}

Write-Host 'Done.'
