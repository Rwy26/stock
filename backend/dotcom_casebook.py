"""닷컴(1995~2002) 국면 사례집 — 분석 AI 프롬프트 주입용.

데이터: D:\STOCK DATA-US\dotcom_1995_2002\llm_training\casebook_compact.json
  (build_llm_training_corpus.py 산출 — 전 수치가 검증 데이터셋에서 결정론 산출:
   나스닥 FRED 교차검증, P/E 는 10-K 전수 재대조, 어조 지표는 MD&A 어휘 빈도)

역할: target_engine 의 dotcomAnalogs 매칭 결과(국면 분포)에 해당하는 국면 블록만
골라 LLM 컨텍스트에 넣는다 — 매칭된 국면이 당시 어떤 환경이었고(밸류에이션·지수),
그 국면에서 20일 보유가 실제로 어떤 분포였는지를 AI 가 인용할 수 있게.
토큰 절약을 위해 상위 2개 국면만 주입. 데이터 부재 시 None (주입 생략, 무영향).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

CASEBOOK_PATH = Path(os.environ.get(
    "DOTCOM_DATA_ROOT", r"D:\STOCK DATA-US\dotcom_1995_2002"
)) / "llm_training" / "casebook_compact.json"

_lock = threading.Lock()
_cache: Optional[dict] = None
_loaded = False


def _load() -> Optional[dict]:
    global _cache, _loaded
    if _loaded:
        return _cache
    with _lock:
        if _loaded:
            return _cache
        try:
            _cache = json.loads(CASEBOOK_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cache = None
        _loaded = True
        return _cache


def context_block(dotcom_analogs: dict) -> Optional[dict]:
    """dotcomAnalogs 의 국면 분포 상위 2개에 해당하는 사례집 블록 반환.

    매칭이 없거나(error) 사례집 파일이 없으면 None — 호출부는 주입을 생략한다.
    """
    if not dotcom_analogs or "error" in dotcom_analogs:
        return None
    phases = dotcom_analogs.get("phaseDistribution") or {}
    if not phases:
        return None
    book = _load()
    if not book:
        return None
    top = sorted(phases.items(), key=lambda x: -x[1])[:2]
    blocks = {name: book[name] for name, _ in top if name in book}
    if not blocks:
        return None
    return {
        "설명": ("현재 국면과 가장 비슷했던 1995~2002 미국 닷컴 국면의 검증 기록 — "
               "수치는 전부 실측(지수 FRED 교차검증, P/E 는 SEC 10-K 전수 재대조). "
               "'실제20일후수익'은 그 국면 임의 시점에 진입했을 때의 실현 분포다."),
        "매칭국면": blocks,
    }
