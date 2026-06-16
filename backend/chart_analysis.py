"""chart_analysis.py

AI-powered chart analysis tool for Moon Stock.

Supports three data sources:
  1. yfinance  - fetch OHLCV by ticker symbol (KRX: '005930.KS', KOSDAQ: '035720.KQ', US: 'AAPL')
  2. CSV upload - TradingView-exported CSV (columns: time, open, high, low, close[, volume])
  3. raw JSON   - dict list with keys: time/date, open, high, low, close[, volume]
  4. images    - TradingView chart screenshot(s) analyzed via OpenAI Vision

Flow (image):
  image bytes → base64 encode → build_vision_prompt() → openai_vision_analyze() → result dict
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
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

    # yfinance ≥1.x returns MultiIndex columns for single tickers too.
    # Flatten: ('Close', '005930.KS') → 'close'
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
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


def _mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Money Flow Index — 거래량 가중 RSI (OHLCV로 재계산, 신뢰값)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    mf = tp * df["volume"]
    pos = mf.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = mf.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    mfr = pos / neg.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))


def _vwap(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """롤링 VWAP(n) — 거래량 가중 평균가."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).rolling(n).sum()
    vv = df["volume"].rolling(n).sum().replace(0, np.nan)
    return pv / vv


def _ichimoku(df: pd.DataFrame) -> dict[str, pd.Series]:
    """일목균형표 전환선/기준선/선행스팬 (현재 상태 판정용, 미래 시프트 없음)."""
    high, low = df["high"], df["low"]
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (high.rolling(52).max() + low.rolling(52).min()) / 2
    return {"tenkan": tenkan, "kijun": kijun, "span_a": span_a, "span_b": span_b}


def _rsi_divergence(close: pd.Series, rsi: pd.Series, lookback: int = 60, window: int = 3) -> dict:
    """최근 구간 가격-RSI 정규 다이버전스 탐지 (결정론)."""
    c = close.tail(lookback).reset_index(drop=True)
    r = rsi.tail(lookback).reset_index(drop=True)
    n = len(c)
    if n < window * 2 + 5 or r.isna().all():
        return {"type": "none"}
    lows, highs = [], []
    for i in range(window, n - window):
        seg = c[i - window:i + window + 1]
        if c[i] == seg.min():
            lows.append(i)
        if c[i] == seg.max():
            highs.append(i)
    bull = bear = None
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if c[b] < c[a] and r[b] > r[a]:
            bull = (b, f"가격 저점 하락({round(c[a])}→{round(c[b])}) vs RSI 상승({round(r[a],1)}→{round(r[b],1)})")
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if c[b] > c[a] and r[b] < r[a]:
            bear = (b, f"가격 고점 상승({round(c[a])}→{round(c[b])}) vs RSI 하락({round(r[a],1)}→{round(r[b],1)})")
    if bull and (not bear or bull[0] >= bear[0]):
        return {"type": "bullish", "detail": bull[1]}
    if bear:
        return {"type": "bearish", "detail": bear[1]}
    return {"type": "none"}


