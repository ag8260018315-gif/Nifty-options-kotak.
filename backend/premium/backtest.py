"""Historical test of the breakout watchlist rule (premium.breakout) on stored 1-minute stock candles.

It replays each session minute by minute exactly as the live list sees it: only candles that had CLOSED at the evaluation
moment, yesterday's high/low/close for pivots, and the same 5-minute-else-1-minute choice as the live list. The first moment in
a session at which a stock would qualify for the watchlist is the signal; what happens afterwards is read only from LATER candles
and never fed back into the rule.

Success (default, adjustable): after the signal, a candle CLOSES above the resistance level AND price reaches +target% from the
entry, within `horizon_minutes`, without first touching -stop% from the entry. If one candle spans both the stop and the target,
the stop counts first (conservative). Everything else is a failure (stop hit or no follow-through).
"""
import math
from dataclasses import asdict, dataclass
from typing import Any

from premium.analysis import MIN_BARS, analyse, resample_ohlcv
from premium.breakout import breakout_setup

MIN_SETUPS_TO_VALIDATE = 200
MIN_SESSIONS_TO_VALIDATE = 40
BANDS = [(0, 50), (50, 65), (65, 80), (80, 101)]


@dataclass(frozen=True)
class Rule:
    target_pct: float = 1.0
    stop_pct: float = 0.5
    horizon_minutes: int = 30
    eval_step_minutes: int = 15

    def describe(self) -> str:
        return (f"Success = a candle closes above the resistance level and price reaches +{self.target_pct}% from the signal price within "
                f"{self.horizon_minutes} minutes, without first falling {self.stop_pct}%. A candle touching both counts as a stop.")


def session_levels(bars: list[dict[str, Any]]) -> dict[str, float] | None:
    return {"high": max(b["high"] for b in bars), "low": min(b["low"] for b in bars), "close": bars[-1]["close"]} if bars else None


def outcome(entry: float, resistance: float, future: list[dict[str, Any]], rule: Rule) -> tuple[str, float]:
    """(SUCCESS | STOP | TIMEOUT, best gain % seen)."""
    target, stop = entry * (1 + rule.target_pct / 100), entry * (1 - rule.stop_pct / 100)
    confirmed, best = False, 0.0
    for bar in future:
        if bar["low"] <= stop:
            return "STOP", best
        best = max(best, (bar["high"] - entry) / entry * 100)
        confirmed = confirmed or bar["close"] > resistance
        if confirmed and bar["high"] >= target:
            return "SUCCESS", best
    return "TIMEOUT", best


def first_setup(bars: list[dict[str, Any]], prev: dict[str, float] | None, rule: Rule) -> dict[str, Any] | None:
    """The first moment in this session the stock would have been on the watchlist, and what followed."""
    n = len(bars)
    for i in range(MIN_BARS - 1, n - 1, rule.eval_step_minutes):
        known = bars[: i + 1]
        now = bars[i]["time"] + 60  # the evaluation moment: bar i has just closed
        hi, lo = max(b["high"] for b in known), min(b["low"] for b in known)
        five = analyse(resample_ohlcv(known, 5), 5, prev, now, True, hi, lo, False)
        chosen = five if five["bars_closed"] >= MIN_BARS else analyse(known, 1, prev, now, True, hi, lo, False)
        setup = breakout_setup(chosen)
        if not setup:
            continue
        entry = bars[i]["close"]
        future = bars[i + 1 : i + 1 + rule.horizon_minutes]
        result, best = outcome(entry, setup["resistance"], future, rule)
        return {"time": now, "entry": round(entry, 2), "score": setup["score"], "distance_pct": setup["distance_pct"], "resistance": setup["resistance"],
                "relative_volume": setup["relative_volume"], "result": result, "best_gain_pct": round(best, 2), "bars_after": len(future)}
    return None


def run(symbols: dict[str, list[tuple[str, list[dict[str, Any]]]]], rule: Rule) -> list[dict[str, Any]]:
    """`symbols`: symbol -> [(trading_day, 1-minute bars)] oldest first. Returns one record per qualifying session."""
    records: list[dict[str, Any]] = []
    for symbol, days in symbols.items():
        prev = None
        for day, bars in days:
            if len(bars) > MIN_BARS + rule.horizon_minutes:
                hit = first_setup(bars, prev, rule)
                if hit:
                    records.append({"symbol": symbol, "day": day, **hit})
            prev = session_levels(bars) or prev
    return records


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / (1 + z * z / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize(records: list[dict[str, Any]], rule: Rule, sessions_tested: int, symbols_tested: int) -> dict[str, Any]:
    n = len(records)
    wins = sum(r["result"] == "SUCCESS" for r in records)
    lo, hi = wilson(wins, n)
    bands = []
    for a, b in BANDS:
        sel = [r for r in records if a <= r["score"] < b]
        w = sum(r["result"] == "SUCCESS" for r in sel)
        bands.append({"band": f"{a}-{min(b, 100)}", "setups": len(sel), "hit_rate_pct": round(100 * w / len(sel), 1) if sel else None})
    days = sorted({r["day"] for r in records})
    validated = n >= MIN_SETUPS_TO_VALIDATE and sessions_tested >= MIN_SESSIONS_TO_VALIDATE
    return {
        "validated": validated, "setups": n, "successes": wins, "hit_rate_pct": round(100 * wins / n, 1) if n else None,
        "ci95_low_pct": round(100 * lo, 1) if n else None, "ci95_high_pct": round(100 * hi, 1) if n else None,
        "stops": sum(r["result"] == "STOP" for r in records), "timeouts": sum(r["result"] == "TIMEOUT" for r in records),
        "sessions_tested": sessions_tested, "symbols_tested": symbols_tested, "period": [days[0], days[-1]] if days else None,
        "by_score_band": bands, "rule": asdict(rule), "definition": rule.describe(),
        "note": ("Past results on past data. It is not a promise or a probability for any future trade." if validated else
                 f"Not enough history to rely on: needs at least {MIN_SETUPS_TO_VALIDATE} setups across {MIN_SESSIONS_TO_VALIDATE} sessions."),
    }
