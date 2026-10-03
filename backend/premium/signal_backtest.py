"""Historical test of the stock signal engine on stored 1-minute candles: win rate, expectancy and drawdown per stock.

For each session the test replays what the live engine would have seen at every evaluation moment: only candles that had CLOSED
(5-minute candles when there are enough, else 1-minute, as live), yesterday's high/low/close for pivots, and the same analysis and
`stock_signal` code. When the engine says Bullish or Bearish and produces a setup, a trade is opened at the last close and then read
forward ONLY from later candles, until the first of: target 1 (+R = the setup's reward-to-risk), the stop (-1R), or the time limit
(marked to market at the limit). A candle touching both stop and target counts as a stop. One trade per stock at a time.
A round-trip cost (default 0.05% of price) is charged and shown in R. Results are past results on past data, not promises.
"""
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from premium.analysis import MIN_BARS, analyse, resample_ohlcv
from premium.signal_engine import stock_signal

MIN_TRADES_TO_RELY = 30
LIVE = {"state": "OPEN", "message": "Live", "tick_age_seconds": 0}


@dataclass(frozen=True)
class Rule:
    horizon_minutes: int = 90
    eval_step_minutes: int = 15
    cost_pct: float = 0.05  # round-trip cost as % of price


def simulate(direction: str, entry: float, stop: float, target: float, rr: float, future: list[dict[str, Any]]) -> tuple[str, float, int]:
    """(result, gross R, bars used). The R multiple is measured against the stop distance."""
    risk = abs(entry - stop)
    long_ = direction == "LONG"
    for n, bar in enumerate(future, start=1):
        hit_stop = bar["low"] <= stop if long_ else bar["high"] >= stop
        hit_target = bar["high"] >= target if long_ else bar["low"] <= target
        if hit_stop:
            return "STOP", -1.0, n
        if hit_target:
            return "TARGET", rr, n
    if not future:
        return "TIMEOUT", 0.0, 0
    last = future[-1]["close"]
    return "TIMEOUT", ((last - entry) if long_ else (entry - last)) / risk, len(future)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / (1 + z * z / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def run_symbol(days: list[tuple[str, list[dict[str, Any]]]], rule: Rule) -> list[dict[str, Any]]:
    """Trades for one stock. `days`: [(trading_day, 1-minute bars)] oldest first."""
    trades: list[dict[str, Any]] = []
    prev = None
    for day, bars in days:
        n = len(bars)
        i, free_from = MIN_BARS - 1, 0
        while i < n - 1:
            if i < free_from:
                i += rule.eval_step_minutes
                continue
            known = bars[: i + 1]
            now = bars[i]["time"] + 60
            hi, lo = max(b["high"] for b in known), min(b["low"] for b in known)
            five = analyse(resample_ohlcv(known, 5), 5, prev, now, True, hi, lo, True, tail=120)
            interval, an = (5, five) if five["bars_closed"] >= MIN_BARS else (1, analyse(known, 1, prev, now, True, hi, lo, True, tail=120))
            sig = stock_signal(an, LIVE, interval, datetime.fromtimestamp(now, timezone.utc))
            setup = sig.get("setup")
            if setup and sig["bias"] in ("Bullish", "Bearish"):
                future = bars[i + 1 : i + 1 + rule.horizon_minutes]
                if len(future) == rule.horizon_minutes:  # only trades whose full time window is inside the session
                    result, gross_r, used = simulate(setup["direction"], setup["entry"], setup["stop"], setup["targets"][0], setup["reward_to_risk"], future)
                    cost_r = setup["entry"] * rule.cost_pct / 100 / setup["risk_per_share"]
                    trades.append({"day": day, "time": now, "direction": setup["direction"], "score": sig["score"], "result": result, "gross_r": round(gross_r, 3),
                                   "net_r": round(gross_r - cost_r, 3), "bars": used})
                    free_from = i + max(used, 1)  # no new trade in this stock until this one is over
            i += rule.eval_step_minutes
        if bars:
            prev = {"high": max(b["high"] for b in bars), "low": min(b["low"] for b in bars), "close": bars[-1]["close"]}
    return trades


def summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "reliable": False, "note": "No trades in the tested history."}
    ordered = sorted(trades, key=lambda t: t["time"])
    wins = sum(t["net_r"] > 0 for t in ordered)
    lo, hi = wilson(wins, n)
    equity = peak = drawdown = 0.0
    streak = worst_streak = 0
    for t in ordered:
        equity += t["net_r"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        streak = streak + 1 if t["net_r"] <= 0 else 0
        worst_streak = max(worst_streak, streak)
    gains = sum(t["net_r"] for t in ordered if t["net_r"] > 0)
    losses = -sum(t["net_r"] for t in ordered if t["net_r"] <= 0)
    by_dir = {}
    for d in ("LONG", "SHORT"):
        sel = [t for t in ordered if t["direction"] == d]
        by_dir[d] = {"trades": len(sel), "win_rate_pct": round(100 * sum(t["net_r"] > 0 for t in sel) / len(sel), 1) if sel else None}
    return {
        "trades": n, "wins": wins, "win_rate_pct": round(100 * wins / n, 1), "win_rate_ci95_pct": [round(100 * lo, 1), round(100 * hi, 1)],
        "avg_r": round(sum(t["net_r"] for t in ordered) / n, 3), "total_r": round(equity, 2), "profit_factor": round(gains / losses, 2) if losses > 0 else None,
        "max_drawdown_r": round(drawdown, 2), "longest_losing_streak": worst_streak, "targets": sum(t["result"] == "TARGET" for t in ordered),
        "stops": sum(t["result"] == "STOP" for t in ordered), "timeouts": sum(t["result"] == "TIMEOUT" for t in ordered), "by_direction": by_dir,
        "period": [ordered[0]["day"], ordered[-1]["day"]], "reliable": n >= MIN_TRADES_TO_RELY,
        "note": ("Past results on past data; not a promise." if n >= MIN_TRADES_TO_RELY else f"Only {n} trades: too few to rely on (needs {MIN_TRADES_TO_RELY}+)."),
    }


def rule_dict(rule: Rule) -> dict[str, Any]:
    return asdict(rule)
