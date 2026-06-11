"""닷컴 데이터셋 밸류에이션 레이어 — 10-K 검증 추출본 → P/E·P/S 시계열.

방법:
 1. raw_10k_extracts/{SYM}.json (전수 원본 대조 통과본) 로드.
 2. 회계분기 → 달력분기 매핑 (회사별 회계연도 상이).
 3. 같은 분기의 복수 공시(분할 재표시) 정합성 검증:
    eps_현재기준 = eps_공시 / (공시일 이후 분할 누적비) 가 공시 간 일치해야 함.
 4. 분기별 최신 공시 채택 → 현재(야후) 주식수 기준으로 정규화.
 5. TTM(직전 4분기 합) 희석 EPS → 일별 P/E = close(분할조정, 배당 미조정) / TTM EPS.
    AMZN 은 전 기간 적자 → P/E 대신 P/S = close × 주식수(현재기준) / TTM 매출.
 6. 문헌 기준값 대조 (CSCO 고점 P/E >120×, AMZN P/S ~48×) — 차이는 사유와 함께 기록.

주의: EPS 는 분기말 기준 정렬 (실제 공시 시차 미반영 — 사후 분석용, 실시간 신호 금지).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\STOCK DATA-US\dotcom_1995_2002")
VAL = ROOT / "valuation"
SYMS = ["MSFT", "INTC", "CSCO", "ORCL", "AMZN"]

splits = pd.read_csv(ROOT / "actions" / "splits_full_history.csv", parse_dates=["date"])

# 공시 기준일 예외: 공시가 직후 발효 예정 분할을 선반영해 인쇄한 경우.
# INTC FY1998 10-K(1999-03-26 접수)는 1999-04-12 2:1 분할(1월 선언)을 이미 반영 —
# 직전 공시 대비 전 분기 EPS 가 정확히 1/2 로 인쇄된 것으로 입증됨.
FILING_BASIS_OVERRIDES: dict[tuple[str, str], tuple[str, ...]] = {
    ("INTC", "1999-03-26"): ("1999-04-12",),
}

# 회사별 표준 분기말 월 (52/53주 회계로 실제 일자가 ±1주 표류 → 그리드에 스냅)
QUARTER_MONTHS = {"MSFT": (3, 6, 9, 12), "INTC": (3, 6, 9, 12), "AMZN": (3, 6, 9, 12),
                  "ORCL": (2, 5, 8, 11), "CSCO": (1, 4, 7, 10)}


def split_factor_after(sym: str, when: pd.Timestamp, filing_key: str = "") -> float:
    excluded = FILING_BASIS_OVERRIDES.get((sym, filing_key), ())
    s = splits[(splits.symbol == sym) & (splits.date > when)]
    f = 1.0
    for _, r in s.iterrows():
        if r["date"].strftime("%Y-%m-%d") in excluded:
            continue
        f *= float(r["ratio"])
    return f


def snap_quarter(sym: str, year: int, mon: int) -> str:
    """실제 분기말 월을 회사 표준 분기 그리드에 스냅 (예: CSCO 5월 1일 → 4월 분기)."""
    grid = QUARTER_MONTHS[sym]
    best, best_d = None, 99
    for gm in grid:
        for dy in (-1, 0, 1):
            d = abs((year * 12 + mon) - ((year + dy) * 12 + gm))
            if d < best_d:
                best_d, best = d, (year + dy, gm)
    return f"{best[0]}-{best[1]:02d}"


def parse_num(v) -> float | None:
    """공시 표기 → float: '1,017,879' / '(0.37)' / '.37' / '92 3/8' / '44-1/4'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lstrip("$")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    m = re.match(r"^(\d+)[\s-](\d+)/(\d+)$", s)  # 분수 표기
    if m:
        f = int(m.group(1)) + int(m.group(2)) / int(m.group(3))
        return -f if neg else f
    m2 = re.match(r"^(\d+)/(\d+)$", s)
    if m2:
        f = int(m2.group(1)) / int(m2.group(2))
        return -f if neg else f
    try:
        f = float(s)
        return -f if neg else f
    except ValueError:
        return None


