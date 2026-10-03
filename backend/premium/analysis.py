"""Pure analysis of candles: indicators, support/resistance, volume, trend and a transparent signal.

Look-ahead rule: the signal uses CLOSED candles only (the forming candle is drawn on the chart but ignored by the signal).
This is informational analysis of past and current prices. It is not investment advice and not a prediction.
"""
from typing import Any

from shared.indicators import atr, bollinger, ema, macd, rsi

MIN_BARS = 35  # MACD(26) + signal(9): fewer closed candles and the indicators are not meaningful
SPIKE_RATIO = 2.0
BUY_AT, SELL_AT = 35, -35
DISCLAIMER = "Informational analysis of live prices. Not investment advice. Indicators can be wrong."


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def resample_ohlcv(bars: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """1-minute bars (sorted) -> `minutes`-minute bars aligned to the IST clock. Volume is summed."""
    if minutes <= 1:
        return [dict(b) for b in bars]
    size = minutes * 60
    out: list[dict[str, Any]] = []
    for bar in bars:
        start = bar["time"] + 19800
        start = start - (start % size) - 19800
        if out and out[-1]["time"] == start:
            last = out[-1]
            last["high"], last["low"], last["close"] = max(last["high"], bar["high"]), min(last["low"], bar["low"]), bar["close"]
            last["volume"] = (last.get("volume") or 0) + (bar.get("volume") or 0)
        else:
            out.append({"time": start, "open": bar["open"], "high": bar["high"], "low": bar["low"], "close": bar["close"], "volume": bar.get("volume") or 0})
    return out


def pivots(prev: dict[str, float] | None) -> dict[str, float] | None:
    """Classic floor-trader pivots from the previous session's high, low and close."""
    if not prev:
        return None
    h, l, c = prev["high"], prev["low"], prev["close"]
    pp = (h + l + c) / 3
    return {
        "pp": pp, "r1": 2 * pp - l, "r2": pp + (h - l), "r3": h + 2 * (pp - l),
        "s1": 2 * pp - h, "s2": pp - (h - l), "s3": l - 2 * (h - pp),
    }


def _swings(bars: list[dict[str, Any]], width: int = 3) -> tuple[list[float], list[float]]:
    highs, lows = [], []
    for i in range(width, len(bars) - width):
        window = bars[i - width : i + width + 1]
        if bars[i]["high"] == max(b["high"] for b in window):
            highs.append(bars[i]["high"])
        if bars[i]["low"] == min(b["low"] for b in window):
            lows.append(bars[i]["low"])
    return highs, lows


def _cluster(levels: list[float], tolerance_pct: float = 0.15) -> list[float]:
    """Merge levels closer than tolerance_pct of price into their average."""
    out: list[list[float]] = []
    for level in sorted(levels):
        if out and abs(level - out[-1][-1]) / out[-1][-1] * 100 <= tolerance_pct:
            out[-1].append(level)
        else:
            out.append([level])
    return [sum(group) / len(group) for group in out]


def support_resistance(closed: list[dict[str, Any]], last: float, prev: dict[str, float] | None, day_high: float | None, day_low: float | None) -> dict[str, Any]:
    piv = pivots(prev)
    sh, sl = _swings(closed)
    candidates = list(sh) + list(sl)
    if piv:
        candidates += list(piv.values())
    if prev:
        candidates += [prev["high"], prev["low"]]
    if day_high:
        candidates.append(day_high)
    if day_low:
        candidates.append(day_low)
    levels = _cluster([c for c in candidates if c and c > 0])
    resistance = sorted([l for l in levels if l > last])[:4]
    support = sorted([l for l in levels if l < last], reverse=True)[:4]
    return {
        "pivots": {k: _r(v) for k, v in piv.items()} if piv else None,
        "resistance": [_r(v) for v in resistance], "support": [_r(v) for v in support],
        "nearest_resistance": _r(resistance[0]) if resistance else None, "nearest_support": _r(support[0]) if support else None,
        "prev_day": {k: _r(v) for k, v in prev.items()} if prev else None,
        "day_high": _r(day_high), "day_low": _r(day_low),
    }


def volume_analysis(closed: list[dict[str, Any]], has_volume: bool) -> dict[str, Any]:
    if not has_volume or not any((b.get("volume") or 0) > 0 for b in closed):
        return {"available": False, "note": "No traded volume is published for this instrument (indices carry none)."}
    vols = [b.get("volume") or 0 for b in closed]
    last = vols[-1]
    base = vols[-21:-1]
    avg = sum(base) / len(base) if base else 0
    rel = last / avg if avg else None
    recent, before = vols[-5:], vols[-10:-5]
    trend = "rising" if before and sum(recent) > sum(before) * 1.15 else "falling" if before and sum(recent) < sum(before) * 0.85 else "flat"
    window = closed[-20:]
    up = sum((b.get("volume") or 0) for b in window if b["close"] >= b["open"])
    down = sum((b.get("volume") or 0) for b in window if b["close"] < b["open"])
    return {
        "available": True, "last": last, "average_20": _r(avg, 0), "relative": _r(rel), "spike": bool(rel and rel >= SPIKE_RATIO),
        "trend": trend, "buying_pressure_pct": _r(up / (up + down) * 100, 1) if (up + down) else None,
    }


def trend_label(closes: list[float], ema_fast: list[float], ema_slow: list[float]) -> dict[str, Any]:
    if len(closes) < 10:
        return {"label": "BUILDING", "basis": []}
    up = ema_fast[-1] > ema_slow[-1] and closes[-1] > ema_slow[-1] and ema_slow[-1] > ema_slow[-6]
    down = ema_fast[-1] < ema_slow[-1] and closes[-1] < ema_slow[-1] and ema_slow[-1] < ema_slow[-6]
    label = "UPTREND" if up else "DOWNTREND" if down else "SIDEWAYS"
    return {"label": label, "basis": [f"EMA9 {'above' if ema_fast[-1] > ema_slow[-1] else 'below'} EMA21", f"price {'above' if closes[-1] > ema_slow[-1] else 'below'} EMA21"]}


def _near(price: float, level: float | None, pct: float = 0.25) -> bool:
    return level is not None and price > 0 and abs(price - level) / price * 100 <= pct


def score_signal(last: float, rsi_now: float | None, macd_hist: list[float], ema_fast: float, ema_slow: float, vwap: float | None,
                 vol: dict[str, Any], levels: dict[str, Any], last_bar_up: bool) -> tuple[int, list[str]]:
    score, why = 0, []
    if ema_fast > ema_slow and last > ema_slow:
        score += 30; why.append("Trend: EMA9 above EMA21 and price above EMA21 (+30)")
    elif ema_fast < ema_slow and last < ema_slow:
        score -= 30; why.append("Trend: EMA9 below EMA21 and price below EMA21 (-30)")
    if rsi_now is not None:
        if 55 <= rsi_now < 70:
            score += 20; why.append(f"Momentum: RSI {rsi_now:.0f} is bullish (+20)")
        elif rsi_now >= 70:
            score += 5; why.append(f"Momentum: RSI {rsi_now:.0f} is overbought, so only +5")
        elif 30 < rsi_now <= 45:
            score -= 20; why.append(f"Momentum: RSI {rsi_now:.0f} is bearish (-20)")
        elif rsi_now <= 30:
            score -= 5; why.append(f"Momentum: RSI {rsi_now:.0f} is oversold, so only -5")
    if len(macd_hist) >= 2:
        if macd_hist[-1] > 0 and macd_hist[-1] >= macd_hist[-2]:
            score += 20; why.append("MACD histogram positive and rising (+20)")
        elif macd_hist[-1] < 0 and macd_hist[-1] <= macd_hist[-2]:
            score -= 20; why.append("MACD histogram negative and falling (-20)")
    if vwap:
        score += 15 if last > vwap else -15
        why.append(f"Price {'above' if last > vwap else 'below'} VWAP ({'+' if last > vwap else '-'}15)")
    if vol.get("available") and vol.get("spike"):
        delta = 15 if last_bar_up else -15
        score += delta; why.append(f"Volume spike {vol['relative']}x on a {'rising' if last_bar_up else 'falling'} candle ({'+' if delta > 0 else ''}{delta})")
    if score > 0 and _near(last, levels.get("nearest_resistance")):
        score -= 10; why.append(f"Price is near resistance {levels['nearest_resistance']} (-10)")
    if score < 0 and _near(last, levels.get("nearest_support")):
        score += 10; why.append(f"Price is near support {levels['nearest_support']} (+10)")
    return max(-100, min(100, score)), why


def _frame(minutes: int) -> str:
    return {60: "1-hour", 240: "4-hour", 1440: "daily", 10080: "weekly"}.get(minutes, f"{minutes}-minute")


def _tail(out: dict[str, Any], tail: int | None) -> dict[str, Any]:
    """Keep only the most recent `tail` candles in the output. Indicators were computed on the full history first, so they are warmed up."""
    if tail and out.get("candles"):
        out["candles"] = out["candles"][-tail:]
        if out.get("series"):
            out["series"] = {k: v[-tail:] for k, v in out["series"].items()}
    return out


def analyse(bars: list[dict[str, Any]], interval: int, prev_day: dict[str, float] | None, now_epoch: float, has_volume: bool,
            day_high: float | None = None, day_low: float | None = None, include_series: bool = True, tail: int | None = None) -> dict[str, Any]:
    """`bars` already resampled to `interval` minutes (oldest first), the last one possibly still forming."""
    width = interval * 60
    closed = [b for b in bars if b["time"] + width <= now_epoch]
    out: dict[str, Any] = {"interval": interval, "bars_total": len(bars), "bars_closed": len(closed), "bars_required": MIN_BARS, "disclaimer": DISCLAIMER}
    closes = [b["close"] for b in bars]
    if bars and include_series:
        h, l, c = [b["high"] for b in bars], [b["low"] for b in bars], closes
        e9, e21 = ema(c, 9), ema(c, 21)
        r14 = rsi(c, 14)
        m_line, m_sig, m_hist = macd(c)
        bb_mid, bb_up, bb_lo = bollinger(c)
        a14 = atr(h, l, c)
        vw: list[float | None] = [None] * len(bars)
        if has_volume:
            pv = vol_sum = 0.0
            for i, b in enumerate(bars):
                v = b.get("volume") or 0
                pv += (b["high"] + b["low"] + b["close"]) / 3 * v
                vol_sum += v
                vw[i] = pv / vol_sum if vol_sum else None
        out["series"] = {
            "time": [b["time"] for b in bars], "ema9": [_r(x) for x in e9], "ema21": [_r(x) for x in e21], "rsi": [_r(x) for x in r14],
            "macd": [_r(x, 3) for x in m_line], "macd_signal": [_r(x, 3) for x in m_sig], "macd_hist": [_r(x, 3) for x in m_hist],
            "bb_upper": [_r(x) for x in bb_up], "bb_mid": [_r(x) for x in bb_mid], "bb_lower": [_r(x) for x in bb_lo], "vwap": [_r(x) for x in vw],
        }
        out["atr"] = _r(a14[-1])
    out["candles"] = [] if not include_series else [{"time": b["time"], "open": _r(b["open"]), "high": _r(b["high"]), "low": _r(b["low"]), "close": _r(b["close"]), "volume": b.get("volume") or 0} for b in bars]
    if len(closed) < MIN_BARS:
        out.update(levels=support_resistance(closed, closed[-1]["close"] if closed else 0, prev_day, day_high, day_low) if closed else None,
                   volume=volume_analysis(closed, has_volume) if closed else {"available": False}, trend={"label": "BUILDING", "basis": []},
                   signal={"action": "BUILDING", "score": 0, "reasons": [f"Needs {MIN_BARS} closed {_frame(interval)} candles; has {len(closed)}. " + ("Long timeframes need stored history: run the history import." if interval >= 60 else "Candles come from live ticks since the server started.")]})
        return _tail(out, tail)
    cc = [b["close"] for b in closed]
    f, s = ema(cc, 9), ema(cc, 21)
    r = rsi(cc, 14)[-1]
    _, _, hist = macd(cc)
    last = cc[-1]
    vwap_closed = None
    if has_volume:
        tot = sum(b.get("volume") or 0 for b in closed)
        vwap_closed = sum((b["high"] + b["low"] + b["close"]) / 3 * (b.get("volume") or 0) for b in closed) / tot if tot else None
    vol = volume_analysis(closed, has_volume)
    levels = support_resistance(closed, last, prev_day, day_high, day_low)
    score, why = score_signal(last, r, hist, f[-1], s[-1], vwap_closed, vol, levels, closed[-1]["close"] >= closed[-1]["open"])
    action = "BUY" if score >= BUY_AT else "SELL" if score <= SELL_AT else "NEUTRAL"
    strength = None if action == "NEUTRAL" else ("STRONG" if abs(score) >= 70 else "MODERATE" if abs(score) >= 50 else "WEAK")
    out["vwap"] = _r(vwap_closed)
    out.update(levels=levels, volume=vol, trend=trend_label(cc, f, s),
               signal={"action": action, "score": score, "strength": strength, "reasons": why, "rsi": _r(r, 1), "price": _r(last), "as_of_candle": closed[-1]["time"],
                       "nearest_support": levels["nearest_support"], "nearest_resistance": levels["nearest_resistance"]})
    return _tail(out, tail)
