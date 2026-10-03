"""The stock signal engine: Bullish / Bearish / Neutral with a transparent setup, built from the analysis of CLOSED candles.

Rules, not predictions:
  * the bias comes from the analysis score (trend, RSI, MACD, VWAP, volume, nearby levels) plus recent candlestick patterns
    (+-8 each, at most +-12), thresholds +-35;
  * a signal is produced only when the data is fresh enough: LIVE (market open, ticks under 15 s old) or HISTORICAL (market
    closed, computed from the last session and labelled so). DELAYED or missing data gives no signal;
  * "confidence" is the signal strength 0-100. It is NOT a probability of winning; the tested win rate is shown separately;
  * every signal carries its generation time, the candle it is based on, and the conditions that would invalidate it.
"""
from datetime import datetime, timezone
from typing import Any

from premium.patterns import BEAR, BULL, detect_recent
from premium.setup import build_setup

BUY_AT, SELL_AT = 35, -35
PATTERN_WEIGHT, PATTERN_CAP, PATTERN_WINDOW = 8, 12, 3
DISCLAIMER = "Informational analysis of live prices. A setup is a description of risk and levels, not a prediction or advice."


def _last(values: list[Any] | None) -> float | None:
    for v in reversed(values or []):
        if v is not None:
            return float(v)
    return None


def _volatility(atr_pct: float | None, interval: int) -> str:
    if atr_pct is None:
        return "Unknown"
    low, high = (0.15, 0.4) if interval < 60 else (0.3, 0.8) if interval < 1440 else (1.0, 2.5) if interval < 10080 else (2.5, 5.5) if interval < 43200 else (5.0, 10.0)
    return "Low" if atr_pct < low else "High" if atr_pct > high else "Normal"


def _momentum(rsi: float | None, hist: float | None) -> tuple[int, str]:
    if rsi is None:
        return 0, "Unknown"
    value = max(-100, min(100, round((rsi - 50) * 2.5)))
    if hist is not None and ((hist > 0) != (value > 0)):
        value = round(value * 0.5)  # RSI and MACD disagree: halve it
    label = "Strong bullish" if value >= 50 else "Bullish" if value >= 15 else "Strong bearish" if value <= -50 else "Bearish" if value <= -15 else "Neutral"
    return value, label


def data_status(market: dict[str, Any] | None) -> dict[str, Any]:
    state = (market or {}).get("state", "NO_FEED")
    msg = (market or {}).get("message", "")
    age = (market or {}).get("tick_age_seconds")
    status = {"OPEN": "LIVE", "CLOSED": "HISTORICAL", "DELAYED": "DELAYED"}.get(state, "UNAVAILABLE")
    text = {"LIVE": "Live prices, fresh ticks.", "HISTORICAL": "Market closed: based on the last completed session, not live prices.",
            "DELAYED": msg or "Prices are delayed, so no signal is produced.", "UNAVAILABLE": msg or "No live price feed."}[status]
    return {"status": status, "tick_age_seconds": age, "message": text}


def stock_signal(analysis: dict[str, Any], market: dict[str, Any] | None, interval: int, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    data = data_status(market)
    base: dict[str, Any] = {"generated_at": now.isoformat(), "data": data, "interval": interval, "disclaimer": DISCLAIMER, "bias": "Unavailable", "action": "NONE",
                            "score": 0, "confidence": {"value": 0, "meaning": "Signal strength, not a probability of winning."}, "reasons": [], "patterns": [],
                            "setup": None, "invalidation": [], "trend_strength": None, "momentum": None, "volatility": None, "as_of_candle": None}
    sig = analysis.get("signal") or {}
    if data["status"] in ("DELAYED", "UNAVAILABLE"):
        base["reasons"] = [data["message"]]
        return base
    if sig.get("action") in (None, "BUILDING"):
        base["reasons"] = list(sig.get("reasons") or ["Not enough candles yet."])
        return base
    candles = analysis.get("candles") or []
    width = interval * 60
    closed = [c for c in candles if c.get("end", c["time"] + width) <= (now.timestamp() if data["status"] == "LIVE" else 1e18)]
    patterns = detect_recent(closed, 30)
    recent_cut = closed[-PATTERN_WINDOW]["time"] if len(closed) >= PATTERN_WINDOW else 0
    recent = [p for p in patterns if p["time"] >= recent_cut]
    adj = sum(PATTERN_WEIGHT if p["direction"] == BULL else -PATTERN_WEIGHT if p["direction"] == BEAR else 0 for p in recent)
    adj = max(-PATTERN_CAP, min(PATTERN_CAP, adj))
    score = max(-100, min(100, int(sig.get("score", 0)) + adj))
    bias = "Bullish" if score >= BUY_AT else "Bearish" if score <= SELL_AT else "Neutral"
    reasons = list(sig.get("reasons") or [])
    for p in recent:
        if p["direction"] in (BULL, BEAR):
            reasons.append(f"Pattern: {p['name']} ({p['direction']}) on a recent candle ({'+' if p['direction'] == BULL else '-'}{PATTERN_WEIGHT})")
    series = analysis.get("series") or {}
    atr = analysis.get("atr")
    price = sig.get("price")
    atr_pct = round(atr / price * 100, 2) if atr and price else None
    rsi_v, hist_v = sig.get("rsi"), _last(series.get("macd_hist"))
    ef, es = _last(series.get("ema_fast")), _last(series.get("ema_slow"))
    trend_strength = min(100, round(abs(ef - es) / atr * 60)) if ef is not None and es is not None and atr else None
    mom_value, mom_label = _momentum(rsi_v, hist_v)
    levels = analysis.get("levels") or {}
    setup = None
    f_n, s_n = (analysis.get("ema_periods") or [9, 20])
    inval: list[str] = []
    if bias in ("Bullish", "Bearish"):
        direction = "LONG" if bias == "Bullish" else "SHORT"
        setup = build_setup(direction, float(price), atr, levels.get("support") or [], levels.get("resistance") or []) if price else None
        if setup:
            inval.append(f"A close {'below' if direction == 'LONG' else 'above'} the stop at {setup['stop']} (the setup is then wrong).")
        inval.append(f"EMA{f_n} crossing {'below' if direction == 'LONG' else 'above'} EMA{s_n}.")
        if direction == "LONG" and levels.get("nearest_support"):
            inval.append(f"A close below support {levels['nearest_support']}.")
        if direction == "SHORT" and levels.get("nearest_resistance"):
            inval.append(f"A close above resistance {levels['nearest_resistance']}.")
        inval.append("The setup is stale after about 10 candles of this size, or once price reaches target 1 or the stop.")
    else:
        inval.append(f"A close above resistance {levels.get('nearest_resistance')} or below support {levels.get('nearest_support')} with rising volume would change the picture.")
    base.update(bias=bias, action={"Bullish": "BUY", "Bearish": "SELL"}.get(bias, "NONE"), score=score,
                confidence={"value": min(100, abs(score)), "meaning": "Signal strength, not a probability of winning. See the tested win rate separately."},
                reasons=reasons, patterns=recent, setup=setup, invalidation=inval, trend_strength=trend_strength,
                momentum={"value": mom_value, "label": mom_label}, volatility={"atr_pct": atr_pct, "label": _volatility(atr_pct, interval)},
                as_of_candle=sig.get("as_of_candle"))
    return base
