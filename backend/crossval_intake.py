# -*- coding: utf-8 -*-
"""
교차검증 적재 창구 — "AI 종목 분석" 화면을 외부 데이터 창구로 만든다.

설계 원칙 (관리자 지시):
  1) 같은 종목 CSV는 종목별 폴더로 모은다.
  2) 업로드 시 과거 자료 유무를 확인해 알리고, 병합 작업을 시작한다.
  3) 과거+신규 데이터를 병합·중복제거해 정규 시계열(OHLCV)로 업데이트한다.
  4) 병합본에서 인덱스(커버리지)와 노드(결정론 메트릭)를 추출한다.
  5) 인덱스·노드는 DB(crossval_corpus)에 저장 → 모든 세션 공동 사용 (main.py가 UPSERT).
  6) watchlist와 비교해 데이터 부족 종목을 작업 요구로 표출 (main.py).

경계: 원본 CSV·병합 parquet 은 외부 유출 없는 로컬(D:\\개인연구용 데이터\\교차검증)에만 둔다.
DB에는 요약 인덱스/노드만 저장하며 거래 판단에 반영하지 않는다(reference-only).
모든 적재/병합은 best-effort — 실패해도 AI 분석 응답엔 영향 없다(호출부 try/except).
"""
from __future__ import annotations

import csv
import io
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

# ── 경로 ────────────────────────────────────────────────────────────────
BASE = Path(r"D:\개인연구용 데이터\교차검증")
RAW_TV = BASE / "00_raw_tv"                 # 00_raw_tv\{종목}\*.csv (원본, 전 컬럼 보존)
MERGED = BASE / "01_normalized" / "merged"  # 01_normalized\merged\{종목}\{tf}.parquet (OHLCV만)
IMAGES = BASE / "reference" / "images"
VALIDATED = BASE / "02_validated"
QUARANTINE = BASE / "99_quarantine"

_OHLCV = {"open", "high", "low", "close", "volume"}
_TIME_COLS = {"time", "date", "datetime", "timestamp"}
_FIELD_VERDICT = {
    "close":  ("ok",      "네이버 종가와 직접 대조 — 교차검증 주축"),
    "open":   ("ok",      "네이버 siseJson 시가와 대조 가능"),
    "high":   ("ok",      "네이버 고가와 대조 가능"),
    "low":    ("ok",      "네이버 저가와 대조 가능"),
    "volume": ("caution", "집계 방식·수정주가 차이로 절대값 불일치 가능 → 추세만 참고"),
    "time":   ("ok",      "KST 날짜키 변환 후 정렬 기준"),
}


def available() -> bool:
    try:
        return BASE.parent.parent.exists()  # D:\ 존재
    except Exception:
        return False


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def safe_symbol(symbol: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣_.-]", "", (symbol or "").strip())
    return s or "UNKNOWN"


def symbol_dir(symbol: str) -> Path:
    return RAW_TV / safe_symbol(symbol)


def _sidecar(target: Path, meta: dict) -> None:
    target.with_suffix(target.suffix + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 시간 파싱/표시 헬퍼 ──────────────────────────────────────────────────
def _parse_ts(s):
    """unix초/ISO/날짜 문자열 → tz-aware datetime(KST) or None."""
    s = str(s).strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 9:                 # unix seconds
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc).astimezone()
        except Exception:
            return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt)
        except Exception:
            continue
    return None


def _fmt_time(v):
    """원시 시간값을 사람이 읽는 'YYYY-MM-DD HH:MM' 으로 (실패 시 원값)."""
    dt = _parse_ts(v)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else v


def _infer_timeframe(vals: list[str]) -> str | None:
    if len(vals) < 2:
        return None
    a, b = _parse_ts(vals[0]), _parse_ts(vals[1])
    if not a or not b:
        return None
    sec = abs((b - a).total_seconds())
    if sec >= 80000:
        return "1D" if sec < 600000 else "1W"
    if sec >= 3600:
        return f"{int(sec // 3600)}H"
    if sec >= 60:
        return f"{int(sec // 60)}m"
    return None


