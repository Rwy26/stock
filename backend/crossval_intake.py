# -*- coding: utf-8 -*-
"""
교차검증 적재 창구 — "AI 종목 분석" 화면을 외부 데이터 창구로 만든다.

설계 원칙 (관리자 지시):
  1) 이 창구로 들어온 데이터는 자동으로 교차검증 폴더로 적재된다.
  2) 여기 자료는 *참고용*. 원본을 변형/재가공하지 않고 증거로 보존한다.
     (AI 해석 결과는 거래 판단/거래 테이블에 반영하지 않는다 — 호출부 책임)
  3) 데이터 성격을 분석해 어떤 필드가 교차검증에 쓸 수 있는지 판정한다.
  4) 적재 코퍼스를 근거로 '언어학습 발전 가능성'을 관리자에게 제시한다.

교차검증 폴더(외부 유출 없는 로컬): D:\개인연구용 데이터\교차검증
  00_raw_tv\          ← TradingView CSV 원본 (이후 ingest.py→validate_naver.py 파이프라인 입력)
  reference\images\   ← 차트 스크린샷 (수치 교차검증 불가 → 참고용 증거 보관)
모든 적재는 best-effort: 실패해도 AI 분석 응답은 영향받지 않는다 (호출부에서 try/except).
"""
from __future__ import annotations

import csv
import io
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 경로 (pipeline\config.py 와 동일 기준) ──────────────────────────────
BASE = Path(r"D:\개인연구용 데이터\교차검증")
RAW_TV = BASE / "00_raw_tv"
IMAGES = BASE / "reference" / "images"
VALIDATED = BASE / "02_validated"
QUARANTINE = BASE / "99_quarantine"

# OHLCV 표준 컬럼
_OHLCV = {"open", "high", "low", "close", "volume"}
_TIME_COLS = {"time", "date", "datetime", "timestamp"}

# 교차검증 가능성 판정표 (필드별)
# verdict: ok=주축/가능, caution=가능하나 주의, no=교차검증 불가(재계산 대상)
_FIELD_VERDICT = {
    "close":  ("ok",      "네이버 종가와 직접 대조 — 교차검증 주축"),
    "open":   ("ok",      "네이버 siseJson 시가와 대조 가능"),
    "high":   ("ok",      "네이버 고가와 대조 가능"),
    "low":    ("ok",      "네이버 저가와 대조 가능"),
    "volume": ("caution", "집계 방식·수정주가 차이로 절대값 불일치 가능 → 추세만 참고"),
    "time":   ("ok",      "KST 날짜키 변환 후 정렬 기준"),
}


def available() -> bool:
    """교차검증 드라이브(D:)가 마운트되어 있는지."""
    try:
        return BASE.parent.parent.exists()  # D:\ 존재 확인
    except Exception:
        return False


def _ensure_dirs() -> None:
    for d in (RAW_TV, IMAGES):
        d.mkdir(parents=True, exist_ok=True)


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_symbol(symbol: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣_.-]", "", (symbol or "").strip())
    return s or "UNKNOWN"


