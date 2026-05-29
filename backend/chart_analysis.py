"""chart_analysis.py

AI-powered chart analysis tool for Moon Stock.

Supports three data sources:
  1. yfinance  - fetch OHLCV by ticker symbol (KRX: '005930.KS', KOSDAQ: '035720.KQ', US: 'AAPL')
  2. CSV upload - TradingView-exported CSV (columns: time, open, high, low, close[, volume])
  3. raw JSON   - dict list with keys: time/date, open, high, low, close[, volume]

Flow:
  load_ohlcv() → compute_indicators() → build_prompt() → openai_analyze() → result dict
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_ohlcv_from_yfinance(
    symbol: str,
    *,
    period: str = "6mo",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance.

    For KRX (KOSPI) append '.KS', for KOSDAQ append '.KQ'.
    e.g. symbol='005930' → auto-tried as '005930.KS'
    """
    try:
        import yfinance as yf  # lazy import – optional dependency
    except ImportError as exc:
        raise ImportError("yfinance is not installed. Run: pip install yfinance") from exc

    ticker = symbol.strip()
    # Auto-suffix Korean 6-digit codes
    if ticker.isdigit() and len(ticker) == 6:
        ticker = f"{ticker}.KS"

    df: pd.DataFrame = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if df.empty and ticker.endswith(".KS"):
        # Retry as KOSDAQ
        ticker = ticker.replace(".KS", ".KQ")
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

    if df.empty:
        raise ValueError(f"No data returned for symbol '{symbol}' (tried ticker '{ticker}')")

    df = df.rename(columns=str.lower)
    df.index.name = "time"
    df = df.reset_index()
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    return df[["time", "open", "high", "low", "close", "volume"]].dropna()


def load_ohlcv_from_csv(content: str | bytes) -> pd.DataFrame:
    """Parse TradingView-exported CSV.

    Expected header (case-insensitive):
      time,open,high,low,close[,volume]
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")

    df = pd.read_csv(io.StringIO(content))
    df.columns = [c.strip().lower() for c in df.columns]

    # Accept 'date' as alias for 'time'
    if "date" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"date": "time"})

    required = {"time", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    else:
        df["volume"] = 0.0

    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close", "volume"]]


def load_ohlcv_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Load from a list of dicts (JSON body)."""
    df = pd.DataFrame(records)
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"date": "time"})
    return load_ohlcv_from_csv(df.to_csv(index=False))


# ---------------------------------------------------------------------------
# Technical indicators (pure pandas/numpy — no extra TA library required)
# ---------------------------------------------------------------------------