# ──────────────────────────────────────────────────────────────────────
# (3 데이터 성격) — 어떤 필드를 교차검증에 쓸 수 있는가
# ──────────────────────────────────────────────────────────────────────
def analyze_csv_nature(raw: bytes | str, filename: str = "") -> dict:
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {"ok": False, "reason": "빈 CSV"}
    cols = [c.strip().lower() for c in header]
    rows = list(reader)
    n = len(rows)

    has_time = any(c in _TIME_COLS for c in cols)
    price_cols = [c for c in cols if c in _OHLCV and c != "volume"]
    has_volume = "volume" in cols or "vol" in cols
    derived = [c for c in cols if c not in _OHLCV and c not in _TIME_COLS and c not in ("vol",)]

    date_min = date_max = None
    timeframe = None
    if has_time and rows:
        ti = next((i for i, c in enumerate(cols) if c in _TIME_COLS), 0)
        vals = [r[ti] for r in rows if len(r) > ti and r[ti].strip()]
        if vals:
            date_min, date_max = _fmt_time(vals[0]), _fmt_time(vals[-1])
            timeframe = _infer_timeframe(vals)

    usable = []
    for c in cols:
        v = _FIELD_VERDICT.get(c)
        if v:
            usable.append({"field": c, "verdict": v[0], "note": v[1]})
    for c in derived:
        usable.append({"field": c, "verdict": "no",
                       "note": "파생 지표(가격에서 결정론적 계산) — 교차검증 대상 아님, 자체 재계산으로 검증"})

    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(cols))
    return {
        "ok": True, "kind": "csv", "filename": filename,
        "rows": n, "columns": cols,
        "layers": {"price": price_cols + (["volume"] if has_volume else []),
                   "meta": [c for c in cols if c in _TIME_COLS], "derived": derived},
        "date_range": [date_min, date_max],
        "timeframe_inferred": timeframe,
        "adjusted_price": "UNKNOWN — TradingView 차트의 수정주가 설정을 export 시 확인 필요",
        "crossval_usable_fields": usable,
        "crossval_ready": has_time and not missing and n >= 30,
        "blockers": (([f"필수 컬럼 누락: {missing}"] if missing else [])
                     + ([] if has_time else ["시간 컬럼 없음"])
                     + ([] if n >= 30 else [f"행 수 부족({n}<30)"])),
    }


