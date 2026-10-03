"""Historical test of the stock watchlist (premium.breakout) on stored 1-minute stock candles.

The live list shows the TOP 10 stocks by score at each moment, so that is what is tested. At every evaluation moment of every
session the test:
  1. rebuilds, for every stock, exactly what the live list would have seen (only candles that had CLOSED at that moment, the
     previous session's high/low/close for pivots, the same 5-minute-else-1-minute choice) and its score;
  2. takes the 10 highest-scoring stocks as "the list" at that moment;
  3. reads what happened afterwards ONLY from later candles, which never feed back into the score.

Success (default, adjustable): a candle CLOSES above the stock's resistance level AND price reaches +target% from the entry within
`horizon_minutes`, without first touching -stop% (a candle spanning both counts as a stop).

Comparison with chance, matched by time: at the same moment, the plain move test ("+target% before -stop%", no resistance
condition) is measured for the top 10 AND for all stocks. Matching the moment removes the time-of-day effect (the first hour is
more volatile than the afternoon). The difference is averaged per day, and the uncertainty comes from the spread across days, so
moments within a day (which move together) are not treated as independent. Only moments with a complete look-forward window are used.
"""
import math
from dataclasses import asdict, dataclass
from typing import Any

from premium.analysis import MIN_BARS, analyse, resample_ohlcv
from premium.breakout import breakout_setup

MIN_SETUPS_TO_VALIDATE = 500
MIN_SESSIONS_TO_VALIDATE = 40
BANDS = [(0, 50), (50, 65), (65, 80), (80, 101)]
TOP_N = 10


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


def pure_outcome(entry: float, future: list[dict[str, Any]], rule: Rule) -> str:
    """The plain move test, with no resistance condition: +target% before -stop% within the window (stop first when ambiguous)."""
    target, stop = entry * (1 + rule.target_pct / 100), entry * (1 - rule.stop_pct / 100)
    for bar in future:
        if bar["low"] <= stop:
            return "STOP"
        if bar["high"] >= target:
            return "SUCCESS"
    return "TIMEOUT"


def setup_at(bars: list[dict[str, Any]], i: int, prev: dict[str, float] | None) -> dict[str, Any] | None:
    """What the live watchlist would have shown for this stock right after bar i closed, using only data up to bar i."""
    known = bars[: i + 1]
    now = bars[i]["time"] + 60  # the evaluation moment: bar i has just closed
    hi, lo = max(b["high"] for b in known), min(b["low"] for b in known)
    five = analyse(resample_ohlcv(known, 5), 5, prev, now, True, hi, lo, False)
    chosen = five if five["bars_closed"] >= MIN_BARS else analyse(known, 1, prev, now, True, hi, lo, False)
    return breakout_setup(chosen)


def _moments(n: int, rule: Rule) -> range:
    """Evaluation moments (index of the bar that just closed) whose look-forward window fits inside the session."""
    return range(MIN_BARS - 1, n - 1 - rule.horizon_minutes + 1, rule.eval_step_minutes)


def observe_session(symbol: str, day: str, bars: list[dict[str, Any]], prev: dict[str, float] | None, rule: Rule) -> list[tuple]:
    """(day, time, symbol, score|None, plain move result, full-rule result|None) for each evaluation moment of one session."""
    out = []
    for i in _moments(len(bars), rule):
        entry = bars[i]["close"]
        future = bars[i + 1 : i + 1 + rule.horizon_minutes]
        move = pure_outcome(entry, future, rule)
        setup = setup_at(bars, i, prev)
        full = outcome(entry, setup["resistance"], future, rule)[0] if setup else None
        out.append((day, bars[i]["time"] + 60, symbol, setup["score"] if setup else None, move, full))
    return out


def observe(symbols: dict[str, list[tuple[str, list[dict[str, Any]]]]], rule: Rule) -> list[tuple]:
    """`symbols`: symbol -> [(trading_day, 1-minute bars)] oldest first."""
    obs: list[tuple] = []
    for symbol, days in symbols.items():
        prev = None
        for day, bars in days:
            if len(bars) > MIN_BARS + rule.horizon_minutes:
                obs.extend(observe_session(symbol, day, bars, prev, rule))
            prev = session_levels(bars) or prev
    return obs


def _mean_ci(values: list[float]) -> tuple[float, float, float]:
    """mean and a 95% range from the spread across values (days)."""
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return mean, mean, mean
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    se = sd / math.sqrt(n)
    return mean, mean - 1.96 * se, mean + 1.96 * se


