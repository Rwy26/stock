[CmdletBinding()]
param(
  [string]$EnvPath = "$PSScriptRoot\..\.venv-ai"
)

$ErrorActionPreference = 'Stop'

$python = Join-Path (Resolve-Path $EnvPath).Path 'Scripts\python.exe'
if (-not (Test-Path $python)) { throw "Python venv not found: $EnvPath (먼저 ai-python-setup.ps1 실행)" }

$code = @"
import sys
print('Python:', sys.version)
try:
    import torch
    print('Torch:', torch.__version__)
    print('CUDA available:', torch.cuda.is_available())
    if torch.cuda.is_available():
        print('CUDA version (torch):', torch.version.cuda)
        print('GPU count:', torch.cuda.device_count())
        for i in range(torch.cuda.device_count()):
            print('GPU', i, torch.cuda.get_device_name(i))
        x = torch.randn((2048, 2048), device='cuda')
        y = torch.randn((2048, 2048), device='cuda')
        z = x @ y
        print('Matmul ok:', float(z[0,0].item()))
    else:
        print('Hint: reinstall torch CUDA build (cu124) if you expect GPU.')
except Exception as e:
    print('ERROR:', e)
    raise
"@

$tmp = Join-Path $env:TEMP ("ai-gpu-test-{0}.py" -f ([Guid]::NewGuid().ToString('N')))
Set-Content -Path $tmp -Value $code -Encoding utf8
try {
  & $python $tmp
}
finally {
  Remove-Item -Force -ErrorAction SilentlyContinue $tmp
}
