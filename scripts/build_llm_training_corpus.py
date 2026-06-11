"""LLM 학습 코퍼스 구축 — 10-K MD&A 추출 + 닷컴 국면 사례집 생성.

산출 (D:\STOCK DATA-US\dotcom_1995_2002\llm_training\):
  mdna/{SYM}_FY{년도}_{국면}.txt   MD&A(Item 7) 원문 + 메타데이터 헤더
  casebook.md                      사람용 국면 사례집 (검증 수치 전체)
  casebook_compact.json            분석 AI 주입용 압축본 (국면별 ~수백 바이트)
  build_report.json                추출 성공/실패 내역

원칙 (analysis-ai-training-method):
  - 수치는 전부 검증 데이터(ohlcv/valuation/features)에서 결정론 산출
  - 경영진 어조는 손수 고른 인용 대신 어휘 빈도 지표로 결정론화
  - 추출 실패 공시는 사유와 함께 기록 — 무데이터 요소는 사례집에서 제외
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"C:\stock\backend")
from regime_analogs import _phase, _PHASES  # noqa: E402 — 국면 라벨 단일 출처

ROOT = Path(r"D:\STOCK DATA-US\dotcom_1995_2002")
OUT = ROOT / "llm_training"
FYE_MONTH = {"MSFT": 6, "CSCO": 7, "ORCL": 5, "INTC": 12, "AMZN": 12}

# 경영진 어조 지표 어휘 (결정론 — 사례집에 그대로 공개)
EXPANSION_TERMS = ["record", "growth", "increase", "strong", "expand",
                   "demand", "opportunit"]
STRESS_TERMS = ["impairment", "restructur", "write-down", "writedown", "decline",
                "decrease", "weak", "uncertaint", "slowdown", "charge", "excess inventor"]


def fiscal_year_end(sym: str, filing: date) -> date:
    """접수일 직전의 회계연도 말일 (근사 — 월 말일 기준)."""
    m = FYE_MONTH[sym]
    y = filing.year if filing.month > m else filing.year - 1
    nxt = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return nxt - timedelta(days=1)


def extract_mdna(text: str) -> tuple[str | None, str]:
    """Item 7 (MD&A) 본문 추출. 목차의 가짜 매치를 피해 가장 긴 구간 채택."""
    # HTML 공시 대응: 태그 제거 + 엔티티 복원
    if "<TABLE" in text[:5000].upper() or "<html" in text[:2000].lower() or text.count("<") > 2000:
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    # 시작 후보: Item 7 헤딩 + (구형 CSCO/INTC 처럼 Exhibit 13 별첨에 들어간 경우 대비)
    # 'Management's Discussion and Analysis' 헤딩 전부
    starts = [m.start() for m in re.finditer(
        r"(?im)^\s*item\s*7[\.:]?\s*(management|—|-|—)?", text)]
    starts += [m.start() for m in re.finditer(
        r"(?i)management'?s\s+discussion\s+and\s+analysis", text)]
    if not starts:
        return None, "Item 7 / MD&A 헤딩 없음"
    # 끝 후보: Item 7A/8 또는 재무제표·감사보고서 시작 (별첨 내 MD&A 의 자연 경계)
    ends_pat = re.compile(
        r"^\s*item\s*(7a|8)[\.:]?\s"
        r"|report\s+of\s+(independent|ernst|the\s+auditors)"
        r"|consolidated\s+(balance\s+sheets?|statements?\s+of)"
        r"|quantitative\s+and\s+qualitative\s+disclosures",
        re.I | re.M)
    best, best_len = None, 0
    for s in sorted(set(starts)):
        m = ends_pat.search(text, s + 200)
        e = m.start() if m else min(s + 120_000, len(text))
        seg = text[s:min(e, s + 120_000)]
        if len(seg) > best_len:
            best, best_len = seg, len(seg)
    if best is None or best_len < 3000:
        return None, f"본문 길이 부족 ({best_len}자) — 목차만 매치된 듯"
    # 공백 정리
    best = re.sub(r"[ \t]+", " ", best)
    best = re.sub(r"\n{3,}", "\n\n", best)
    return best.strip(), "ok"


def tone_metrics(text: str) -> dict:
    """어조 지표: 1만 단어당 확장/스트레스 어휘 출현 횟수 (결정론)."""
    low = text.lower()
    words = max(len(low.split()), 1)
    exp = sum(low.count(t) for t in EXPANSION_TERMS)
    stress = sum(low.count(t) for t in STRESS_TERMS)
    return {
        "words": words,
        "expansionPer10k": round(exp / words * 10000, 1),
        "stressPer10k": round(stress / words * 10000, 1),
    }


def main() -> None:
    (OUT / "mdna").mkdir(parents=True, exist_ok=True)
    report = {"extracted": [], "failed": [], "builtAt": "2026-06-12"}

    # ── 1) MD&A 추출 ────────────────────────────────────────────────────────
    mdna_tones: dict[str, list[dict]] = {}  # phase → [{sym, fy, tone...}]
    for sym_dir in sorted((ROOT / "edgar").iterdir()):
        if not sym_dir.is_dir():
            continue
        sym = sym_dir.name
        for f in sorted(sym_dir.glob("*.txt")):
            filing = date.fromisoformat(f.name[:10])
            fye = fiscal_year_end(sym, filing)
            phase = _phase(fye.isoformat())
            body, status = extract_mdna(f.read_text(encoding="utf-8", errors="replace"))
            if body is None:
                report["failed"].append({"file": f.name, "symbol": sym, "reason": status})
                continue
            tone = tone_metrics(body)
            fy = fye.year
            header = (
                f"# 회사: {sym} | 회계연도: FY{fy} (말일 {fye}) | 접수일: {filing}\n"
                f"# 국면: {phase} (기준: 회계연도 말일, regime_analogs._PHASES)\n"
                f"# 출처: edgar/{sym}/{f.name} (SEC EDGAR 원본)\n"
                f"# 어조 지표(1만 단어당): 확장 {tone['expansionPer10k']} / "
                f"스트레스 {tone['stressPer10k']} (단어 {tone['words']:,})\n"
                + "#" * 78 + "\n\n"
            )
            out_name = f"{sym}_FY{fy}_{phase}.txt"
            (OUT / "mdna" / out_name).write_text(header + body, encoding="utf-8")
            report["extracted"].append({"file": f.name, "symbol": sym, "fy": fy,
                                        "phase": phase, "out": out_name, **tone})
            mdna_tones.setdefault(phase, []).append({"sym": sym, "fy": fy, **tone})
    print(f"MD&A 추출: 성공 {len(report['extracted'])} / 실패 {len(report['failed'])}")
    for fl in report["failed"]:
        print(f"  실패: {fl['file']} — {fl['reason']}")

    # ── 2) 국면별 검증 수치 (가격·밸류에이션·실제 결과) ───────────────────────
    ix = pd.read_csv(ROOT / "ohlcv" / "nasdaq_composite.csv",
                     index_col="date", parse_dates=True)["close"]
    pe = pd.read_csv(ROOT / "valuation" / "pe_ps_daily.csv", parse_dates=["date"])
    feats = []
    for f in (ROOT / "features").glob("*_features.csv"):
        d = pd.read_csv(f, parse_dates=["date"])
        d["sym"] = f.stem.replace("_features", "")
        feats.append(d)
    fdf = pd.concat(feats, ignore_index=True)

    casebook = {}
    for name, a, b in _PHASES:
        w = ix.loc[a:b]
        if len(w) < 2:
            continue
        peak = w.cummax()
        mdd = float(((w / peak - 1) * 100).min())
        block = {
            "기간": f"{a} ~ {b}",
            "나스닥": {"시작": round(float(w.iloc[0]), 1), "끝": round(float(w.iloc[-1]), 1),
                     "변화율pct": round((float(w.iloc[-1]) / float(w.iloc[0]) - 1) * 100, 1),
                     "구간내최대드로다운pct": round(mdd, 1)},
        }
        # 밸류에이션 관측값 (검증 P/E·P/S)
        pw = pe[(pe.date >= a) & (pe.date <= b)]
        vals = {}
        for sym in ["MSFT", "INTC", "CSCO", "ORCL"]:
            s = pw[(pw.symbol == sym) & pw.pe_ttm.notna()]
            if len(s) >= 20:
                vals[sym] = {"peStart": float(s.iloc[0].pe_ttm), "peMax": float(s.pe_ttm.max()),
                             "peEnd": float(s.iloc[-1].pe_ttm)}
        s = pw[(pw.symbol == "AMZN") & pw.ps_ttm.notna()]
        if len(s) >= 20:
            vals["AMZN_PS"] = {"psStart": float(s.iloc[0].ps_ttm), "psMax": float(s.ps_ttm.max()),
                               "psEnd": float(s.iloc[-1].ps_ttm)}
        if vals:
            block["밸류에이션관측"] = vals
        # 실제 결과: 이 국면에 속한 모든 시점의 20일 후 수익 (8개 시계열 풀)
        fw = fdf[(fdf.date >= a) & (fdf.date <= b) & fdf.fwd_ret_20d_pct.notna()]
        if len(fw) >= 100:
            block["실제20일후수익"] = {
                "표본": int(len(fw)),
                "상승비율pct": round(float((fw.fwd_ret_20d_pct > 0).mean() * 100), 1),
                "중앙값pct": round(float(fw.fwd_ret_20d_pct.median()), 2),
                "하위10pct": round(float(fw.fwd_ret_20d_pct.quantile(0.1)), 2),
                "상위10pct": round(float(fw.fwd_ret_20d_pct.quantile(0.9)), 2),
            }
        # 경영진 어조 (MD&A 어휘 빈도 — 해당 국면 회계연도 공시들)
        tones = mdna_tones.get(name, [])
        if tones:
            block["경영진어조"] = {
                "공시수": len(tones),
                "확장어휘per10k중앙값": round(sorted(t["expansionPer10k"] for t in tones)[len(tones) // 2], 1),
                "스트레스어휘per10k중앙값": round(sorted(t["stressPer10k"] for t in tones)[len(tones) // 2], 1),
            }
        casebook[name] = block

    (OUT / "casebook_compact.json").write_text(
        json.dumps(casebook, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 3) 사람용 casebook.md ───────────────────────────────────────────────
    md = ["# 닷컴 버블(1995~2002) 국면 사례집 — 전 수치 검증 데이터 출처",
          "",
          "수치 출처: ohlcv(FRED 교차검증) · valuation/pe_ps_daily.csv(10-K 전수 재대조) ·",
          "features(*_features.csv). 어조 지표는 MD&A 어휘 빈도(어휘 목록은 build 스크립트에 공개).",
          "MD&A 원문: llm_training/mdna/ (국면 라벨 포함). 생성: build_llm_training_corpus.py", ""]
    for name, block in casebook.items():
        md.append(f"## {name} ({block['기간']})")
        nz = block["나스닥"]
        md.append(f"- 나스닥: {nz['시작']} → {nz['끝']} ({nz['변화율pct']:+}%), "
                  f"구간 내 MDD {nz['구간내최대드로다운pct']}%")
        for sym, v in block.get("밸류에이션관측", {}).items():
            if sym == "AMZN_PS":
                md.append(f"- AMZN P/S: 시작 {v['psStart']} / 최고 {v['psMax']} / 끝 {v['psEnd']}")
            else:
                md.append(f"- {sym} P/E: 시작 {v['peStart']} / 최고 {v['peMax']} / 끝 {v['peEnd']}")
        if "실제20일후수익" in block:
            r = block["실제20일후수익"]
            md.append(f"- 이 국면 임의 시점의 20일 후: 상승 {r['상승비율pct']}% · "
                      f"중앙값 {r['중앙값pct']}% · 하위10% {r['하위10pct']}% · 상위10% {r['상위10pct']}% "
                      f"(표본 {r['표본']:,})")
        if "경영진어조" in block:
            t = block["경영진어조"]
            md.append(f"- 경영진 어조(MD&A {t['공시수']}건): 확장어휘 {t['확장어휘per10k중앙값']} vs "
                      f"스트레스어휘 {t['스트레스어휘per10k중앙값']} (1만 단어당 중앙값)")
        md.append("")
    (OUT / "casebook.md").write_text("\n".join(md), encoding="utf-8")

    (OUT / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"사례집: 국면 {len(casebook)}개 — casebook_compact.json / casebook.md 저장")


if __name__ == "__main__":
    main()