def _obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — 종가 방향으로 부호화한 거래량 누적 (수급 추적)."""
    sign = np.sign(df["close"].diff().fillna(0.0))
    return (sign * df["volume"]).cumsum()


def _adx(df: pd.DataFrame, n: int = 14):
    """Wilder ADX/DMI — 추세 강도(ADX) + 방향성(+DI/-DI)."""
    high, low, close = df["high"], df["low"], df["close"]
    up, dn = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False).mean()
    return adx, plus_di, minus_di


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
    sma120 = _sma(close, 120)
    sma200 = _sma(close, 200)
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    rsi14 = _rsi(close, 14)
    macd_line, macd_signal, macd_hist = _macd(close)
    bb_upper, bb_mid, bb_lower = _bollinger(close)
    atr14 = _atr(df)
    vol_ma20 = volume.rolling(20).mean()
    mfi14 = _mfi(df, 14)
    vwap20 = _vwap(df, 20)
    ichi = _ichimoku(df)
    rsi_div = _rsi_divergence(close, rsi14)
    obv = _obv(df)
    adx, plus_di, minus_di = _adx(df)

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
        "sma": {"5": _last(sma5), "20": _last(sma20), "60": _last(sma60),
                "120": _last(sma120), "200": _last(sma200)},
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
        "mfi_14": _last(mfi14),
        "vwap_20": _last(vwap20),
        "ichimoku": {
            "tenkan": _last(ichi["tenkan"]),
            "kijun": _last(ichi["kijun"]),
            "price_vs_kijun": "위" if current_price >= _last(ichi["kijun"]) else "아래",
            "cloud": ("구름 위" if current_price > max(_last(ichi["span_a"]), _last(ichi["span_b"]))
                      else "구름 아래" if current_price < min(_last(ichi["span_a"]), _last(ichi["span_b"]))
                      else "구름 안"),
        },
        "rsi_divergence": rsi_div,
        "obv": {
            "direction_20bar": ("상승" if obv.iloc[-1] > obv.iloc[-min(20, len(obv))] else "하락"),
            "confirms_price": bool((obv.iloc[-1] > obv.iloc[-min(20, len(obv))]) ==
                                   (current_price > float(close.iloc[-min(20, len(close))]))),
        },
        "adx_14": {
            "adx": _last(adx),
            "plus_di": _last(plus_di),
            "minus_di": _last(minus_di),
            "regime": ("추세" if (_last(adx) or 0) >= 25 else "약한추세" if (_last(adx) or 0) >= 20 else "횡보"),
            "direction": ("상승우위" if (_last(plus_di) or 0) >= (_last(minus_di) or 0) else "하락우위"),
        },
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
당신은 ICT(Inner Circle Trader, 스마트머니 컨셉) + 수급 분석 + 기업가치 통합 분석 전문 AI입니다.
주어진 차트 데이터(OHLCV)와 기술적 지표를 바탕으로 한국어로 명확하고 실용적인 분석을 제공합니다.

━━ 분석 기준 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1] ICT 스마트머니 분석
  - Order Block (OB): 기관/세력의 매집/분산 구간 식별
  - FVG (Fair Value Gap) / Imbalance 구간 파악
  - Liquidity Sweep: 고점/저점 청산 패턴 (BSL/SSL)
  - Market Structure: BOS(Break of Structure) / CHoCH(Change of Character)
  - Premium / Discount Zone (50% 기준 고평가/저평가 구간)

[2] 수급 분석
  - 거래량 급증 구간 및 세력 개입 흔적
  - 이동평균선 배열 (20/60/120/200일선)
  - 볼린저밴드 / RSI / MACD / MFI(거래량가중) / VWAP / 일목균형표 수급 시그널
  - RSI 다이버전스(rsi_divergence)는 추세 약화/반전의 강한 단서로 해석
  - 제공된 '멀티 타임프레임 합류'·'참고 신호(CVD·ZONE)'가 있으면 함께 고려하되,
    참고 신호는 외부 미검증값이므로 보조 근거로만 쓰고 핵심 수치로 단정하지 말 것

[3] 기업가치 기반 현재가 평가
  - 현재가가 저평가 / 적정 / 고평가인지 판단
  - 섹터 트렌드 및 미래 가치 기대감 반영

[4] 최근 시장 재료 (AI가 아는 최신 정보 기준)
  - 해당 종목 및 섹터의 상승 재료 (뉴스/공시/정책/실적)
  - 판단에 필요한 추가 데이터가 있다면 사용자에게 명시적으로 요청

━━ 응답 규칙 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 추상적 표현 금지. 모든 핵심 수치는 반드시 숫자로 명시
- 중요한 가격(목표가/손절가/진입가)은 계산 후 재검토하여 오류 없이 기재
- 판단 근거가 불충분하면 "data_needed" 필드에 필요한 정보를 명시

반드시 아래 JSON 형식으로만 반환하세요:
{
  "signal": "매수" | "매도" | "관망",
  "confidence": 0~100,
  "rise_probability": 0~100,
  "fall_probability": 0~100,
  "valuation": "저평가" | "적정" | "고평가",
  "trend": "강한상승" | "상승" | "횡보" | "하락" | "강한하락",
  "summary": "3~5문장 핵심 요약 (숫자 포함)",
  "ict_analysis": {
    "order_block": "OB 구간 (가격대 명시)",
    "fvg": "FVG/Imbalance 구간",
    "liquidity": "청산 유동성 위치",
    "market_structure": "BOS/CHoCH 상태",
    "zone": "Premium | Discount | Equilibrium"
  },
  "technical": {
    "trend_detail": "추세 상세",
    "ma_alignment": "이동평균선 배열",
    "support_zones": ["지지구간1", "지지구간2"],
    "resistance_zones": ["저항구간1", "저항구간2"],
    "rsi": "RSI 수치 및 해석",
    "macd": "MACD 상태",
    "bollinger": "볼린저밴드 해석",
    "volume": "거래량 분석"
  },
  "catalysts": {
    "news_materials": "알려진 상승 재료 (뉴스/공시/정책)",
    "sector_expectation": "섹터 미래 가치 기대감",
    "risk_factors": ["리스크1", "리스크2"]
  },
  "targets": {
    "entry_zone": "추천 진입 구간 (숫자)",
    "target_1": "1차 목표가 (숫자)",
    "target_2": "2차 목표가 (숫자)",
    "stop_loss": "손절 마지노선 (이 가격 이탈 시 즉시 손절, 숫자)",
    "risk_reward": "리스크:리워드 비율 (예: 1:2.5)",
    "basis": "목표가/손절가 산출 근거"
  },
  "outlook": {
    "short_term": "단기(1~5일) 전망",
    "mid_term": "중기(1~4주) 전망"
  },
  "data_needed": "판단에 추가로 필요한 정보 (없으면 null)",
  "directive_response": "사용자가 [사용자 지시]를 준 경우 그 지시 수행 결과/답변 요약 (지시 없으면 null)"
}
"""


