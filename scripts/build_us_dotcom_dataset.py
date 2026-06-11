"""닷컴 버블(1995~2002) 미국 시장 데이터셋 구축 — D:\STOCK DATA-US\dotcom_1995_2002

목적: 유사 국면 확률 엔진의 비교 표본 확장 — 현재 한국 시장 국면을
1995~2002 나스닥 과열·붕괴 국면과 다차원 매칭하기 위한 기초 데이터.

레이어:
  ohlcv/      일봉 시세 (yfinance, auto_adjust=False — 원시 종가 + 수정 종가 병행)
  macro/      FRED 공식 시계열 (나스닥 지수 교차검증 + 거시 맥락)
  features/   target_engine._regime_features 와 동일 정의의 6차원 국면 특징
              + 드로다운/200일선 괴리/미래수익 라벨 (라벨은 분석용 — 실시간 사용 금지)
  actions/    분할·배당 이력 (수정주가 검증용)
  edgar/      SEC EDGAR 원본 10-K 공시 전문 (밸류에이션 추출·LLM 학습 원전)
  verification_report.json  검증 결과 — 통과/실패/검증 불가 전부 기록

데이터 정확성 원칙: 교차검증 실패·불가 항목은 보고서에 명시. 수치 가공·보정 없음.
실행: backend\.venv 파이썬으로 실행 (yfinance/pandas/httpx 필요).
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

# Windows 콘솔(cp949)에서 em-dash 등 출력 실패 방지
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"D:\STOCK DATA-US\dotcom_1995_2002")
START, END = "1995-01-01", "2002-12-31"

H_WEB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# SEC 요구사항: 연락처가 포함된 식별 UA + 초당 10요청 미만
H_SEC = {"User-Agent": "MOON STOCK research (private research; contact: moonstock.research@gmail.com)"}

STOCKS = ["AMZN", "CSCO", "INTC", "ORCL", "MSFT"]
INDICES = {
    "^IXIC": "nasdaq_composite",   # FRED NASDAQCOM 과 전구간 교차검증
    "^NDX": "nasdaq_100",          # 단일 소스 — 보고서에 명시
    "^GSPC": "sp500",              # 단일 소스 — 보고서에 명시
}
FRED_SERIES = {
    "NASDAQCOM": "나스닥 종합지수 (교차검증 기준)",
    "DGS10": "미 10년물 국채금리 %",
    "DFF": "연방기금금리 실효 %",
    "DEXKOUS": "원/달러 환율 (한국 국면 비교용)",
}
# EDGAR CIK — ORCL 은 구법인(ORACLE CORP /DE/)이 1995~2003 공시 보유
CIKS = {"AMZN": "0001018724", "CSCO": "0000858877", "INTC": "0000050863",
        "ORCL": "0000777676", "MSFT": "0000789019"}

report: dict = {"builtAt": datetime.now().isoformat(timespec="seconds"),
                "period": [START, END], "checks": [], "warnings": []}


def _check(name: str, passed: bool, detail: str) -> None:
    report["checks"].append({"name": name, "passed": passed, "detail": detail})
    print(("  [PASS] " if passed else "  [FAIL] ") + f"{name} — {detail}")


# ── 1) 시세 (yfinance) ──────────────────────────────────────────────────────
def fetch_prices() -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    (ROOT / "ohlcv").mkdir(parents=True, exist_ok=True)
    for sym, alias in {**{s: s for s in STOCKS}, **INDICES}.items():
        df = yf.download(sym, start=START, end="2003-01-01",
                         auto_adjust=False, progress=False)
        if df.empty:
            report["warnings"].append(f"{sym}: yfinance 응답 없음")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                "Close": "close", "Adj Close": "adj_close",
                                "Volume": "volume"})
        df.index.name = "date"
        cols = ["open", "high", "low", "close", "adj_close", "volume"]
        df = df[[c for c in cols if c in df.columns]].round(6)
        name = alias if sym in INDICES else sym
        df.to_csv(ROOT / "ohlcv" / f"{name}.csv")
        out[sym] = df
        print(f"  {sym}: {len(df)}봉 ({df.index[0].date()} ~ {df.index[-1].date()})")
        time.sleep(0.4)
    return out


# ── 2) FRED 공식 시계열 + 나스닥 교차검증 ────────────────────────────────────
def fetch_fred_and_verify(prices: dict[str, pd.DataFrame]) -> None:
    (ROOT / "macro").mkdir(parents=True, exist_ok=True)
    fred: dict[str, pd.Series] = {}
    for sid, desc in FRED_SERIES.items():
        r = None
        for attempt in range(4):  # FRED 가 간헐적으로 느림 — 재시도
            try:
                r = httpx.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                              params={"id": sid, "cosd": START, "coed": END},
                              headers=H_WEB, timeout=120, follow_redirects=True)
                r.raise_for_status()
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 3:
                    report["warnings"].append(f"FRED {sid}: 조회 실패 {type(exc).__name__}")
                    r = None
                else:
                    time.sleep(3 * (attempt + 1))
        if r is None:
            continue
        df = pd.read_csv(pd.io.common.StringIO(r.text))
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df.to_csv(ROOT / "macro" / f"fred_{sid}.csv", index=False)
        fred[sid] = df.set_index("date")["value"]
        print(f"  FRED {sid}: {df['value'].notna().sum()}개 관측치 — {desc}")
        time.sleep(0.3)

    # 나스닥 종합 교차검증: yfinance ^IXIC vs FRED NASDAQCOM (전구간 일별)
    if "^IXIC" in prices and "NASDAQCOM" in fred:
        yx = prices["^IXIC"]["close"].copy()
        yx.index = yx.index.strftime("%Y-%m-%d")
        fx = fred["NASDAQCOM"].dropna()
        both = pd.DataFrame({"yf": yx, "fred": fx}).dropna()
        rel = (both["yf"] - both["fred"]).abs() / both["fred"]
        ok = (rel <= 0.001).mean() * 100  # 0.1% 이내 일치율
        _check("나스닥 종합 yfinance↔FRED 일별 교차검증",
               bool(ok >= 99.5 and len(both) > 1900),
               f"{len(both)}일 비교, 0.1% 이내 일치 {ok:.2f}%, 최대편차 {rel.max()*100:.4f}%")
        peak = both["fred"].idxmax()
        _check("버블 고점 일자/값 (공식 기록 대조)",
               bool(peak == "2000-03-10" and abs(both.loc[peak, "fred"] - 5048.62) < 0.01),
               f"고점 {peak} = {both.loc[peak, 'fred']}")


# ── 3) 분할·배당 이력 ────────────────────────────────────────────────────────
def fetch_actions() -> None:
    import yfinance as yf

    (ROOT / "actions").mkdir(parents=True, exist_ok=True)
    rows = []
    for sym in STOCKS:
        tk = yf.Ticker(sym)
        sp = tk.splits
        dv = tk.dividends
        for d, ratio in sp.items():
            if d.strftime("%Y-%m-%d") <= END:
                rows.append({"symbol": sym, "date": d.strftime("%Y-%m-%d"),
                             "action": "split", "value": float(ratio)})
        for d, amt in dv.items():
            if d.strftime("%Y-%m-%d") <= END:
                rows.append({"symbol": sym, "date": d.strftime("%Y-%m-%d"),
                             "action": "dividend", "value": float(amt)})
        time.sleep(0.4)
    pd.DataFrame(rows).sort_values(["symbol", "date"]).to_csv(
        ROOT / "actions" / "corporate_actions_1995_2002.csv", index=False)
    n_splits = sum(1 for r in rows if r["action"] == "split")
    print(f"  분할 {n_splits}건 + 배당 {len(rows) - n_splits}건 저장")


# ── 4) 구조 무결성 검증 (OHLC·캘린더·분할 연속성) ────────────────────────────
def verify_structure(prices: dict[str, pd.DataFrame]) -> None:
    actions = pd.read_csv(ROOT / "actions" / "corporate_actions_1995_2002.csv")
    for sym in STOCKS + list(INDICES):
        if sym not in prices:
            continue
        df = prices[sym]
        # OHLC 정합: low ≤ open/close ≤ high, 전부 양수
        bad = ((df["low"] > df[["open", "close"]].min(axis=1)) |
               (df["high"] < df[["open", "close"]].max(axis=1)) |
               (df[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum()
        _check(f"{sym} OHLC 정합", bool(bad == 0), f"위반 {bad}일 / {len(df)}일")
        # 캘린더: 7일 초과 공백 없음 (미국 휴장 최대 4~5일)
        gaps = df.index.to_series().diff().dt.days.fillna(1)
        big = int((gaps > 7).sum())
        _check(f"{sym} 거래일 연속성", big == 0, f"7일 초과 공백 {big}회")
        if sym in STOCKS:
            # 분할일에 수정종가(adj_close)는 점프하지 않아야 함 (±25% 이내)
            sp = actions[(actions.symbol == sym) & (actions.action == "split")]
            jumps = 0
            for d in sp["date"]:
                ts = pd.Timestamp(d)
                if ts in df.index:
                    i = df.index.get_loc(ts)
                    if i > 0:
                        chg = abs(df["adj_close"].iloc[i] / df["adj_close"].iloc[i - 1] - 1)
                        if chg > 0.25:
                            jumps += 1
            _check(f"{sym} 분할일 수정주가 연속성", jumps == 0,
                   f"분할 {len(sp)}건 중 수정종가 단절 {jumps}건")


# ── 5) 6차원 국면 특징 (target_engine 과 동일 정의) ──────────────────────────
def build_features(prices: dict[str, pd.DataFrame]) -> None:
    sys.path.insert(0, r"C:\stock\backend")
    import target_engine as te

    (ROOT / "features").mkdir(parents=True, exist_ok=True)
    dim_keys = ["trend_ema_gap_pct", "rsi14", "ret20d_std_pct",
                "vol_ratio_5_20", "pos_60d_pctile", "ret_20d_pct"]
    for sym in list(prices):
        df = prices[sym]
        # 분할 왜곡 없는 수정 시계열 기준 (지수는 close == adj 동일)
        closes = df["adj_close"].tolist()
        vols = df["volume"].fillna(0).tolist()
        rows = []
        for i in range(len(closes)):
            f = te._regime_features(closes, vols, i)
            if f is None:
                continue
            c = closes[i]
            run_max = max(closes[: i + 1])
            ma200 = sum(closes[i - 199: i + 1]) / 200 if i >= 199 else None
            row = {"date": df.index[i].strftime("%Y-%m-%d")}
            row.update(dict(zip(dim_keys, [round(v, 4) for v in f])))
            row["drawdown_pct"] = round((c / run_max - 1) * 100, 2)
            row["ma200_gap_pct"] = round((c / ma200 - 1) * 100, 2) if ma200 else None
            # 미래 수익 라벨 — 사후 분석/학습 전용 (미래 참조이므로 매칭 입력 금지)
            row["fwd_ret_20d_pct"] = (
                round((closes[i + 20] / c - 1) * 100, 2) if i + 20 < len(closes) else None)
            row["fwd_ret_60d_pct"] = (
                round((closes[i + 60] / c - 1) * 100, 2) if i + 60 < len(closes) else None)
            rows.append(row)
        name = INDICES.get(sym, sym)
        pd.DataFrame(rows).to_csv(ROOT / "features" / f"{name}_features.csv", index=False)
        print(f"  {sym}: 특징 {len(rows)}행")


# ── 6) SEC EDGAR 원본 10-K 보존 (1995~2003 접수분) ───────────────────────────
def fetch_edgar() -> None:
    saved = 0
    for sym, cik in CIKS.items():
        out_dir = ROOT / "edgar" / sym
        out_dir.mkdir(parents=True, exist_ok=True)
        r = httpx.get("https://www.sec.gov/cgi-bin/browse-edgar",
                      params={"action": "getcompany", "CIK": cik, "type": "10-K",
                              "dateb": "20040101", "owner": "include",
                              "count": "40", "output": "atom"},
                      headers=H_SEC, timeout=60, follow_redirects=True)
        if r.status_code != 200:
            report["warnings"].append(f"EDGAR {sym}: 목록 조회 실패 HTTP {r.status_code}")
            continue
        entries = re.findall(
            r"<accession-n?u?m?b?e?r?>([\d-]+)</accession-.*?>.*?"
            r"<filing-date>([\d-]+)</filing-date>.*?<filing-type>(10-K[^<]*)</filing-type>",
            r.text, re.S)
        if not entries:  # 태그 순서가 다른 경우 대비 — entry 단위 재파싱
            entries = []
            for ent in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
                acc = re.search(r"<accession-n\w*>([\d-]+)<", ent)
                fdt = re.search(r"<filing-date>([\d-]+)<", ent)
                ftp = re.search(r"<filing-type>(10-K[^<]*)<", ent)
                if acc and fdt and ftp:
                    entries.append((acc.group(1), fdt.group(1), ftp.group(1)))
        got = 0
        for acc, fdate, ftype in entries:
            if not ("1995" <= fdate[:4] <= "2003"):
                continue
            acc_nodash = acc.replace("-", "")
            url = (f"https://www.sec.gov/Archives/edgar/data/"
                   f"{int(cik)}/{acc_nodash}.txt")
            # 구형 경로 폴백: 일부 90년대 접수분은 평면 경로
            for u in (url, f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}.txt"):
                try:
                    fr = httpx.get(u, headers=H_SEC, timeout=120, follow_redirects=True)
                    if fr.status_code == 200 and len(fr.content) > 5000:
                        fn = out_dir / f"{fdate}_{ftype.replace('/', '-')}_{acc}.txt"
                        fn.write_bytes(fr.content)
                        got += 1
                        saved += 1
                        break
                except Exception:
                    continue
            time.sleep(0.15)
        print(f"  EDGAR {sym} (CIK {cik}): 10-K {got}건 저장")
        if got == 0:
            report["warnings"].append(f"EDGAR {sym}: 1995~2003 10-K 0건 — CIK 확인 필요")
    _check("EDGAR 10-K 원본 보존", saved >= 30, f"총 {saved}건 (5사 × 1995~2003 회계연도)")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    print("[1/6] 일봉 시세 (yfinance)")
    prices = fetch_prices()
    if not prices:
        raise RuntimeError("시세 다운로드 전부 실패 — 중단")
    # 이후 단계는 상호 독립 — 한 단계 실패가 전체를 막지 않게 하고 경고로 기록
    steps = [
        ("[2/6] FRED 공식 시계열 + 나스닥 교차검증", lambda: fetch_fred_and_verify(prices)),
        ("[3/6] 분할·배당 이력", fetch_actions),
        ("[4/6] 구조 무결성 검증", lambda: verify_structure(prices)),
        ("[5/6] 6차원 국면 특징 + 드로다운/라벨", lambda: build_features(prices)),
        ("[6/6] SEC EDGAR 원본 10-K", fetch_edgar),
    ]
    for title, fn in steps:
        print(title)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            report["warnings"].append(f"{title} 단계 실패: {type(exc).__name__}: {exc}")
            print(f"  [WARN] 단계 실패 — {type(exc).__name__}: {exc}")

    report["singleSourceSeries"] = ["nasdaq_100(^NDX)", "sp500(^GSPC)"] + STOCKS
    report["singleSourceNote"] = (
        "개별주 일별 시세의 독립 2차 소스(Stooq/WSJ/investing.com/macrotrends)는 "
        "전부 접근 차단되어 전구간 교차검증 불가 — 구조 무결성·분할 연속성·지수 "
        "교차검증(동일 공급망 신뢰도)·역사적 앵커 대조로 대체. 상세는 README 참조.")
    (ROOT / "verification_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    n_fail = sum(1 for c in report["checks"] if not c["passed"])
    print(f"\n완료 — 검증 {len(report['checks'])}건 중 실패 {n_fail}건, "
          f"경고 {len(report['warnings'])}건 → verification_report.json")


if __name__ == "__main__":
    main()