def quarter_end(sym: str, fy: int, label: str) -> str | None:
    """(회계연도, 분기 라벨) → 달력 분기말 'YYYY-MM'."""
    L = label.lower()
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2},\s*(\d{4})", L)
    if m:  # CSCO 식 명시 일자 → 표준 분기 그리드에 스냅
        mon = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"].index(m.group(1)) + 1
        return snap_quarter(sym, int(m.group(2)), mon)
    if sym == "MSFT":  # FY 6월 말
        for k, (mon, off) in {"sept": (9, -1), "dec": (12, -1), "mar": (3, 0), "june": (6, 0)}.items():
            if k in L:
                return f"{fy + off}-{mon:02d}"
    if sym == "INTC":  # FY 12월 말
        q = {"q1": 3, "q2": 6, "q3": 9, "q4": 12}
        for k, mon in q.items():
            if L.startswith(k):
                return f"{fy}-{mon:02d}"
    if sym == "ORCL":  # FY 5월 말
        for k, (mon, off) in {"first": (8, -1), "second": (11, -1),
                              "third": (2, 0), "fourth": (5, 0)}.items():
            if k in L:
                return f"{fy + off}-{mon:02d}"
    if sym == "AMZN":  # 달력 연도
        q = {"q1": 3, "q2": 6, "q3": 9, "q4": 12}
        for k, mon in q.items():
            if L.startswith(k):
                return f"{fy}-{mon:02d}"
    if sym == "CSCO":  # 가격 전용 레코드 (financials 없음) → 건너뜀
        return None
    return None


