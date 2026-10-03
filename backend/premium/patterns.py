"""Candlestick patterns on CLOSED candles. Pure. Each pattern names the candle it completes on (its time), a direction, and a plain
explanation. Patterns are context for a signal, never a signal by themselves."""
from typing import Any

BULL, BEAR, NEUTRAL = "bullish", "bearish", "neutral"


def _parts(b: dict[str, Any]) -> tuple[float, float, float, float]:
    body = abs(b["close"] - b["open"])
    rng = b["high"] - b["low"]
    return body, rng, b["high"] - max(b["open"], b["close"]), min(b["open"], b["close"]) - b["low"]


def _bull(b: dict[str, Any]) -> bool:
    return b["close"] > b["open"]


def _bear(b: dict[str, Any]) -> bool:
    return b["close"] < b["open"]


def _found(name: str, direction: str, bar: dict[str, Any], text: str) -> dict[str, Any]:
    return {"name": name, "direction": direction, "time": bar["time"], "explanation": text}


def detect_at(bars: list[dict[str, Any]], i: int) -> list[dict[str, Any]]:
    """Patterns completing on bar i, using only bars[: i + 1]."""
    b = bars[i]
    body, rng, upper, lower = _parts(b)
    if rng <= 0:
        return []
    out: list[dict[str, Any]] = []
    down_before = i >= 3 and bars[i - 1]["close"] < bars[i - 3]["close"]
    up_before = i >= 3 and bars[i - 1]["close"] > bars[i - 3]["close"]
    if body <= 0.1 * rng:
        out.append(_found("Doji", NEUTRAL, b, "Open and close are almost equal: buyers and sellers balanced, so the prior move may be pausing."))
    elif body >= 0.9 * rng:
        out.append(_found("Marubozu", BULL if _bull(b) else BEAR, b, "A full-bodied candle with almost no wicks: one side controlled the whole period."))
    if body > 0 and lower >= 2 * body and upper <= max(0.3 * body, 0.1 * rng) and down_before:
        out.append(_found("Hammer", BULL, b, "A long lower wick after a fall: sellers pushed down but buyers took the price back up."))
    if body > 0 and upper >= 2 * body and lower <= max(0.3 * body, 0.1 * rng) and up_before:
        out.append(_found("Shooting star", BEAR, b, "A long upper wick after a rise: buyers pushed up but sellers took the price back down."))
    if i >= 1:
        p = bars[i - 1]
        pbody = abs(p["close"] - p["open"])
        if _bear(p) and _bull(b) and b["open"] <= p["close"] and b["close"] >= p["open"] and body > pbody:
            out.append(_found("Bullish engulfing", BULL, b, "A rising candle fully covers the previous falling one: buyers overpowered sellers."))
        if _bull(p) and _bear(b) and b["open"] >= p["close"] and b["close"] <= p["open"] and body > pbody:
            out.append(_found("Bearish engulfing", BEAR, b, "A falling candle fully covers the previous rising one: sellers overpowered buyers."))
    if i >= 2:
        a, m = bars[i - 2], bars[i - 1]
        abody, mbody = abs(a["close"] - a["open"]), abs(m["close"] - m["open"])
        if _bear(a) and mbody <= 0.3 * abody and _bull(b) and b["close"] > (a["open"] + a["close"]) / 2 and abody > 0:
            out.append(_found("Morning star", BULL, b, "A fall, a small indecisive candle, then a strong rise above the midpoint of the first candle."))
        if _bull(a) and mbody <= 0.3 * abody and _bear(b) and b["close"] < (a["open"] + a["close"]) / 2 and abody > 0:
            out.append(_found("Evening star", BEAR, b, "A rise, a small indecisive candle, then a strong fall below the midpoint of the first candle."))
        if _bull(a) and _bull(m) and _bull(b) and a["close"] < m["close"] < b["close"] and m["open"] > a["open"] and b["open"] > m["open"]:
            out.append(_found("Three white soldiers", BULL, b, "Three rising candles in a row, each closing higher than the last."))
        if _bear(a) and _bear(m) and _bear(b) and a["close"] > m["close"] > b["close"] and m["open"] < a["open"] and b["open"] < m["open"]:
            out.append(_found("Three black crows", BEAR, b, "Three falling candles in a row, each closing lower than the last."))
    return out


def detect_recent(bars: list[dict[str, Any]], lookback: int = 30) -> list[dict[str, Any]]:
    """Patterns on the last `lookback` closed candles, oldest first."""
    found: list[dict[str, Any]] = []
    for i in range(max(0, len(bars) - lookback), len(bars)):
        found.extend(detect_at(bars, i))
    return found
