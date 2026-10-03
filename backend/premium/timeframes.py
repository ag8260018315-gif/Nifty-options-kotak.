"""Long timeframes (1 hour, 4 hour, 1 day, 1 week) built from finer candles. Pure functions.

Hour and 4-hour candles are anchored to the NSE open (09:15 IST): 09:15-10:15, 10:15-11:15 ... and 09:15-13:15, 13:15-15:30, with the
last one shorter. Daily candles start at IST midnight and weekly candles on Monday, matching how Upstox labels them.
"""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
IST_OFFSET = 19800
OPEN_SECONDS = 9 * 3600 + 15 * 60
DAY, WEEK = 1440, 10080
LONG_FRAMES = (60, 240, DAY, WEEK)


def _merge(into: dict[str, Any], bar: dict[str, Any]) -> None:
    into["high"], into["low"], into["close"] = max(into["high"], bar["high"]), min(into["low"], bar["low"]), bar["close"]
    into["volume"] = (into.get("volume") or 0) + (bar.get("volume") or 0)


def _new(start: int, bar: dict[str, Any]) -> dict[str, Any]:
    return {"time": start, "open": bar["open"], "high": bar["high"], "low": bar["low"], "close": bar["close"], "volume": bar.get("volume") or 0}


def session_bucket(epoch: int, minutes: int) -> int:
    """Start (epoch) of the `minutes`-wide bucket that holds `epoch`, counted from 09:15 IST of that day."""
    local = epoch + IST_OFFSET
    open_local = local - local % 86400 + OPEN_SECONDS
    k = max(0, (local - open_local) // (minutes * 60))
    return open_local + k * minutes * 60 - IST_OFFSET


def day_start(epoch: int) -> int:
    local = epoch + IST_OFFSET
    return local - local % 86400 - IST_OFFSET


def week_start(epoch: int) -> int:
    midnight = day_start(epoch)
    weekday = datetime.fromtimestamp(midnight + 3600, IST).weekday()  # Monday = 0
    return midnight - weekday * 86400


def regroup(bars: list[dict[str, Any]], start_of) -> list[dict[str, Any]]:
    """Combine bars (sorted by time) into buckets whose start is `start_of(time)`. The result's time is the bucket start."""
    out: list[dict[str, Any]] = []
    for bar in sorted(bars, key=lambda b: b["time"]):
        start = start_of(bar["time"])
        if out and out[-1]["time"] == start:
            _merge(out[-1], bar)
        else:
            out.append(_new(start, bar))
    return out


def to_daily(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return regroup(bars, day_start)


def to_weekly(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return regroup(daily, week_start)


def merge_by_time(base: list[dict[str, Any]], newer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union of two bar lists; where the same candle time exists in both, `newer` wins."""
    by_time = {b["time"]: b for b in base}
    by_time.update({b["time"]: b for b in newer})
    return [by_time[t] for t in sorted(by_time)]


def build_long_bars(minutes: int, fine: list[dict[str, Any]], daily: list[dict[str, Any]], today: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Candles for a long timeframe.
    fine   = intraday history (any size that divides the target: 30-minute or 1-minute bars), oldest first
    daily  = daily history (time = IST midnight)
    today  = today's live 1-minute candles (so the newest candle is current, and is drawn as still forming)"""
    if minutes in (60, 240):
        start_today = day_start(today[0]["time"]) if today else None
        history = [b for b in fine if start_today is None or b["time"] < start_today]
        return regroup(history + list(today), lambda t: session_bucket(t, minutes))
    if minutes not in (DAY, WEEK):
        raise ValueError("unsupported long timeframe")
    days = merge_by_time(daily, to_daily(today)) if today else list(daily)
    if not days and fine:
        days = to_daily(fine)
    return days if minutes == DAY else to_weekly(days)