def _sidecar(target: Path, meta: dict) -> None:
    target.with_suffix(target.suffix + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ──────────────────────────────────────────────────────────────────────
# (3) 데이터 성격 분석 — 어떤 필드를 교차검증에 쓸 수 있는가
# ──────────────────────────────────────────────────────────────────────
def analyze_csv_nature(raw: bytes | str, filename: str = "") -> dict:
    """CSV 헤더·표본을 보고 4층(가격/메타/파생/신뢰) 관점으로 성격 판정.
    pandas 없이 표준 csv 로 가볍게 파싱한다 (읽기 전용, 원본 변형 없음)."""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = raw
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return {"ok": False, "reason": "빈 CSV"}
    cols = [c.strip().lower() for c in header]
    rows = list(reader)
    n = len(rows)

    # date→time 동의어 정규화
    has_time = any(c in _TIME_COLS for c in cols)
    price_cols = [c for c in cols if c in _OHLCV and c != "volume"]
    has_volume = "volume" in cols or "vol" in cols
    derived = [c for c in cols if c not in _OHLCV and c not in _TIME_COLS and c not in ("vol",)]

    # 날짜 범위·타임프레임 추정
    date_min = date_max = None
    timeframe = None
    if has_time and rows:
        tcol_idx = next((i for i, c in enumerate(cols) if c in _TIME_COLS), 0)
        vals = [r[tcol_idx] for r in rows if len(r) > tcol_idx and r[tcol_idx].strip()]
        if vals:
            date_min, date_max = vals[0], vals[-1]
            timeframe = _infer_timeframe(vals)

    # 필드별 교차검증 가능성
    usable, notes = [], []
    for c in cols:
        v = _FIELD_VERDICT.get(c)
        if v:
            usable.append({"field": c, "verdict": v[0], "note": v[1]})
    for c in derived:
        usable.append({"field": c, "verdict": "no",
                       "note": "파생 지표(가격에서 결정론적 계산) — 교차검증 대상 아님, 자체 재계산으로 검증"})

    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(cols))
    crossval_ready = has_time and not missing and n >= 30

    return {
        "ok": True,
        "kind": "csv",
        "filename": filename,
        "rows": n,
        "columns": cols,
        "layers": {  # 4층 분류
            "price": price_cols + (["volume"] if has_volume else []),
            "meta": [c for c in cols if c in _TIME_COLS],
            "derived": derived,
        },
        "date_range": [date_min, date_max],
        "timeframe_inferred": timeframe,
        "adjusted_price": "UNKNOWN — TradingView 차트의 수정주가 설정을 export 시 확인 필요",
        "crossval_usable_fields": usable,
        "crossval_ready": crossval_ready,
        "blockers": (
            ([f"필수 컬럼 누락: {missing}"] if missing else [])
            + ([] if has_time else ["시간 컬럼 없음"])
            + ([] if n >= 30 else [f"행 수 부족({n}<30)"])
        ),
    }


def _infer_timeframe(vals: list[str]) -> str | None:
    """앞 두 타임스탬프 간격으로 타임프레임 추정."""
    def _parse(s: str):
        s = s.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                return datetime.strptime(s[: len(fmt) + 4], fmt)
            except Exception:
                continue
        if s.isdigit():
            try:
                return datetime.fromtimestamp(int(s), tz=timezone.utc)
            except Exception:
                return None
        return None
    if len(vals) < 2:
        return None
    a, b = _parse(vals[0]), _parse(vals[1])
    if not a or not b:
        return None
    sec = abs((b - a).total_seconds())
    if sec >= 80000:
        return "1D" if sec < 600000 else "1W+"
    if sec >= 3600:
        return f"{int(sec // 3600)}H"
    if sec >= 60:
        return f"{int(sec // 60)}m"
    return None


# ──────────────────────────────────────────────────────────────────────
# (1)(2) 적재 — 원본 변형 없이 증거 보존
# ──────────────────────────────────────────────────────────────────────
def save_csv(symbol: str, filename: str, raw: bytes, *, extra_context: str | None = None) -> dict:
    """CSV 원본을 00_raw_tv 에 그대로 적재 + 출처 사이드카. (ingest.py 가 이후 처리)"""
    if not available():
        return {"stored": False, "reason": "교차검증 드라이브(D:) 미마운트"}
    _ensure_dirs()
    sym = _safe_symbol(symbol)
    sha = hashlib.sha256(raw).hexdigest()
    target = RAW_TV / f"{sym}_{_now_stamp()}_tvexport.csv"
    target.write_bytes(raw)
    meta = {
        "source": "AI 종목 분석 창구",
        "reference_only": True,           # 참고용 — 거래 판단 반영 금지
        "do_not_reprocess_original": True,  # 원본 변형 금지(증거보존). 가공은 별도 폴더에서만
        "symbol": sym,
        "original_filename": filename,
        "received_at_kst": datetime.now().isoformat(),
        "sha256": sha,
        "bytes": len(raw),
        "extra_context": extra_context or None,
    }
    _sidecar(target, meta)
    return {"stored": True, "path": str(target), "sha256": sha[:16],
            "folder": "00_raw_tv", "next": "ingest.py → validate_naver.py"}


