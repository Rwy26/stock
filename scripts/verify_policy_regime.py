"""verify_policy_regime.py — 시한부 정책·선거 가중 로직 단위검증 (네트워크 비의존).

검증 항목:
  (a) 정치타깃 가중 오버라이드: 윈도우 내 Polymarket 0.6/Kalshi 0.4(+Metaculus 제외),
      윈도우 밖 0.4/0.4/0.2 — 두 분기 consensus 수치로 확인.
  (b) policyRegime 블록 주입/제거: compute_market_compass(with_ai=False) 두 분기.
  (c) 비정치 타깃·기존 5+4 macroMap·점수 회귀 없음.
  (d) 시그널 적중추적(risk_signals/probabilities) 충돌 없음(구조 유지).

실행:  backend\.venv\Scripts\python.exe scripts\verify_policy_regime.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import global_macro_feeds as gmf  # noqa: E402

IN = date(2026, 6, 18)            # 윈도우 내
OUT = date(2026, 11, 4)           # 윈도우 밖 (다음날)

ok = True


def check(label: str, cond: bool, extra: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}")


# --- (a) 가중 오버라이드: 순수 consensus 산출을 합성 소스값으로 검증 ----------------
def consensus(parts: dict, key: str, today) -> float | None:
    weights, _mode = gmf._weights_for(key, today)
    avail = {k: v for k, v in parts.items() if v is not None and k in weights}
    if not avail:
        return None
    wsum = sum(weights[k] for k in avail)
    return round(sum(v * weights[k] for k, v in avail.items()) / wsum, 1)


print("\n(a) 소스 가중 오버라이드 — 정치·Fed 타깃")
poly, kal, meta = 70.0, 30.0, 90.0   # 합성 (poly≠kal 이라 가중 차이가 수치로 드러남)
parts = {"polymarket": poly, "kalshi": kal, "metaculus": meta}

c_in = consensus(parts, "fed_cut_next", IN)     # 0.6*70 + 0.4*30 = 54.0 (meta 제외)
c_out = consensus(parts, "fed_cut_next", OUT)   # 0.4/0.4/0.2 → (0.4*70+0.4*30+0.2*90)/1.0 = 58.0
check("윈도우 내 정치타깃 = Poly0.6/Kal0.4, Metaculus 제외", c_in == 54.0, f"got {c_in}")
check("윈도우 밖 정치타깃 = 기본 0.4/0.4/0.2", c_out == 58.0, f"got {c_out}")
m_in = gmf._weights_for("fed_cut_next", IN)[1]
m_out = gmf._weights_for("fed_cut_next", OUT)[1]
check("weight_mode 라벨 분기", m_in == "policy_window" and m_out == "default", f"{m_in}/{m_out}")

print("\n(c-1) 비정치 타깃은 윈도우와 무관하게 기본 가중")
c_np_in = consensus(parts, "recession_2026", IN)
c_np_out = consensus(parts, "recession_2026", OUT)
check("비정치 타깃 consensus 윈도우 불변", c_np_in == c_np_out == 58.0, f"{c_np_in}/{c_np_out}")
check("비정치 타깃 weight_mode=default(양 분기)",
      gmf._weights_for("recession_2026", IN)[1] == "default"
      and gmf._weights_for("recession_2026", OUT)[1] == "default")

print("\n   election_window_active 경계")
check("경계일(11-03) 포함", gmf.election_window_active(date(2026, 11, 3)) is True)
check("다음날(11-04) 제외", gmf.election_window_active(date(2026, 11, 4)) is False)

# --- (b)(c)(d) compute_market_compass 두 분기 (네트워크/LLM 없이) -------------------
# 외부 호출(예측시장/yfinance/뉴스/sector_rotation)을 결정론 스텁으로 대체해 분기만 검증.
import global_macro  # noqa: E402
import market_compass as mc  # noqa: E402

_STUB_PRED = {
    "fed_cut_next": {"polymarket": 70.0, "kalshi": 30.0, "metaculus": None,
                     "consensus": None, "n_sources": 2, "weight_mode": None,
                     "feeds_into": ["liquidity"], "label": "Fed 금리 인하 (연내)"},
    "us_gov_shutdown": {"polymarket": 40.0, "kalshi": None, "metaculus": None,
                        "consensus": 40.0, "n_sources": 1, "weight_mode": None,
                        "feeds_into": ["risk_appetite", "geopolitics"], "label": "미 정부 셧다운"},
}
_STUB_NEWS = {"sectors": {"반도체": {"headlines": [
    {"title": "트럼프, 16개국에 10% 관세 재부과 검토"},
    {"title": "파월 연준의장 해임 압박 수위 높여"},
    {"title": "삼성전자 신고가 경신"},   # 비정책 — 태깅 안 돼야
]}}}


def patched_compute(today):
    """today 분기로 compute_market_compass 실행 (모든 외부 IO 스텁)."""
    orig = {
        "today": gmf.election_window_active,
        "gm": global_macro.compute_global_macro,
        "rot": None,
    }
    # 윈도우 분기 주입
    gmf.election_window_active = lambda t=None: gmf.ELECTION_WINDOW_UNTIL >= today  # noqa: E731

    def fake_gm(force=False):
        return {"scores": {k: 50 for k in global_macro.SCORE_KEYS},
                "composite": 50, "flow": "중립",
                "probabilities": {"method": "deterministic", "n": None,
                                  "1w": {"up": 50, "down": 50}},
                "kr_sectors": {}, "kr_sector_matrix": {}, "risk_signals": [],
                "evidence": {}, "asof": "stub",
                "inputs": {"prediction": _STUB_PRED}}
    global_macro.compute_global_macro = fake_gm

    import sector_rotation
    orig["rot"] = sector_rotation.compute_sector_rotation
    sector_rotation.compute_sector_rotation = lambda force=False: {
        "sectors": [{"sector": "반도체", "score": 70, "lifecycle": "성장",
                     "detail": {"intradayPct": 1.0}, "breakdown": {}}],
        "macroDetail": {"tnx": 4.4, "tnx20dChg": 1.0, "usKrw": 1380, "usKrwChg5d": 0.5,
                        "oil": 75, "oilChg5d": -1.0, "nasdaq": 18000, "nasdaqChg20d": 2.0,
                        "vix": 18}}

    import news_collector
    orig["nc_collect"] = news_collector.collect
    orig["nc_ctx"] = news_collector.get_news_context
    news_collector.collect = lambda pages=1: None
    news_collector.get_news_context = lambda *a, **k: _STUB_NEWS

    mc._cache = None
    mc._cache_ts = 0.0
    try:
        return mc.compute_market_compass(force=True, with_ai=False)
    finally:
        gmf.election_window_active = orig["today"]
        global_macro.compute_global_macro = orig["gm"]
        sector_rotation.compute_sector_rotation = orig["rot"]
        news_collector.collect = orig["nc_collect"]
        news_collector.get_news_context = orig["nc_ctx"]


print("\n(b) policyRegime 블록 주입/제거")
r_in = patched_compute(IN)
r_out = patched_compute(OUT)
check("윈도우 내 policyRegime 존재", "policyRegime" in r_in)
check("윈도우 밖 policyRegime 부재", "policyRegime" not in r_out)
if "policyRegime" in r_in:
    pr = r_in["policyRegime"]
    check("windowUntil = 2026-11-03", pr.get("windowUntil") == "2026-11-03", pr.get("windowUntil"))
    titles = [n["title"] for n in pr.get("policyNews", [])]
    check("관세 뉴스 태깅", any("관세" in t for t in titles))
    check("연준압박 뉴스 태깅", any("파월" in t for t in titles))
    check("비정책 뉴스(신고가) 미태깅", not any("신고가" in t for t in titles))
    check("예측시장 수치 surface(fed_cut_next)",
          any(m["key"] == "fed_cut_next" for m in pr.get("predictionMarkets", [])))

print("\n(c-2) 기존 macroMap 5+4 행 회귀 없음 (양 분기 동일)")
check("macroMap 행 수 동일", len(r_in["macroMap"]) == len(r_out["macroMap"]),
      f"{len(r_in['macroMap'])} vs {len(r_out['macroMap'])}")
factors = [row["factor"] for row in r_in["macroMap"]]
base5 = ["미 10Y 금리", "원달러", "유가(WTI)", "나스닥", "VIX(미국)"]
glob4 = ["글로벌 위험선호", "글로벌 유동성", "AI 투자사이클", "지정학 리스크"]
check("기존 국내 5행 유지", all(f in factors for f in base5))
check("글로벌 4행 유지", all(f in factors for f in glob4))

print("\n(d) 시그널 적중추적 구조 회귀 없음")
check("globalSentiment.riskSignals 키 유지(양 분기)",
      "riskSignals" in r_in["globalSentiment"] and "riskSignals" in r_out["globalSentiment"])
check("probabilities 구조 유지", "probabilities" in r_in["globalSentiment"])
check("regime/sectorRanking 등 본체 회귀 없음",
      r_in["regime"]["label"] == r_out["regime"]["label"]
      and r_in["sectorRanking"] == r_out["sectorRanking"])

print(f"\n{'='*48}\n  결과: {'ALL PASS ✅' if ok else 'FAILURES ❌'}\n{'='*48}")
sys.exit(0 if ok else 1)
