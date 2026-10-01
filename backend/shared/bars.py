"""Candle helpers shared by both engines (pure)."""
from typing import Any

IST_OFFSET = 19800  # +05:30, fixed


def resample(bars: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """Combine 1-minute bars (sorted by time) into `minutes`-minute bars aligned to the IST clock.
    The result's `time` is the bucket START; `pcr`, when present, is the last one seen in the bucket."""
    if minutes <= 1:
        return [dict(b) for b in bars]
    size = minutes * 60
    out: list[dict[str, Any]] = []
    for bar in bars:
        start = bar["time"] + IST_OFFSET
        start = start - (start % size) - IST_OFFSET
        if out and out[-1]["time"] == start:
            last = out[-1]
            last["high"] = max(last["high"], bar["high"])
            last["low"] = min(last["low"], bar["low"])
            last["close"] = bar["close"]
            if "pcr" in bar:
                last["pcr"] = bar["pcr"]
        else:
            out.append({**bar, "time": start})
    return out