def _clean_json_response(text: str) -> str:
    """Gemini/OpenAI sometimes wraps JSON in markdown fences. Strip them."""
    t = text.strip()
    # ```json ... ``` or ``` ... ```
    if t.startswith("```"):
        lines = t.splitlines()
        # drop first line (``` or ```json) and last line (```)
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        t = "\n".join(inner).strip()
    return t


def build_prompt(symbol: str, indicators: dict[str, Any], extra_note: str | None = None) -> str:
    ind = dict(indicators)
    recent = ind.pop("recent_ohlcv", [])
    note = f"\n{extra_note}\n" if extra_note else ""
    return (
        f"종목: {symbol}\n\n"
        f"## 기술적 지표\n```json\n{json.dumps(ind, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 최근 20봉 OHLCV\n```json\n{json.dumps(recent, ensure_ascii=False, indent=2)}\n```\n"
        f"{note}\n"
        "위 데이터를 분석하여 지정된 JSON 형식으로만 응답해주세요."
    )


def openai_analyze(
    symbol: str,
    indicators: dict[str, Any],
    *,
    api_key: str,
    model: str = "gpt-4o-mini",
    base_url: str = "https://api.openai.com/v1",
    timeout_seconds: float = 60.0,
    extra_note: str | None = None,
) -> dict[str, Any]:
    """Call OpenAI-compatible Chat Completions API (OpenAI / Groq) and parse the JSON response."""
    if not api_key:
        raise ValueError("API key is not configured")

    prompt = build_prompt(symbol, indicators, extra_note)

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

    endpoint = f"{base_url.rstrip('/')}/chat/completions"

    try:
        resp = httpx.post(endpoint, json=payload, headers=headers, timeout=timeout_seconds)
    except Exception as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc

    if resp.status_code >= 400:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"API error {resp.status_code}: {err_body}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    try:
        result = json.loads(_clean_json_response(content))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse response as JSON: {exc}\nRaw (first 500): {content[:500]}") from exc

    return result


