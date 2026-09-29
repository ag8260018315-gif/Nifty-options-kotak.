"""Rule-based trade plan shown on the dashboard and given to the Claude analyst.

Signal rule (transparent, not a prediction):
  BUY CALLS  when PCR >= 1.05 AND the index rose over both the last 5 and 15 minutes
  BUY PUTS   when PCR <= 0.85 AND the index fell over both the last 5 and 15 minutes
  WAIT       otherwise, or when the feed is not live
Stops, both always shown for the at-the-money strike:
  index stop    CE: lowest index low of the last 15 one-minute candles; PE: highest high
  premium stop  PREMIUM_STOP_PCT (default 25%) below the option's current premium
Only live Kotak data is used; nothing is filled in when data is missing.
"""
import os
from datetime import datetime, timezone
from typing import Any

PCR_BULLISH = 1.05
PCR_BEARISH = 0.85
STOP_WINDOW_MINUTES = 15
TRADEABLE_STATES = {"LIVE", "DEMO"}


def premium_stop_pct() -> float:
    try:
        return min(80.0, max(5.0, float(os.environ.get("PREMIUM_STOP_PCT", "25"))))
    except ValueError:
        return 25.0


def price_move(candles: list[dict[str, Any]], seconds: int) -> float | None:
    """Close of the latest candle minus the close of the last candle at least `seconds` older."""
    if len(candles) < 2:
        return None
    last = candles[-1]
    base = None
    for candle in candles:
        if candle["time"] <= last["time"] - seconds:
            base = candle
        else:
            break
    return None if base is None else round(last["close"] - base["close"], 2)


def _trend(move5: float | None, move15: float | None) -> str:
    if move5 is None or move15 is None:
        return "BUILDING"
    if move5 > 0 and move15 > 0:
        return "RISING"
    if move5 < 0 and move15 < 0:
        return "FALLING"
    return "MIXED"


def _atm_row(snapshot: Any) -> Any | None:
    chain = list(snapshot.option_chain)
    if not chain:
        return None
    marked = next((row for row in chain if row.is_atm), None)
    return marked or min(chain, key=lambda row: abs(row.strike - snapshot.spot.ltp))


def _premium_stop(ltp: float, pct: float) -> float | None:
    return round(ltp * (1 - pct / 100), 2) if ltp and ltp > 0 else None


def build_trade_plan(snapshot: Any | None, candles: list[dict[str, Any]], feed_state: str) -> dict[str, Any]:
    pct = premium_stop_pct()
    base: dict[str, Any] = {
        "available": False,
        "symbol": getattr(snapshot, "symbol", None),
        "signal": "WAIT",
        "reasons": [],
        "feed_state": feed_state,
        "premium_stop_pct": pct,
        "stop_window_minutes": STOP_WINDOW_MINUTES,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "rule": "BUY CALLS: PCR >= 1.05 and price up over 5 and 15 min. BUY PUTS: PCR <= 0.85 and price down over 5 and 15 min. Otherwise WAIT.",
    }
    if snapshot is None or not snapshot.option_chain or not snapshot.spot.ltp or snapshot.spot.ltp <= 0:
        base["reasons"] = ["Waiting for a live option chain."]
        return base

    spot = float(snapshot.spot.ltp)
    pcr = float(snapshot.structure.pcr)
    bias = "BULLISH" if pcr >= PCR_BULLISH else "BEARISH" if pcr <= PCR_BEARISH else "NEUTRAL"
    move5 = price_move(candles, 5 * 60)
    move15 = price_move(candles, 15 * 60)
    trend = _trend(move5, move15)
    window = candles[-STOP_WINDOW_MINUTES:]
    low15 = round(min(c["low"] for c in window), 2) if window else None
    high15 = round(max(c["high"] for c in window), 2) if window else None
    atm = _atm_row(snapshot)

    reasons = [f"PCR is {pcr:.2f} ({bias.lower()}; bullish at 1.05 or above, bearish at 0.85 or below)."]
    if trend == "BUILDING":
        reasons.append("Price momentum needs at least 15 minutes of live candles.")
    else:
        reasons.append(f"Index moved {move5:+.2f} over 5 min and {move15:+.2f} over 15 min ({trend.lower()}).")

    signal = "WAIT"
    if feed_state not in TRADEABLE_STATES:
        reasons.append(f"Feed is {feed_state}, so no signal is given on stale data.")
    elif bias == "BULLISH" and trend == "RISING":
        signal = "BUY CALLS"
        reasons.append("PCR and price both point up.")
    elif bias == "BEARISH" and trend == "FALLING":
        signal = "BUY PUTS"
        reasons.append("PCR and price both point down.")
    elif bias != "NEUTRAL" and trend in {"RISING", "FALLING", "MIXED"}:
        reasons.append("PCR and price disagree, so the rule waits.")
    elif bias == "NEUTRAL":
        reasons.append("PCR is neutral, so the rule waits.")

    ce_ltp = float(atm.call.ltp) if atm else 0.0
    pe_ltp = float(atm.put.ltp) if atm else 0.0
    return {
        **base,
        "available": True,
        "symbol": snapshot.symbol,
        "signal": signal,
        "reasons": reasons,
        "spot": round(spot, 2),
        "pcr": round(pcr, 2),
        "pcr_bias": bias,
        "trend": trend,
        "move_5m": move5,
        "move_15m": move15,
        "atm_strike": atm.strike if atm else None,
        "candles_in_window": len(window),
        "ce": {
            "strike": atm.strike if atm else None,
            "premium": round(ce_ltp, 2) if ce_ltp else None,
            "premium_stop": _premium_stop(ce_ltp, pct),
            "index_stop": low15,
            "index_stop_points": round(spot - low15, 2) if low15 is not None else None,
        },
        "pe": {
            "strike": atm.strike if atm else None,
            "premium": round(pe_ltp, 2) if pe_ltp else None,
            "premium_stop": _premium_stop(pe_ltp, pct),
            "index_stop": high15,
            "index_stop_points": round(high15 - spot, 2) if high15 is not None else None,
        },
    }
