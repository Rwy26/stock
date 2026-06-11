"""yfinance 동작 스모크 테스트 (DB 쓰기 없음)."""
import yfinance as yf
for t in ["005930.KS", "011810.KS", "182400.KQ", "064350.KS", "099320.KQ"]:
    try:
        df = yf.download(t, start="2026-06-01", end="2026-06-13", progress=False, auto_adjust=True)
        if df is None or df.empty:
            print(f"{t}: EMPTY")
        else:
            last = df.tail(3)
            print(f"{t}: {len(df)} rows, last:")
            for dt, row in last.iterrows():
                c = row["Close"] if "Close" in row else row.iloc[3]
                v = row["Volume"] if "Volume" in row else row.iloc[4]
                print(f"   {dt.date()} close={float(c):.0f} vol={int(v)}")
    except Exception as e:
        print(f"{t}: ERROR {e}")
