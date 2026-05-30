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
    base_url: str = "https://api.openai.com/v1",
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Call OpenAI-compatible Chat Completions API (OpenAI / Groq) and parse the JSON response."""
    if not api_key:
        raise ValueError("API key is not configured")

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
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse response as JSON: {exc}\nRaw: {content}") from exc

    return result


def gemini_analyze(
    symbol: str,
    indicators: dict[str, Any],
    *,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Call Google Gemini API (free tier) and parse the JSON response."""
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured")

    prompt = build_prompt(symbol, indicators)

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
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to parse Gemini response: {exc}\nRaw: {data}") from exc

    return result


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
) -> dict[str, Any]:
    """End-to-end: load data → compute indicators → AI analysis.

    Returns a dict with keys: symbol, indicators (summary), ai_result, analyzed_at.
    provider: "openai" | "gemini" (완전 무료) | "groq" (무료)
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
        ai_result = gemini_analyze(symbol, indicators, api_key=api_key, model=model)
    elif provider == "groq":
        ai_result = openai_analyze(
            symbol, indicators,
            api_key=api_key, model=model,
            base_url="https://api.groq.com/openai/v1",
        )
    else:
        ai_result = openai_analyze(symbol, indicators, api_key=api_key, model=model)

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
당신은 전문 주식/자산 트레이딩 분석 AI입니다.
첨부된 TradingView 차트 스크린샷(일봉/4시간봉/1시간봉 등 여러 타임프레임)을 보고
아래 5가지 항목을 반드시 포함하는 종합 분석을 한국어로 수행합니다.

── 분석 항목 ──────────────────────────────────────
1. 기업·종목 기본 분석
   - 차트에 표시된 종목명·코드·거래소 확인
   - 사업 특성 및 현재 가격 수준 평가

2. 기술적 분석 (Technical Analysis)
   - 현재 추세 (상승/하락/횡보) 및 강도
   - 이동평균선 배열 (정배열/역배열/수렴)
   - RSI·MACD·볼린저밴드·기타 보조지표 해석
   - 주요 캔들 패턴 (장대양봉·십자성·이브닝스타 등)
   - 지지/저항 구간 (정확한 가격대)

3. 상승 이유 분석 (섹터·업계·뉴스)
   - 차트의 급등 구간·거래량 폭발 이유 추론
   - 관련 섹터·산업 트렌드 (AI, 반도체, 전장, 2차전지 등)
   - 예상되는 촉매(뉴스/이슈/실적)

4. 목표가 추론
   - 피보나치 확장/되돌림 기반 목표가
   - 기술적 패턴 완성 목표가
   - 1차 / 2차 / 3차 목표가 (가격 명시)

5. 수급 분석 및 손절가
   - Volume Profile·거래량 분포로 핵심 매물대 파악
   - 손절 기준가 (스윙/단기 구분)
   - 리스크/리워드 비율

── 응답 형식 ──────────────────────────────────────
반드시 아래 JSON만 반환하세요 (설명 텍스트 없음):
{
  "symbol": "종목명 (차트에서 읽은 값)",
  "timeframes": ["확인된 타임프레임 목록"],
  "current_price": "현재가 (차트에서 읽은 값)",
  "signal": "매수" | "매도" | "관망",
  "confidence": 0~100,
  "trend": "강한상승" | "상승" | "횡보" | "하락" | "강한하락",
  "summary": "3~5문장 핵심 요약",
  "company_analysis": {
    "sector": "섹터/산업군",
    "key_products": "핵심 제품/사업",
    "current_position": "현재 차트상 포지션 평가"
  },
  "technical": {
    "trend_detail": "추세 상세",
    "ma_alignment": "이동평균선 배열 상태",
    "support_zones": ["지지구간1", "지지구간2"],
    "resistance_zones": ["저항구간1", "저항구간2"],
    "rsi": "RSI 해석",
    "macd": "MACD 해석",
    "bollinger": "볼린저밴드 해석",
    "volume": "거래량 분석",
    "patterns": "주요 캔들/차트 패턴"
  },
  "rise_reason": {
    "catalyst": "상승 촉매 추론",
    "sector_trend": "섹터 트렌드",
    "news_factors": ["예상 뉴스/이슈 1", "예상 뉴스/이슈 2"]
  },
  "targets": {
    "target_1": "1차 목표가",
    "target_2": "2차 목표가",
    "target_3": "3차 목표가",
    "basis": "목표가 산출 근거"
  },
  "supply_demand": {
    "key_volume_zone": "핵심 거래량 집중 구간",
    "stop_loss_swing": "스윙 손절가",
    "stop_loss_short": "단기 손절가",
    "risk_reward": "리스크/리워드 비율",
    "entry_zone": "진입 추천 구간"
  },
  "risks": ["리스크1", "리스크2", "리스크3"],
  "outlook": {
    "short_term": "단기(1~5일) 전망",
    "mid_term": "중기(1~4주) 전망"
  }
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
    intro_text = f"종목: {symbol}\n첨부된 {len(image_files)}개의 TradingView 차트를 분석해주세요."
    if extra_context:
        intro_text += f"\n추가 정보: {extra_context}"
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
            raw_content = data["candidates"][0]["content"]["parts"][0]["text"]
            ai_result = json.loads(raw_content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Failed to parse Gemini Vision response: {exc}\nRaw: {data}") from exc
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
            ai_result = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Failed to parse response as JSON: {exc}\nRaw: {raw_content[:500]}") from exc

    return {
        "symbol": symbol,
        "images_count": len(image_files),
        "ai_result": ai_result,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