def gemini_analyze(
    symbol: str,
    indicators: dict[str, Any],
    *,
    api_key: str,
    model: str | None = None,
    timeout_seconds: float = 60.0,
    extra_note: str | None = None,
) -> dict[str, Any]:
    """Call Google Gemini API (free tier) and parse the JSON response."""
    if model is None:
        from settings import settings as _s
        model = _s.gemini_model
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")

    prompt = build_prompt(symbol, indicators, extra_note)

    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model}:generateContent?key={api_key}"
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3,
        },
    }

    try:
        resp = httpx.post(url, json=payload, timeout=timeout_seconds)
    except Exception as exc:
        raise RuntimeError(f"Gemini API request failed: {exc}") from exc

    if resp.status_code >= 400:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        raise RuntimeError(f"Gemini API error {resp.status_code}: {err_body}")

    data = resp.json()
    try:
        candidate = data["candidates"][0]
        finish = candidate.get("finishReason", "")
        if finish not in ("", "STOP", None):
            raise RuntimeError(f"Gemini 응답 조기 종료: finishReason={finish}. 프롬프트가 너무 길거나 토큰 제한 초과")
        text = candidate["content"]["parts"][0]["text"]
        result = json.loads(_clean_json_response(text))
    except RuntimeError:
        raise
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to parse Gemini response: {exc}\nRaw (first 500): {str(data)[:500]}") from exc

    return result


