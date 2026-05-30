#!/usr/bin/env pwsh
# AI 대화 기록 → Obsidian 변환 런처
# 사용: 더블클릭 or 터미널에서 실행

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExportDir = "$env:USERPROFILE\Downloads\ai-exports"
$VaultDir  = "D:\.obsidian\ai\conversations"

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  AI 대화 기록 → Obsidian 변환" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

# 내보내기 폴더 열기
Write-Host "`n📁 내보내기 폴더를 탐색기로 엽니다..." -ForegroundColor Yellow
Start-Process explorer.exe $ExportDir

# 파일 확인
$files = Get-ChildItem $ExportDir -Include "*.json","*.zip","*.html" -Recurse -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -notlike "_*" }

if (-not $files) {
    Write-Host "`n⚠  변환할 파일이 없습니다." -ForegroundColor Red
    Write-Host "   아래 경로에 내보낸 파일을 넣고 이 스크립트를 다시 실행하세요:" -ForegroundColor Yellow
    Write-Host "   $ExportDir" -ForegroundColor White
    Write-Host ""
    Write-Host "   각 서비스 내보내기 방법:" -ForegroundColor Cyan
    Write-Host "   ChatGPT  → chat.openai.com/settings > Data Controls > Export"
    Write-Host "   Claude   → claude.ai/settings > Privacy > Export data"
    Write-Host "   Gemini   → takeout.google.com → 'Gemini Apps Activity' 만 선택"
    Write-Host "   Grok     → x.com/settings 또는 grok.x.com (제한적 지원)"
    Write-Host "   Perplexity → 현재 공식 내보내기 없음 (수동 복사)"
    Write-Host ""
    Read-Host "Enter 키를 누르면 닫힙니다"
    exit 0
}

Write-Host "`n발견된 파일 ($($files.Count)개):" -ForegroundColor Green
$files | Format-Table Name, Length, LastWriteTime -AutoSize

# Python 실행
$python = $null
foreach ($p in @("python", "py", "python3",
    "C:\stock\backend\.venv\Scripts\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")) {
    if (Get-Command $p -ErrorAction SilentlyContinue) { $python = $p; break }
    if (Test-Path $p) { $python = $p; break }
}

if (-not $python) {
    Write-Host "`n❌ Python을 찾을 수 없습니다. Python을 설치하거나 가상환경을 활성화하세요." -ForegroundColor Red
    Read-Host "Enter 키를 누르면 닫힙니다"
    exit 1
}

Write-Host "`n🐍 Python 실행 중: $python" -ForegroundColor Green
& $python "$ScriptDir\ai_to_obsidian.py"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ 완료! Obsidian을 새로고침(Ctrl+R)하면 적용됩니다." -ForegroundColor Green
    Write-Host "   열기: ai/conversations/_index" -ForegroundColor Cyan
    Start-Process explorer.exe $VaultDir
} else {
    Write-Host "`n❌ 오류가 발생했습니다. 위 메시지를 확인하세요." -ForegroundColor Red
}

Read-Host "`nEnter 키를 누르면 닫힙니다"
