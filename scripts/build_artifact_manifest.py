"""정적 산출물 경량 메타 표준화 — moonstock-read-layer-efficiency 표준 적용.

표준(역설계 문서 8절): 파이프라인 산출물마다 생성시각·행수·빌드해시 표준화
→ CDN 신선도/무결성 1차 게이트. 데이터 파일은 불변(사이드카 _manifest.json만 생성).

각 출력 그룹 루트에 _manifest.json:
  { schema_version, generated_at, generator, rootBuildHash, artifactCount, files:[
      { path, updated_at(파일 mtime ISO), rows, bytes, version(sha256[:12]) } ] }
rows: csv=데이터행(헤더 제외), json=list 길이 또는 dict 키수, md/txt=null.
교차검증 비협상과 무관(메타는 신선도 게이트일 뿐, 네이버 검증·라이브 예측 미접촉).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOTS = [Path(r"D:\STOCK DATA-US\dotcom_1995_2002"),
         Path(r"D:\STOCK DATA-US\backtests")]
EXTS = {".csv", ".json", ".md", ".txt"}
SCHEMA_VERSION = "meta-1.0"


def count_rows(p: Path) -> int | None:
    ext = p.suffix.lower()
    try:
        if ext == ".csv":
            with open(p, encoding="utf-8", errors="replace") as f:
                n = sum(1 for _ in f)
            return max(n - 1, 0)  # 헤더 제외
        if ext == ".json":
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(obj, list):
                return len(obj)
            if isinstance(obj, dict):
                return len(obj)
    except Exception:
        return None
    return None


def file_meta(p: Path, root: Path) -> dict:
    data = p.read_bytes()
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    return {
        "path": str(p.relative_to(root)).replace("\\", "/"),
        "updated_at": mtime.isoformat(timespec="seconds"),
        "rows": count_rows(p),
        "bytes": len(data),
        "version": hashlib.sha256(data).hexdigest()[:12],
    }


def build(root: Path) -> dict:
    files = []
    for dirpath, _dirs, names in os.walk(root):
        for nm in names:
            if nm == "_manifest.json":
                continue
            p = Path(dirpath) / nm
            if p.suffix.lower() in EXTS:
                files.append(file_meta(p, root))
    files.sort(key=lambda f: f["path"])
    # 루트 빌드해시: 전 파일 version 연결의 해시 (1줄 신선도 폴링용)
    root_hash = hashlib.sha256(
        "".join(f["version"] for f in files).encode()).hexdigest()[:12]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "scripts/build_artifact_manifest.py",
        "rootBuildHash": root_hash,
        "artifactCount": len(files),
        "files": files,
    }


def main() -> None:
    for root in ROOTS:
        if not root.exists():
            print(f"[skip] 없음: {root}")
            continue
        manifest = build(root)
        (root / "_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        total_rows = sum(f["rows"] or 0 for f in manifest["files"])
        print(f"{root.name}: 산출물 {manifest['artifactCount']}개 / "
              f"총 {total_rows:,}행 / buildHash {manifest['rootBuildHash']} "
              f"→ _manifest.json")


if __name__ == "__main__":
    main()