def test_ai_connection(
    *,
    api_key: str,
    model: str,
    provider: str = "gemini",
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Minimal connectivity test: sends a tiny prompt and expects a JSON reply.

    Returns {"ok": True, "provider": ..., "model": ..., "latency_ms": ...}
    Raises RuntimeError with a user-friendly message on failure.
    """
    import time

    test_prompt = 'Respond with only valid JSON: {"ok": true, "test": "connection"}'
    t0 = time.monotonic()

    if provider == "gemini":
        url = (
            f"https://generativelanguage.googleapis.com/v1beta"
            f"/models/{model}:generateContent?key={api_key}"
        )
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": test_prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        try:
            resp = httpx.post(url, json=payload, timeout=timeout_seconds)
        except Exception as exc:
            raise RuntimeError(f"Gemini 네트워크 연결 실패: {exc}") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"Gemini API 오류 {resp.status_code}: {detail}")
        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            json.loads(_clean_json_response(text))  # validate JSON
        except Exception as exc:
            raise RuntimeError(f"Gemini 응답 파싱 실패: {exc}\nRaw: {str(data)[:200]}") from exc
    else:
        base_url_t = "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": test_prompt}],
            "temperature": 0,
            "max_tokens": 64,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        try:
            resp = httpx.post(f"{base_url_t}/chat/completions", json=payload, headers=headers, timeout=timeout_seconds)
        except Exception as exc:
            raise RuntimeError(f"{provider} 네트워크 연결 실패: {exc}") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"{provider} API 오류 {resp.status_code}: {detail}")

    latency_ms = round((time.monotonic() - t0) * 1000)
    return {"ok": True, "provider": provider, "model": model, "latency_ms": latency_ms}


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def analyze_chart(
    *,
    symbol: str,
    api_key: str,
    model: str,
    provider: str = "openai",  # "openai" | "gemini" | "groq"
    # Data source options (exactly one should be provided)
    yfinance_period: str | None = "6mo",
    yfinance_interval: str = "1d",
    csv_content: str | bytes | None = None,
    ohlcv_records: list[dict[str, Any]] | None = None,
    extra_note: str | None = None,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """End-to-end: load data → compute indicators → AI analysis.

    Returns a dict with keys: symbol, indicators (summary), ai_result, analyzed_at.
    provider: "openai" | "gemini" (완전 무료) | "groq" (무료)
    extra_note: 프롬프트에 덧붙일 추가 분석 노트 (예: 변곡점 집중 분석).
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

    # 3. AI analysis – dispatch to selected provider
    if provider == "gemini":
        ai_result = gemini_analyze(symbol, indicators, api_key=api_key, model=model,
                                   extra_note=extra_note, timeout_seconds=timeout_seconds)
    elif provider == "groq":
        ai_result = openai_analyze(
            symbol, indicators,
            api_key=api_key, model=model,
            base_url="https://api.groq.com/openai/v1",
            extra_note=extra_note, timeout_seconds=timeout_seconds,
        )
    else:
        ai_result = openai_analyze(symbol, indicators, api_key=api_key, model=model,
                                   extra_note=extra_note, timeout_seconds=timeout_seconds)

    return {
        "symbol": symbol,
        "indicators": {k: v for k, v in indicators.items() if k != "recent_ohlcv"},
        "ai_result": ai_result,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Image-based analysis (TradingView screenshot → OpenAI Vision)
# ---------------------------------------------------------------------------

_VISION_SYSTEM_PROMPT = """\
당신은 ICT(Inner Circle Trader, 스마트머니 컨셉) + 수급 분석 + 기업가치 통합 분석 전문 AI입니다.
첨부된 TradingView 차트 스크린샷(일봉/4시간봉/1시간봉 등 여러 타임프레임)을 보고
한국어로 명확하고 숫자 중심의 종합 분석을 수행합니다.

━━ 분석 기준 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[1] ICT 스마트머니 분석
  - Order Block (OB): 기관/세력의 매집/분산 구간 식별 (가격대 명시)
  - FVG (Fair Value Gap) / Imbalance 구간 파악
  - Liquidity Sweep: BSL/SSL 고점/저점 청산 패턴
  - Market Structure: BOS(Break of Structure) / CHoCH(Change of Character)
  - Premium / Discount Zone (50% 기준)

[2] 수급 분석
  - 거래량 급증 구간 및 세력 개입 흔적
  - 이동평균선 배열 상태 (정배열/역배열/수렴)
  - 핵심 매물대(Volume Profile 기반)

[3] 기업가치 기반 현재가 평가
  - 현재가가 저평가 / 적정 / 고평가인지 판단
  - 섹터 트렌드 및 미래 가치 기대감 (AI, 반도체, 방산, 바이오 등)

[4] 최근 시장 재료
  - 해당 종목·섹터의 상승 재료 (최신 뉴스/공시/정책/실적 기반)
  - 판단에 필요한 추가 데이터가 있다면 "data_needed"에 명시

━━ 응답 규칙 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- 추상적 표현 금지. 모든 핵심 수치는 반드시 숫자로 명시
- 목표가/손절가/진입가 계산 후 반드시 재검토하여 오류 없이 기재
- 판단 근거가 불충분하면 data_needed에 요청 항목 명시

반드시 아래 JSON만 반환하세요 (설명 텍스트 없음):
{
  "symbol": "종목명만 (차트에 보이는 한글 종목명. 절대 종목코드를 붙이거나 괄호로 코드를 병기하지 말 것. 차트에 종목명이 안 보이면 null)",
  "code_in_chart": "차트 화면에 '종목코드 6자리'가 명확히 보이면 그 숫자만, 안 보이면 null (추정·생성 절대 금지)",
  "timeframes": ["확인된 타임프레임 목록"],
  "current_price": "현재가 (숫자)",
  "signal": "매수" | "매도" | "관망",
  "confidence": 0~100,
  "rise_probability": 0~100,
  "fall_probability": 0~100,
  "valuation": "저평가" | "적정" | "고평가",
  "trend": "강한상승" | "상승" | "횡보" | "하락" | "강한하락",
  "summary": "3~5문장 핵심 요약 (숫자 포함)",
  "ict_analysis": {
    "order_block": "OB 구간 (가격대 명시)",
    "fvg": "FVG/Imbalance 구간",
    "liquidity": "청산 유동성 위치",
    "market_structure": "BOS/CHoCH 상태",
    "zone": "Premium | Discount | Equilibrium"
  },
  "technical": {
    "trend_detail": "추세 상세",
    "ma_alignment": "이동평균선 배열 상태",
    "support_zones": ["지지구간1 (숫자)", "지지구간2 (숫자)"],
    "resistance_zones": ["저항구간1 (숫자)", "저항구간2 (숫자)"],
    "rsi": "RSI 수치 및 해석",
    "macd": "MACD 상태",
    "bollinger": "볼린저밴드 해석",
    "volume": "거래량 및 수급 분석",
    "patterns": "주요 캔들/차트 패턴"
  },
  "catalysts": {
    "news_materials": "알려진 상승 재료 (뉴스/공시/정책)",
    "sector_expectation": "섹터 미래 가치 기대감",
    "risk_factors": ["리스크1", "리스크2"]
  },
  "targets": {
    "entry_zone": "추천 진입 구간 (숫자)",
    "target_1": "1차 목표가 (숫자)",
    "target_2": "2차 목표가 (숫자)",
    "stop_loss": "손절 마지노선 — 이 가격 이탈 시 즉시 손절 (숫자)",
    "risk_reward": "리스크:리워드 비율 (예: 1:2.5)",
    "basis": "목표가/손절가 산출 근거"
  },
  "outlook": {
    "short_term": "단기(1~5일) 전망",
    "mid_term": "중기(1~4주) 전망"
  },
  "data_needed": "판단에 추가로 필요한 정보 (없으면 null)",
  "directive_response": "사용자가 [사용자 지시]를 준 경우 그 지시 수행 결과/답변 요약 (지시 없으면 null)"
}
"""


def _image_bytes_to_data_url(image_bytes: bytes, filename: str = "") -> str:
    """Convert image bytes to a base64 data URL for OpenAI Vision API."""
    ext = ""
    if filename:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/png")

    # Auto-detect from magic bytes if no extension hint
    if not ext:
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif image_bytes[:2] in (b"\xff\xd8", b"\xff\xe0", b"\xff\xe1"):
            mime = "image/jpeg"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            mime = "image/webp"

    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def analyze_chart_images(
    *,
    symbol: str,
    image_files: list[tuple[str, bytes]],   # [(filename, bytes), ...]
    api_key: str,
    model: str = "gpt-4o",
    provider: str = "openai",  # "openai" | "gemini" | "groq"
    extra_context: str | None = None,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """Analyze TradingView chart screenshots using Vision API.

    Args:
        symbol: 종목명 or 코드 (식별용, AI가 차트에서 직접 읽기도 함)
        image_files: list of (filename, bytes) tuples – 여러 타임프레임 가능
        api_key: API key for the selected provider
        model: model name
        provider: "openai" | "gemini" (무료) | "groq"
        extra_context: 추가 컨텍스트 (예: 현재가, 보유여부 등)
        timeout_seconds: HTTP 타임아웃

    Returns:
        dict with keys: symbol, ai_result, analyzed_at, images_count
    """
    if not api_key:
        raise ValueError("API key is not configured")
    if not image_files:
        raise ValueError("최소 1개 이상의 차트 이미지가 필요합니다")
    if len(image_files) > 6:
        raise ValueError("이미지는 최대 6개까지 업로드 가능합니다")

    # Build content list: text + images (OpenAI Vision format)
    content: list[dict[str, Any]] = []

    timeframe_labels = ["일봉", "4시간봉", "1시간봉", "15분봉", "5분봉", "주봉"]
    intro_text = (
        f"참고 식별자(검증 안 됨): {symbol}\n"
        "※ 이 식별자는 파일명에서 추출됐을 수 있어 틀릴 수 있다. 종목명은 반드시 차트 이미지에서 직접 읽어라. "
        "이 식별자를 종목코드로 단정하거나 종목명에 병기하지 마라.\n"
        f"첨부된 {len(image_files)}개의 TradingView 차트를 분석해주세요."
    )
    if extra_context:
        # 추가 정보는 단순 참고가 아니라 '사용자 지시'로 취급한다 —
        # 예: "섹터 구분해서 리포트에 반영", "보유 중이니 매도 타이밍 위주로",
        # "이미지가 서로 다른 종목이면 각각 식별해서 알려줘" 등 자연어 명령을 수행한다.
        intro_text += (
            f"\n\n[사용자 지시 — 반드시 수행]\n{extra_context}\n"
            "위 지시를 분석에 우선 반영하라. 섹터 분류를 요청하면 company_analysis.sector에 채우고, "
            "특정 관점(보유/신규/매도 등)을 지정하면 그 관점으로 summary와 targets를 작성하라. "
            "지시 수행 결과나 사용자에게 전할 답을 directive_response 필드에 한국어로 요약하라."
        )
    intro_text += "\n지정된 JSON 형식으로만 응답하세요."

    content.append({"type": "text", "text": intro_text})

    for idx, (filename, img_bytes) in enumerate(image_files):
        label = timeframe_labels[idx] if idx < len(timeframe_labels) else f"차트{idx+1}"
        data_url = _image_bytes_to_data_url(img_bytes, filename)
        content.append({"type": "text", "text": f"[{label} 차트]"})
        content.append({
            "type": "image_url",
            "image_url": {"url": data_url, "detail": "high"},
        })

    if provider == "gemini":
        # Gemini Vision API – images as inlineData
        gurl = (
            f"https://generativelanguage.googleapis.com/v1beta"
            f"/models/{model}:generateContent?key={api_key}"
        )
        g_parts: list[dict[str, Any]] = [{"text": intro_text}]
        for idx2, (fname2, img_bytes2) in enumerate(image_files):
            label2 = timeframe_labels[idx2] if idx2 < len(timeframe_labels) else f"\ucc28\ud2b82{idx2 + 1}"
            data_url2 = _image_bytes_to_data_url(img_bytes2, fname2)
            mime2 = data_url2.split(";")[0].split("data:")[1]
            b64_2 = data_url2.split(";base64,")[1]
            g_parts.append({"text": f"[{label2} \ucc28\ud2b8]"})
            g_parts.append({"inlineData": {"mimeType": mime2, "data": b64_2}})
        g_payload = {
            "contents": [{"role": "user", "parts": g_parts}],
            "systemInstruction": {"parts": [{"text": _VISION_SYSTEM_PROMPT}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.3,
            },
        }
        try:
            resp = httpx.post(gurl, json=g_payload, timeout=timeout_seconds)
        except Exception as exc:
            raise RuntimeError(f"Gemini Vision API request failed: {exc}") from exc
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            raise RuntimeError(f"Gemini Vision API error {resp.status_code}: {err_body}")
        data = resp.json()
        try:
            candidate = data["candidates"][0]
            finish = candidate.get("finishReason", "")
            if finish not in ("", "STOP", None):
                raise RuntimeError(f"Gemini Vision 응답 조기 종료: finishReason={finish}. 프롬프트가 너무 길거나 토큰 제한 초과")
            raw_content = candidate["content"]["parts"][0]["text"]
            ai_result = json.loads(_clean_json_response(raw_content))
        except RuntimeError:
            raise
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to parse Gemini Vision response: {exc}\nRaw (first 500): {str(data)[:500]}") from exc
    else:
        # OpenAI / Groq Vision (OpenAI-compatible)
        base_url_v = "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
        oa_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                f"{base_url_v}/chat/completions",
                json=oa_payload,
                headers=headers,
                timeout=timeout_seconds,
            )
        except Exception as exc:
            raise RuntimeError(f"Vision API request failed: {exc}") from exc
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text
            raise RuntimeError(f"Vision API error {resp.status_code}: {err_body}")
        data = resp.json()
        raw_content = data["choices"][0]["message"]["content"]
        try:
            ai_result = json.loads(_clean_json_response(raw_content))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse response as JSON: {exc}\nRaw (first 500): {raw_content[:500]}") from exc

    return {
        "symbol": symbol,
        "images_count": len(image_files),
        "ai_result": ai_result,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Multi-stock: 이미지가 서로 다른 종목이면 그룹별로 순차 분석 (지시문 트리거)
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
첨부된 차트/데이터 이미지들이 각각 어느 '종목'에 관한 것인지 식별하라.
같은 종목의 다른 타임프레임/데이터 이미지는 하나의 그룹으로 묶는다.
시황·지수·시장 전체 데이터처럼 특정 종목이 아닌 이미지는 stock을 "공통"으로 둔다.
반드시 아래 JSON만 반환:
{"groups": [{"stock": "종목명(차트에서 읽은 값)", "code": "6자리코드 또는 null", "images": [0-기반 이미지 인덱스 배열]}]}
"""


def classify_images_by_stock(
    *,
    image_files: list[tuple[str, bytes]],
    api_key: str,
    model: str,
    provider: str,
    timeout_seconds: float = 60.0,
) -> list[dict[str, Any]]:
    """1회 비전 호출로 이미지를 종목별 그룹으로 분류. 실패 시 전체를 한 그룹으로."""
    fallback = [{"stock": "", "code": None, "images": list(range(len(image_files)))}]
    if len(image_files) <= 1:
        return fallback

    parts_intro = (
        _CLASSIFY_PROMPT
        + f"\n이미지 수: {len(image_files)} (인덱스 0~{len(image_files) - 1})"
    )
    try:
        if provider == "gemini":
            gurl = (
                f"https://generativelanguage.googleapis.com/v1beta"
                f"/models/{model}:generateContent?key={api_key}"
            )
            g_parts: list[dict[str, Any]] = [{"text": parts_intro}]
            for idx, (fname, img) in enumerate(image_files):
                durl = _image_bytes_to_data_url(img, fname)
                g_parts.append({"text": f"[이미지 {idx}]"})
                g_parts.append({"inlineData": {
                    "mimeType": durl.split(";")[0].split("data:")[1],
                    "data": durl.split(";base64,")[1],
                }})
            payload = {
                "contents": [{"role": "user", "parts": g_parts}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
            }
            resp = httpx.post(gurl, json=payload, timeout=timeout_seconds)
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            base = "https://api.groq.com/openai/v1" if provider == "groq" else "https://api.openai.com/v1"
            content: list[dict[str, Any]] = [{"type": "text", "text": parts_intro}]
            for idx, (fname, img) in enumerate(image_files):
                content.append({"type": "text", "text": f"[이미지 {idx}]"})
                content.append({"type": "image_url",
                                "image_url": {"url": _image_bytes_to_data_url(img, fname), "detail": "low"}})
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            resp = httpx.post(f"{base}/chat/completions", json=payload,
                              headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout_seconds)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
        groups = json.loads(_clean_json_response(raw)).get("groups") or []
        # 유효성: 인덱스 범위 보정
        clean = []
        for grp in groups:
            idxs = [i for i in (grp.get("images") or []) if isinstance(i, int) and 0 <= i < len(image_files)]
            if idxs:
                clean.append({"stock": grp.get("stock") or "", "code": grp.get("code"), "images": idxs})
        return clean or fallback
    except Exception:
        return fallback


def analyze_chart_images_multi(
    *,
    symbol: str,
    image_files: list[tuple[str, bytes]],
    api_key: str,
    model: str = "gpt-4o",
    provider: str = "openai",
    extra_context: str | None = None,
    timeout_seconds: float = 90.0,
) -> dict[str, Any]:
    """이미지를 종목별로 분류 후 그룹마다 순차 분석. 그룹이 1개면 단일 분석과 동일.

    Returns: {"multi": bool, "results": [analyze_chart_images() 결과, ...], "groups": [...]}
    """
    groups = classify_images_by_stock(
        image_files=image_files, api_key=api_key, model=model,
        provider=provider, timeout_seconds=timeout_seconds,
    )
    # 단일 종목(또는 분류 실패)이면 다종목 처리 불필요
    real = [g for g in groups if (g.get("stock") or "").strip() and (g.get("stock") != "공통")]
    if len(real) <= 1:
        single = analyze_chart_images(
            symbol=symbol, image_files=image_files, api_key=api_key,
            model=model, provider=provider, extra_context=extra_context,
            timeout_seconds=timeout_seconds,
        )
        return {"multi": False, "results": [single], "groups": groups}

    # 공통(시황) 이미지는 각 종목 그룹에 맥락으로 동봉
    common_idxs = [i for g in groups if (g.get("stock") == "공통") for i in g["images"]]
    results = []
    for g in real:
        idxs = list(dict.fromkeys(g["images"] + common_idxs))
        sub_imgs = [image_files[i] for i in idxs]
        sym = (g.get("code") or g.get("stock") or symbol).strip()
        try:
            res = analyze_chart_images(
                symbol=sym, image_files=sub_imgs, api_key=api_key,
                model=model, provider=provider, extra_context=extra_context,
                timeout_seconds=timeout_seconds,
            )
            results.append(res)
        except Exception as exc:  # noqa: BLE001
            results.append({"symbol": sym, "error": str(exc), "ai_result": None,
                            "analyzed_at": datetime.now(timezone.utc).isoformat()})
    return {"multi": True, "results": results, "groups": groups}