def cross_section(obs: list[tuple], rule: Rule, top_n: int = TOP_N) -> dict[str, Any]:
    """The top-N list at every moment versus all stocks at the same moment, summarised per day."""
    groups: dict[tuple[str, int], list[tuple]] = {}
    for o in obs:
        groups.setdefault((o[0], o[1]), []).append(o)
    per_day: dict[str, dict[str, list[float]]] = {}
    pooled = {"listed_n": 0, "listed_move": 0, "listed_full": 0, "listed_stop": 0, "listed_timeout": 0, "base_n": 0, "base_move": 0, "moments": 0}
    bands = {b: [0, 0] for b in BANDS}
    for (day, _t), members in groups.items():
        for m in members:
            if m[3] is not None:
                for band in BANDS:
                    if band[0] <= m[3] < band[1]:
                        bands[band][0] += 1
                        bands[band][1] += m[5] == "SUCCESS"
        scored = sorted((m for m in members if m[3] is not None), key=lambda m: (-m[3], m[2]))
        if len(scored) < top_n or len(members) < 2 * top_n:
            continue  # not enough stocks at this moment for a meaningful top-N versus the rest
        top = scored[:top_n]
        top_move = sum(m[4] == "SUCCESS" for m in top) / top_n
        base_move = sum(m[4] == "SUCCESS" for m in members) / len(members)
        top_full = sum(m[5] == "SUCCESS" for m in top) / top_n
        d = per_day.setdefault(day, {"diff": [], "full": []})
        d["diff"].append(top_move - base_move)
        d["full"].append(top_full)
        pooled["moments"] += 1
        pooled["listed_n"] += top_n
        pooled["listed_move"] += sum(m[4] == "SUCCESS" for m in top)
        pooled["listed_full"] += sum(m[5] == "SUCCESS" for m in top)
        pooled["listed_stop"] += sum(m[5] == "STOP" for m in top)
        pooled["listed_timeout"] += sum(m[5] == "TIMEOUT" for m in top)
        pooled["base_n"] += len(members)
        pooled["base_move"] += sum(m[4] == "SUCCESS" for m in members)
    day_diff = [sum(v["diff"]) / len(v["diff"]) for v in per_day.values()]
    day_full = [sum(v["full"]) / len(v["full"]) for v in per_day.values()]
    return {"pooled": pooled, "day_diff": day_diff, "day_full": day_full, "days": sorted(per_day), "bands": {f"{a}-{min(b, 100)}": v for (a, b), v in bands.items()}}


def run(symbols: dict[str, list[tuple[str, list[dict[str, Any]]]]], rule: Rule, top_n: int = TOP_N) -> dict[str, Any]:
    return cross_section(observe(symbols, rule), rule, top_n)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / (1 + z * z / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize(cs: dict[str, Any], rule: Rule, symbols_tested: int, top_n: int = TOP_N) -> dict[str, Any]:
    p, days = cs["pooled"], cs["days"]
    n_days = len(days)
    full_rate = p["listed_full"] / p["listed_n"] if p["listed_n"] else None
    full_mean, full_lo, full_hi = _mean_ci(cs["day_full"]) if n_days else (0.0, 0.0, 0.0)
    listed_move = p["listed_move"] / p["listed_n"] if p["listed_n"] else None
    base_move = p["base_move"] / p["base_n"] if p["base_n"] else None
    if n_days:
        d_mean, d_lo, d_hi = _mean_ci(cs["day_diff"])
    else:
        d_mean = d_lo = d_hi = 0.0
    if n_days < 10 or not p["listed_n"]:
        verdict, text = "UNKNOWN", "Not enough days to compare with chance."
    elif d_lo > 0:
        verdict, text = "BETTER", "At the same moments, the top-ranked stocks reached the target more often than stocks in general, by more than chance alone would explain."
    elif d_hi < 0:
        verdict, text = "WORSE", "At the same moments, the top-ranked stocks reached the target LESS often than stocks in general."
    else:
        verdict, text = "SAME", "At the same moments, the top-ranked stocks cannot be told apart from stocks in general on this test."
    validated = p["listed_n"] >= MIN_SETUPS_TO_VALIDATE and n_days >= MIN_SESSIONS_TO_VALIDATE
    pct = lambda v: None if v is None else round(100 * v, 1)  # noqa: E731
    return {
        "method": f"top_{top_n}_by_score_at_each_moment",
        "validated": validated, "setups": p["listed_n"], "successes": p["listed_full"], "hit_rate_pct": pct(full_rate),
        "ci95_low_pct": pct(max(0.0, full_lo)) if n_days else None, "ci95_high_pct": pct(min(1.0, full_hi)) if n_days else None,
        "stops": p["listed_stop"], "timeouts": p["listed_timeout"], "moments_tested": p["moments"],
        "sessions_tested": n_days, "symbols_tested": symbols_tested, "period": [days[0], days[-1]] if days else None,
        "by_score_band": [{"band": k, "setups": v[0], "hit_rate_pct": round(100 * v[1] / v[0], 1) if v[0] else None} for k, v in cs["bands"].items()],
        "rule": asdict(rule), "definition": rule.describe(),
        "comparison": {
            "test": "Plain move at the same moments: price reaches the target before the stop within the window (no resistance condition). The top-ranked stocks are compared with all stocks at the SAME moment, so time of day cannot explain a difference.",
            "listed_rate_pct": pct(listed_move), "listed_setups": p["listed_n"], "random_rate_pct": pct(base_move), "random_moments": p["base_n"],
            "difference_points": round(100 * d_mean, 2), "difference_ci95_points": [round(100 * d_lo, 2), round(100 * d_hi, 2)], "days": n_days,
            "verdict": verdict, "verdict_text": text,
        },
        "note": ("Past results on past data. It is not a promise or a probability for any future trade." if validated else
                 f"Not enough history to rely on: needs at least {MIN_SETUPS_TO_VALIDATE} listed stock-moments across {MIN_SESSIONS_TO_VALIDATE} sessions."),
    }