def _sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def _ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(series: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = _sma(series, n)
    std = series.rolling(n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    return upper, mid, lower


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def compute_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Compute key technical indicators and return a summary dict.

    The dict contains both series snapshots (last N values) and scalar summaries
    suitable for embedding in an LLM prompt.
    """
    close = df["close"]
    volume = df["volume"]

    sma5 = _sma(close, 5)
    sma20 = _sma(close, 20)
    sma60 = _sma(close, 60)
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    rsi14 = _rsi(close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    atr14 = _atr(df)
    vol_ma20 = volume.rolling(20).mean()

    def _last(s: pd.Series, n: int = 1) -> float | list[float]:
        vals = s.dropna().tail(n).round(4).tolist()
        return vals[0] if n == 1 else vals

    current_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else current_price
    change_pct = round((current_price - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    # Recent 20 OHLCV rows for the prompt
    recent_ohlcv = df.tail(20)[["time", "open", "high", "low", "close", "volume"]].copy()
    recent_ohlcv["time"] = recent_ohlcv["time"].astype(str)
    recent_rows = recent_ohlcv.to_dict(orient="records")

    return {
        "current_price": current_price,
        "change_pct": change_pct,
        "data_rows": len(df),
        "date_range": {
            "start": str(df["time"].iloc[0]),
            "end": str(df["time"].iloc[-1]),
        },
        "sma": {"5": _last(sma5), "20": _last(sma20), "60": _last(sma60)},
        "ema": {"12": _last(ema12), "26": _last(ema26)},
        "rsi_14": _last(rsi14),
        "macd": {
            "macd": _last(macd_line),
            "signal": _last(macd_signal),
            "histogram": _last(macd_hist),
        },
        "bollinger": {
            "upper": _last(bb_upper),
            "mid": _last(bb_mid),
            "lower": _last(bb_lower),
            "bandwidth": round((_last(bb_upper) - _last(bb_lower)) / (_last(bb_mid) or 1) * 100, 2),
            "pct_b": round((current_price - _last(bb_lower)) / ((_last(bb_upper) - _last(bb_lower)) or 1), 4),
        },
        "atr_14": _last(atr14),
        "volume": {
            "last": float(volume.iloc[-1]),
            "ma20": round(float(vol_ma20.iloc[-1]), 2) if not pd.isna(vol_ma20.iloc[-1]) else None,
            "ratio": round(float(volume.iloc[-1]) / float(vol_ma20.iloc[-1]), 2)
            if (not pd.isna(vol_ma20.iloc[-1]) and float(vol_ma20.iloc[-1]) > 0)
            else None,
        },
        "recent_ohlcv": recent_rows,
    }


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
당신은 전문 주식/자산 기술적 분석 AI입니다.
주어진 차트 데이터(OHLCV)와 기술적 지표를 바탕으로 한국어로 명확하고 실용적인 분석을 제공합니다.

분석 시 반드시 포함할 내용:
1. 현재 추세 (상승/하락/횡보) 및 강도
2. 주요 지지/저항 구간
3. RSI, MACD, 볼린저밴드 해석
4. 거래량 분석
5. 단기(1~5일) / 중기(1~4주) 전망
6. 매매 판단: 매수 / 매도 / 관망 중 하나 + 명확한 근거
7. 주요 리스크 요인

응답은 반드시 아래 JSON 형식으로만 반환하세요:
{
  "signal": "매수" | "매도" | "관망",
  "confidence": 0~100 (확신도 %),
  "trend": "상승" | "하락" | "횡보",
  "summary": "2~3문장 핵심 요약",
  "analysis": {
    "trend_detail": "추세 상세 설명",
    "support_resistance": "지지/저항 구간 설명",
    "rsi": "RSI 해석",
    "macd": "MACD 해석",
    "bollinger": "볼린저밴드 해석",
    "volume": "거래량 해석"
  },
  "outlook": {
    "short_term": "단기(1~5일) 전망",
    "mid_term": "중기(1~4주) 전망"
  },
  "risks": ["리스크1", "리스크2"],
  "entry_zone": "진입 가격대 (매수 시그널인 경우)",
  "stop_loss": "손절 기준",
  "target_price": "목표가 (매수 시그널인 경우)"
}
"""


def build_prompt(symbol: str, indicators: dict[str, Any]) -> str:
    ind = dict(indicators)
    recent = ind.pop("recent_ohlcv", [])
    return (
        f"종목: {symbol}\n\n"
        f"## 기술적 지표\n```json\n{json.dumps(ind, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 최근 20봉 OHLCV\n```json\n{json.dumps(recent, ensure_ascii=False, indent=2)}\n```\n\n"
        "위 데이터를 분석하여 지정된 JSON 형식으로만 응답해주세요."
    )


def openai_analyze(
    symbol: str,
    indicators: dict[str, Any],
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Call OpenAI Chat Completions API and parse the JSON response."""
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    prompt = build_prompt(symbol, indicators)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

    if resp.status_code >= 400:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"OpenAI API error {resp.status_code}: {err_body}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse OpenAI response as JSON: {exc}\nRaw: {content}") from exc

    return result


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def analyze_chart(
    *,
    symbol: str,
    openai_api_key: str,
    openai_model: str = "gpt-4o-mini",
    # Data source options (exactly one should be provided)
    yfinance_period: str | None = "6mo",
    yfinance_interval: str = "1d",
    csv_content: str | bytes | None = None,
    ohlcv_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """End-to-end: load data → compute indicators → AI analysis.

    Returns a dict with keys: symbol, indicators (summary), ai_result, analyzed_at.
    """
    # 1. Load OHLCV
    if csv_content is not None:
        df = load_ohlcv_from_csv(csv_content)
    elif ohlcv_records is not None:
        df = load_ohlcv_from_records(ohlcv_records)
    else:
        df = load_ohlcv_from_yfinance(
            symbol,
            period=yfinance_period or "6mo",
            interval=yfinance_interval,
        )

    if len(df) < 30:
        raise ValueError(f"Insufficient data: {len(df)} rows (minimum 30 required)")

    # 2. Indicators
    indicators = compute_indicators(df)

    # 3. AI analysis
    ai_result = openai_analyze(
        symbol,
        indicators,
        api_key=openai_api_key,
        model=openai_model,
    )

    return {
        "symbol": symbol,
        "indicators": {k: v for k, v in indicators.items() if k != "recent_ohlcv"},
        "ai_result": ai_result,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