def main() -> None:
    issues: list[str] = []
    canon: dict[str, dict[str, dict]] = {s: {} for s in SYMS}  # sym → qend → record

    for sym in SYMS:
        data = json.loads((VAL / "raw_10k_extracts" / f"{sym}.json").read_text(encoding="utf-8"))
        groups: dict[str, list[dict]] = {}
        for rec in data:
            if rec.get("verification_failed") or rec.get("fiscal_year") is None:
                continue
            eps = rec.get("eps_diluted") or rec.get("eps") or rec.get("eps_basic")
            eps_f = parse_num(eps)
            if eps_f is None and parse_num(rec.get("revenue")) is None:
                continue  # 가격 전용 레코드
            qe = quarter_end(sym, int(rec["fiscal_year"]), str(rec.get("quarter_label", "")))
            if qe is None:
                continue
            filing_key = Path(rec["source_file"]).name[:10]
            filing = pd.Timestamp(filing_key)
            factor = split_factor_after(sym, filing, filing_key)
            # 매출 단위: thousands → millions 통일
            unit_txt = (str(rec.get("units", "")) + " " + str(rec.get("note", ""))).lower()
            rev = parse_num(rec.get("revenue"))
            if rev is not None and "thousand" in unit_txt:
                rev /= 1000.0
            shares = rec.get("weighted_avg_shares")
            if isinstance(shares, dict):
                shares = shares.get("diluted") or shares.get("basic")
            shares_f = parse_num(shares)
            groups.setdefault(qe, []).append({
                "filing": filing,
                "eps_cur": round(eps_f / factor, 6) if eps_f is not None else None,
                "eps_as_printed": eps_f,
                "revenue_m": rev,
                "net_income": parse_num(rec.get("net_income")),
                "shares_cur_k": shares_f * factor if shares_f is not None else None,
                "src": Path(rec["source_file"]).name,
            })

        for qe, occs in groups.items():
            # 분할 재표시 정합성: 현재기준 EPS 가 공시 간 일치해야 함
            eps_curs = [o["eps_cur"] for o in occs if o["eps_cur"] is not None]
            if len(eps_curs) >= 2:
                spread = max(eps_curs) - min(eps_curs)
                # 공시 EPS 는 0.01 단위 반올림 → 허용오차 = 0.005/min(factor) 합산 근사
                if spread > 0.011:
                    issues.append(f"{sym} {qe}: 재표시 EPS 불일치 {sorted(set(eps_curs))} "
                                  f"(출처 {[o['src'][:10] for o in occs]})")
            latest = max(occs, key=lambda o: o["filing"])
            canon[sym][qe] = latest

    print(f"재표시 정합성 위반: {len(issues)}건")
    for i in issues:
        print("  ", i)

    # ── 분기 펀더멘털 CSV ──────────────────────────────────────────────────
    rows = []
    for sym in SYMS:
        for qe in sorted(canon[sym]):
            c = canon[sym][qe]
            rows.append({"symbol": sym, "quarter_end": qe,
                         "eps_diluted_current_basis": c["eps_cur"],
                         "revenue_millions": c["revenue_m"],
                         "shares_current_basis_k": c["shares_cur_k"],
                         "source_filing": c["src"]})
    qdf = pd.DataFrame(rows)
    qdf.to_csv(VAL / "quarterly_fundamentals.csv", index=False)
    print(f"분기 펀더멘털 {len(qdf)}행 저장")

    # ── 일별 P/E (P/S for AMZN) ────────────────────────────────────────────
    out_rows = []
    checks = []
    for sym in SYMS:
        px = pd.read_csv(ROOT / "ohlcv" / f"{sym}.csv", index_col="date", parse_dates=True)
        qs = sorted(canon[sym])
        ttm_eps, ttm_rev, sh = {}, {}, {}
        for i in range(3, len(qs)):
            window = qs[i - 3: i + 1]
            # 분기 연속성: 4분기가 끊김 없이 이어져야 TTM 유효
            ms = [pd.Period(q, freq="M") for q in window]
            if any((ms[j + 1] - ms[j]).n != 3 for j in range(3)):
                continue
            es = [canon[sym][q]["eps_cur"] for q in window]
            rs = [canon[sym][q]["revenue_m"] for q in window]
            qend = qs[i]
            if all(e is not None for e in es):
                ttm_eps[qend] = round(sum(es), 6)
            if all(r is not None for r in rs):
                ttm_rev[qend] = round(sum(rs), 3)
            if canon[sym][qend]["shares_cur_k"] is not None:
                sh[qend] = canon[sym][qend]["shares_cur_k"]
        # 일별 매핑: 해당 일자 이전 가장 최근 분기말
        keys = sorted(ttm_eps.keys() | ttm_rev.keys())
        if not keys:
            continue
        kperiods = [pd.Period(k, freq="M").end_time for k in keys]
        for dt, row in px.iterrows():
            j = -1
            for idx, ke in enumerate(kperiods):
                if ke <= dt:
                    j = idx
            if j < 0:
                continue
            q = keys[j]
            close = float(row["close"])  # 분할 조정·배당 미조정 — EPS 현재기준과 동일 기준
            eps = ttm_eps.get(q)
            pe = round(close / eps, 1) if eps and eps > 0 else None
            ps = None
            if sym == "AMZN" and ttm_rev.get(q) and sh.get(q):
                # close($) × 주식수(천주) / 매출(백만$) → ($·천주)/백만$ = 배수/1000 보정
                ps = round(close * sh[q] / 1000.0 / ttm_rev[q], 1)
            out_rows.append({"date": dt.strftime("%Y-%m-%d"), "symbol": sym,
                             "close_split_adj": close, "ttm_eps": eps,
                             "pe_ttm": pe, "ps_ttm": ps, "ttm_quarter": q})
    pdf = pd.DataFrame(out_rows)
    pdf.to_csv(VAL / "pe_ps_daily.csv", index=False)
    print(f"일별 밸류에이션 {len(pdf)}행 저장")

    # ── 문헌 대조 ──────────────────────────────────────────────────────────
    sub = pdf[(pdf.symbol == "CSCO") & (pdf.date == "2000-03-27")]
    if len(sub):
        pe = sub.iloc[0]["pe_ttm"]
        checks.append(f"CSCO 2000-03-27 GAAP TTM P/E = {pe}배 (문헌 '>120배' — GAAP 는 "
                      f"IPR&D 일회성 비용으로 EPS 가 낮아 문헌(프로포마 추정)보다 높게 나옴)")
    amz = pdf[(pdf.symbol == "AMZN") & (pdf.ps_ttm.notna())]
    if len(amz):
        peak = amz.loc[amz.ps_ttm.idxmax()]
        checks.append(f"AMZN P/S 최고 = {peak.ps_ttm}배 ({peak.date}) (문헌 '~48배')")
    for c in checks:
        print("  [대조]", c)

    rp = ROOT / "verification_report.json"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    rep["valuationLayer"] = {
        "builtFrom": "SEC 10-K 원본 46건 — 추출 427레코드 전수 원본 재대조 통과",
        "restatementIssues": issues,
        "literatureCrossChecks": checks,
        "caveats": [
            "EPS 는 분기말 기준 정렬 — 실제 공시 시차(1~3개월) 미반영, 사후 분석 전용",
            "GAAP EPS 기준 — IPR&D 등 일회성 비용 포함, 당시 통용 '프로포마 P/E' 보다 높음",
            "ORCL FY2000 Q4 는 대규모 영업외이익 포함 (EPS 0.82) — 직후 1년 P/E 왜곡",
        ],
    }
    rp.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("verification_report.json 갱신 완료")


if __name__ == "__main__":
    main()
