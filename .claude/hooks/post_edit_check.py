"""
Post-edit hook: Python .py 파일 저장 시 UTF-8 인코딩 + 문법 검사
"""
import os
import ast
import sys
import pathlib

file_path = os.environ.get("CLAUDE_FILE_PATHS", "")
if not file_path or not file_path.endswith(".py"):
    sys.exit(0)

p = pathlib.Path(file_path)
if not p.exists():
    sys.exit(0)

try:
    source = p.read_text(encoding="utf-8")
except UnicodeDecodeError as e:
    print(f"[HOOK] UTF-8 인코딩 오류: {file_path}\n  → {e}")
    print(f"[HOOK] 파일에 encoding='utf-8' 누락 가능성. 확인 필요.")
    sys.exit(1)

try:
    ast.parse(source)
except SyntaxError as e:
    print(f"[HOOK] Python 문법 오류: {file_path}\n  → {e}")
    sys.exit(1)

sys.exit(0)