# ──────────────────────────────────────────────────────────────────────
# (2 과거자료 확인)
# ──────────────────────────────────────────────────────────────────────
def existing_data(symbol: str) -> dict:
    """업로드 전 해당 종목 과거 자료 유무. 프론트가 '과거 N건 발견, 병합 시작' 알림에 사용."""
    if not available():
        return {"found": False, "reason": "드라이브 미마운트"}
    sdir = symbol_dir(symbol)
    if not sdir.exists():
        return {"found": False, "file_count": 0}
    csvs = sorted(sdir.glob("*.csv"))
    if not csvs:
        return {"found": False, "file_count": 0}
    last = max(csvs, key=lambda p: p.stat().st_mtime)
    return {
        "found": True,
        "file_count": len(csvs),
        "last_uploaded": datetime.fromtimestamp(last.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        "files": [p.name for p in csvs[-5:]],
    }


# ──────────────────────────────────────────────────────────────────────
# (1 종목별 적재) — 원본 변형 없이 종목 폴더에 보존
# ──────────────────────────────────────────────────────────────────────
def _detect_tf(filename: str, raw: bytes) -> str:
    """파일명/데이터에서 타임프레임 추정 (병합 그룹 키)."""
    nat = analyze_csv_nature(raw, filename)
    return (nat.get("timeframe_inferred") or "NA") if nat.get("ok") else "NA"


def save_csv(symbol: str, filename: str, raw: bytes, *, extra_context: str | None = None) -> dict:
    if not available():
        return {"stored": False, "reason": "교차검증 드라이브(D:) 미마운트"}
    sym = safe_symbol(symbol)
    sdir = symbol_dir(sym)
    sdir.mkdir(parents=True, exist_ok=True)
    tf = _detect_tf(filename, raw)
    sha = hashlib.sha256(raw).hexdigest()
    target = sdir / f"{sym}_{tf}_{_now_stamp()}_tvexport.csv"
    target.write_bytes(raw)
    _sidecar(target, {
        "source": "AI 종목 분석 창구", "reference_only": True,
        "do_not_reprocess_original": True,
        "symbol": sym, "timeframe": tf, "original_filename": filename,
        "received_at_kst": datetime.now().isoformat(),
        "sha256": sha, "bytes": len(raw), "extra_context": extra_context or None,
    })
    return {"stored": True, "path": str(target), "sha256": sha[:16],
            "folder": f"00_raw_tv/{sym}", "timeframe": tf}


def save_image(symbol: str, filename: str, raw: bytes, *, extra_context: str | None = None) -> dict:
    if not available():
        return {"stored": False, "reason": "교차검증 드라이브(D:) 미마운트"}
    sym = safe_symbol(symbol)
    idir = IMAGES / sym
    idir.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(raw).hexdigest()
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".png"
    target = idir / f"{sym}_{_now_stamp()}_{sha[:8]}{ext}"
    target.write_bytes(raw)
    _sidecar(target, {
        "source": "AI 종목 분석 창구", "reference_only": True,
        "crossval": "불가 — 이미지는 네이버 수치 대조 대상 아님 (참고/패턴 코퍼스용)",
        "symbol": sym, "original_filename": filename,
        "received_at_kst": datetime.now().isoformat(),
        "sha256": sha, "bytes": len(raw), "extra_context": extra_context or None,
    })
    return {"stored": True, "path": str(target), "sha256": sha[:16],
            "folder": f"reference/images/{sym}", "crossval": "reference-only"}


# ──────────────────────────────────────────────────────────────────────
# (3 병합·업데이트) + (4 인덱스·노드 추출)
# ──────────────────────────────────────────────────────────────────────
def _read_ohlcv(path: Path):
    """CSV에서 OHLCV만 파싱 → DataFrame[ts, open, high, low, close, volume]."""
    import pandas as pd
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"date": "time"})
    if "time" not in df.columns or not _OHLCV.issubset(set(df.columns) | {"volume"}):
        need = {"time", "open", "high", "low", "close"} - set(df.columns)
        if need:
            raise ValueError(f"필수 컬럼 누락: {sorted(need)}")
    # 시간 파싱 (unix초 또는 문자열)
    t = df["time"]
    if pd.api.types.is_numeric_dtype(t):
        ts = pd.to_datetime(t, unit="s", utc=True).dt.tz_convert("Asia/Seoul")
    else:
        ts = pd.to_datetime(t, errors="coerce", utc=True).dt.tz_convert("Asia/Seoul")
    out = pd.DataFrame({"ts": ts})
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(df[c], errors="coerce")
    out["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0) if "volume" in df.columns else 0.0
    out = out.dropna(subset=["ts", "open", "high", "low", "close"]).sort_values("ts")
    return out


def merge_symbol(symbol: str) -> dict:
    """종목 폴더의 모든 CSV를 tf별로 병합·중복제거(최신 업로드 우선)→ parquet 갱신.
    인덱스(timeframes)와 노드(결정론 메트릭)를 함께 반환. DB 저장은 호출부(main.py)."""
    import pandas as pd
    if not available():
        return {"ok": False, "reason": "드라이브 미마운트"}
    sym = safe_symbol(symbol)
    sdir = symbol_dir(sym)
    csvs = sorted(sdir.glob("*.csv")) if sdir.exists() else []
    if not csvs:
        return {"ok": False, "reason": "CSV 없음"}

    # tf별 그룹 (파일명 {sym}_{tf}_... 에서 tf 추출, 없으면 데이터로 추정)
    groups: dict[str, list[Path]] = {}
    for p in csvs:
        m = re.match(rf"{re.escape(sym)}_([^_]+)_", p.name)
        tf = m.group(1) if m else (_detect_tf(p.name, p.read_bytes()) or "NA")
        groups.setdefault(tf, []).append(p)

    timeframes: dict[str, dict] = {}
    tf_added: dict[str, int] = {}
    total_rows = 0
    last_close = None
    last_data_at = None
    first_data_at = None

    for tf, paths in groups.items():
        frames = []
        for p in sorted(paths, key=lambda x: x.stat().st_mtime):  # 오래된→최신
            try:
                d = _read_ohlcv(p)
                d["_src"] = p.stat().st_mtime
                frames.append(d)
            except Exception:
                continue
        if not frames:
            continue
        cat = pd.concat(frames, ignore_index=True).sort_values(["ts", "_src"])
        merged = cat.drop_duplicates(subset="ts", keep="last").drop(columns="_src").sort_values("ts").reset_index(drop=True)

        out_dir = MERGED / sym
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{tf}.parquet"
        prev_rows = 0
        if out_path.exists():
            try:
                prev_rows = len(pd.read_parquet(out_path, columns=["ts"]))
            except Exception:
                prev_rows = 0
        merged.to_parquet(out_path, index=False)

        rows = len(merged)
        tf_added[tf] = max(0, rows - prev_rows)
        fmin, fmax = merged["ts"].iloc[0], merged["ts"].iloc[-1]
        timeframes[tf] = {
            "rows": rows,
            "first": fmin.strftime("%Y-%m-%d %H:%M"),
            "last": fmax.strftime("%Y-%m-%d %H:%M"),
            "files": len(paths),
            "added_this_run": tf_added[tf],
        }
        total_rows += rows
        if last_data_at is None or fmax > last_data_at:
            last_data_at = fmax
            last_close = float(merged["close"].iloc[-1])
        if first_data_at is None or fmin < first_data_at:
            first_data_at = fmin

    coverage_days = (last_data_at - first_data_at).days if (last_data_at and first_data_at) else 0
    node = {                                   # (4) 결정론 노드
        "code": sym,
        "total_rows": total_rows,
        "timeframes": sorted(timeframes.keys()),
        "tf_count": len(timeframes),
        "last_close": last_close,
        "last_data_at": last_data_at.strftime("%Y-%m-%d %H:%M") if last_data_at else None,
        "first_data_at": first_data_at.strftime("%Y-%m-%d %H:%M") if first_data_at else None,
        "coverage_days": coverage_days,
        "file_count": len(csvs),
    }
    return {
        "ok": True, "symbol": sym,
        "timeframes": timeframes,                      # (4) 인덱스
        "total_rows": total_rows,
        "file_count": len(csvs),
        "last_close": last_close,
        "last_data_at": last_data_at.strftime("%Y-%m-%d %H:%M") if last_data_at else None,
        "added_this_run": sum(tf_added.values()),      # (3) 이번 업로드로 늘어난 봉
        "node": node,
    }


# ──────────────────────────────────────────────────────────────────────
# 발전 가능성 (코퍼스 통계 — DB 기반은 main.py, 여기는 파일 기반 보조)
# ──────────────────────────────────────────────────────────────────────
def corpus_stats() -> dict:
    if not available():
        return {"available": False, "reason": "교차검증 드라이브(D:) 미마운트"}
    csvs = list(RAW_TV.glob("*/*.csv")) if RAW_TV.exists() else []
    imgs = [p for p in IMAGES.glob("*/*") if p.suffix.lower() in
            (".png", ".jpg", ".jpeg", ".webp", ".gif")] if IMAGES.exists() else []
    symbols = {p.parent.name for p in csvs}
    verified_ratio = None
    reports = list(VALIDATED.glob("*_report.json")) if VALIDATED.exists() else []
    if reports:
        rs = []
        for r in reports:
            try:
                rs.append(json.loads(r.read_text(encoding="utf-8")).get("verified_ratio"))
            except Exception:
                pass
        rs = [x for x in rs if isinstance(x, (int, float))]
        if rs:
            verified_ratio = round(sum(rs) / len(rs), 4)
    return {
        "available": True, "csv_count": len(csvs), "image_count": len(imgs),
        "symbol_count": len(symbols), "symbols_sample": sorted(symbols)[:20],
        "validated_reports": len(reports), "avg_verified_ratio": verified_ratio,
        "quarantined_sets": len(list(QUARANTINE.glob("*_mismatch.parquet"))) if QUARANTINE.exists() else 0,
    }


def _DEV_SYSTEM_PROMPT() -> str:
    return (
        "당신은 개인 퀀트 연구자의 데이터 전략 자문역이다. "
        "사용자는 TradingView export 데이터를 외부 유출 없는 로컬 교차검증 폴더에 적재해 "
        "'높은 승률·손익비의 매매법'을 연구하고, 자신의 아이디어가 실제 시장에 어떻게 적용되는지 검증한다. "
        "원칙: 수치는 결정론 계산, LLM(언어모델)은 해석·아이디어 제안만. 적재 자료는 참고용이며 원본 재가공 금지. "
        "주어진 '코퍼스 현황' 통계만을 근거로(없는 데이터를 지어내지 말 것), "
        "이 데이터를 언어학습/머신러닝으로 어떻게 더 발전시킬 수 있는지 관리자에게 제시하라. "
        "반드시 아래 JSON 스키마로만 응답:\n"
        '{"headline": str, "readiness": "이 코퍼스의 현재 학습 준비도 한 줄 평가",'
        ' "ideas": [{"title": str, "what": "무엇을 만들 수 있나", '
        '"data_needed": "필요한 추가 데이터/라벨", "feasibility": "now|soon|later", '
        '"caution": "데이터 정확성·라이선스 관점 주의"}],'
        ' "next_actions": [str]}'
    )


def suggest_development(stats: dict, *, api_key: str, model: str, provider: str,
                        timeout_seconds: float = 60.0) -> dict:
    import httpx
    user = ("## 코퍼스 현황 (이 수치만 근거로 삼을 것)\n```json\n"
            + json.dumps(stats, ensure_ascii=False, indent=2)
            + "\n```\n위 현황을 바탕으로 발전 가능성을 지정 JSON으로만 제시하라.")
    sysp = _DEV_SYSTEM_PROMPT()
    if provider == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={api_key}")
        payload = {"contents": [{"role": "user", "parts": [{"text": user}]}],
                   "systemInstruction": {"parts": [{"text": sysp}]},
                   "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6}}
        resp = httpx.post(url, json=payload, timeout=timeout_seconds)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        base_url = "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
        payload = {"model": model,
                   "messages": [{"role": "system", "content": sysp}, {"role": "user", "content": user}],
                   "temperature": 0.6, "response_format": {"type": "json_object"}}
        resp = httpx.post(f"{base_url}/chat/completions", json=payload,
                          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                          timeout=timeout_seconds)
        if resp.status_code >= 400:
            raise RuntimeError(f"API error {resp.status_code}: {resp.text[:300]}")
        content = resp.json()["choices"][0]["message"]["content"]
    t = content.strip()
    if t.startswith("```"):
        t = "\n".join(t.splitlines()[1:])
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return json.loads(t.strip())