def save_image(symbol: str, filename: str, raw: bytes, *, extra_context: str | None = None) -> dict:
    """차트 스크린샷을 reference/images 에 참고용 증거로 보관 (수치 교차검증 불가)."""
    if not available():
        return {"stored": False, "reason": "교차검증 드라이브(D:) 미마운트"}
    _ensure_dirs()
    sym = _safe_symbol(symbol)
    sha = hashlib.sha256(raw).hexdigest()
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".png"
    target = IMAGES / f"{sym}_{_now_stamp()}_{sha[:8]}{ext}"
    target.write_bytes(raw)
    meta = {
        "source": "AI 종목 분석 창구",
        "reference_only": True,
        "crossval": "불가 — 이미지는 네이버 수치 대조 대상 아님 (참고/패턴 코퍼스용)",
        "symbol": sym,
        "original_filename": filename,
        "received_at_kst": datetime.now().isoformat(),
        "sha256": sha,
        "bytes": len(raw),
        "extra_context": extra_context or None,
    }
    _sidecar(target, meta)
    return {"stored": True, "path": str(target), "sha256": sha[:16],
            "folder": "reference/images", "crossval": "reference-only"}


# ──────────────────────────────────────────────────────────────────────
# (4) 코퍼스 통계 + 언어학습 발전 가능성 제안
# ──────────────────────────────────────────────────────────────────────
def corpus_stats() -> dict:
    """적재 코퍼스 현황 — 발전 제안의 grounding 근거 (읽기 전용)."""
    if not available():
        return {"available": False, "reason": "교차검증 드라이브(D:) 미마운트"}
    csvs = list(RAW_TV.glob("*.csv")) if RAW_TV.exists() else []
    imgs = [p for p in IMAGES.glob("*") if p.suffix.lower() in
            (".png", ".jpg", ".jpeg", ".webp", ".gif")] if IMAGES.exists() else []

    # 종목 다양성 (사이드카 메타에서 symbol 집계)
    symbols: set[str] = set()
    for p in csvs:
        m = re.match(r"([0-9A-Za-z가-힣]+)_", p.name)
        if m:
            symbols.add(m.group(1))

    # 검증 통과율 (validate_naver.py 리포트 집계)
    verified_ratio = None
    reports = list(VALIDATED.glob("*_report.json")) if VALIDATED.exists() else []
    if reports:
        ratios = []
        for r in reports:
            try:
                ratios.append(json.loads(r.read_text(encoding="utf-8")).get("verified_ratio"))
            except Exception:
                pass
        ratios = [x for x in ratios if isinstance(x, (int, float))]
        if ratios:
            verified_ratio = round(sum(ratios) / len(ratios), 4)

    quarantined = len(list(QUARANTINE.glob("*_mismatch.parquet"))) if QUARANTINE.exists() else 0

    return {
        "available": True,
        "csv_count": len(csvs),
        "image_count": len(imgs),
        "symbol_count": len(symbols),
        "symbols_sample": sorted(symbols)[:20],
        "validated_reports": len(reports),
        "avg_verified_ratio": verified_ratio,
        "quarantined_sets": quarantined,
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
    """코퍼스 통계를 근거로 LLM이 발전 가능성을 자율 생성 (해석/제안만)."""
    import httpx
    user = (
        "## 코퍼스 현황 (이 수치만 근거로 삼을 것)\n```json\n"
        + json.dumps(stats, ensure_ascii=False, indent=2)
        + "\n```\n위 현황을 바탕으로 발전 가능성을 지정 JSON으로만 제시하라."
    )
    sysp = _DEV_SYSTEM_PROMPT()

    if provider == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={api_key}")
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": sysp}]},
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
        }
        resp = httpx.post(url, json=payload, timeout=timeout_seconds)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:300]}")
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        base_url = "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": sysp},
                         {"role": "user", "content": user}],
            "temperature": 0.6,
            "response_format": {"type": "json_object"},
        }
        resp = httpx.post(f"{base_url}/chat/completions", json=payload,
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"},
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
