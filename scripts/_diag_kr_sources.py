"""임시 진단: yfinance 차단 여부 + KR 대체 데이터 소스(pykrx/FDR) 검증. 실행 후 삭제."""
import warnings
warnings.filterwarnings("ignore")

KOSPI_ETF = "091160"   # KODEX 반도체
ETF_KS = KOSPI_ETF + ".KS"

print("=== 1) yfinance 재시도 (^KS11, 091160.KS, 3mo) ===")
try:
    import yfinance as yf
    for sym in ("^KS11", ETF_KS):
        try:
            df = yf.download(sym, period="3mo", interval="1d", progress=False, auto_adjust=True)
            n = 0 if df is None else len(df)
            last = None if (df is None or df.empty) else round(float(df["Close"].iloc[-1].item()), 2)
            print(f"  yf {sym}: rows={n} last={last}")
        except Exception as e:
            print(f"  yf {sym}: ERR {type(e).__name__} {str(e)[:80]}")
except Exception as e:
    print("  yfinance import 실패:", e)

print("\n=== 2) pykrx (KOSPI 지수 1001 + ETF 091160) ===")
try:
    from pykrx import stock
    # 최근 ~3개월
    import datetime as dt
    end = dt.date(2026, 6, 24)
    start = end - dt.timedelta(days=95)
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    try:
        idx = stock.get_index_ohlcv(s, e, "1001")  # 코스피
        print(f"  pykrx KOSPI(1001): rows={len(idx)} last_close={idx['종가'].iloc[-1] if len(idx) else None} "
              f"({idx.index[-1].date() if len(idx) else '-'})")
    except Exception as e2:
        print("  pykrx index ERR:", type(e2).__name__, str(e2)[:100])
    try:
        etf = stock.get_etf_ohlcv_by_date(s, e, KOSPI_ETF)
        print(f"  pykrx ETF({KOSPI_ETF}): rows={len(etf)} last_close={etf['종가'].iloc[-1] if len(etf) else None} "
              f"cols={list(etf.columns)[:5]}")
    except Exception as e3:
        print("  pykrx etf ERR:", type(e3).__name__, str(e3)[:100])
except Exception as e:
    print("  pykrx import 실패:", e)

print("\n=== 3) FinanceDataReader (KS11 + 091160) ===")
try:
    import FinanceDataReader as fdr
    for sym in ("KS11", KOSPI_ETF):
        try:
            df = fdr.DataReader(sym, "2026-03-21", "2026-06-24")
            n = len(df)
            last = round(float(df["Close"].iloc[-1]), 2) if n else None
            print(f"  fdr {sym}: rows={n} last_close={last} cols={list(df.columns)[:6]}")
        except Exception as e4:
            print(f"  fdr {sym}: ERR {type(e4).__name__} {str(e4)[:80]}")
except Exception as e:
    print("  FinanceDataReader import 실패:", e)
