"""Plain readings of the current chain, shown on the dashboard and given to the AI analyst.

These describe what the data shows. They are not recommendations: there is no buy or sell label,
no target, no stop level and no confidence figure, and nothing here combines the readings into a call.

  PCR lean       PUT-HEAVY when PCR >= 1.05, CALL-HEAVY when PCR <= 0.85, otherwise BALANCED.
                 It describes open interest positioning in the strikes on screen, not direction.
  Price moves    Change in the index over the last 5 and 15 minutes, from live one-minute candles.
  15-min range   The highest high and lowest low of the last 15 one-minute candles.
Only live Kotak data is used; nothing is filled in when data is missing.
"""
from datetime import datetime, timezone
from typing import Any

PCR_PUT_HEAVY = 1.05
PCR_CALL_HEAVY = 0.85
RANGE_WINDOW_MINUTES = 15

# Labels that older saved snapshots and exports carry. They are shown as neutral descriptions instead.
LEGACY_LABELS = {"BUY CALLS": "PUT-HEAVY", "BUY PUTS": "CALL-HEAVY", "WAIT": "BALANCED"}
BIAS_LABELS = {"BULLISH": "PUT-HEAVY", "BEARISH": "CALL-HEAVY", "NEUTRAL": "BALANCED"}


def neutral_label(value: Any) -> Any:
    """Turns an old BUY CALLS / BUY PUTS / WAIT label (or a bias word) into a neutral description."""
    if isinstance(value, str):
        return LEGACY_LABELS.get(value.strip().upper(), BIAS_LABELS.get(value.strip().upper(), value))
    return value


def pcr_lean(pcr: float) -> str:
    return "PUT-HEAVY" if pcr >= PCR_PUT_HEAVY else "CALL-HEAVY" if pcr <= PCR_CALL_HEAVY else "BALANCED"


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


def build_market_read(snapshot: Any | None, candles: list[dict[str, Any]], feed_state: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "available": False,
        "symbol": getattr(snapshot, "symbol", None),
        "feed_state": feed_state,
        "reasons": [],
        "range_window_minutes": RANGE_WINDOW_MINUTES,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    if snapshot is None or not snapshot.option_chain or not snapshot.spot.ltp or snapshot.spot.ltp <= 0:
        base["reasons"] = ["Waiting for a live option chain."]
        return base

    spot = float(snapshot.spot.ltp)
    pcr = float(snapshot.structure.pcr)
    lean = pcr_lean(pcr)
    move5 = price_move(candles, 5 * 60)
    move15 = price_move(candles, 15 * 60)
    trend = _trend(move5, move15)
    window = candles[-RANGE_WINDOW_MINUTES:]
    atm = _atm_row(snapshot)

    positioning = {
        "PUT-HEAVY": "put open interest is above call open interest",
        "CALL-HEAVY": "call open interest is above put open interest",
        "BALANCED": "put and call open interest are close",
    }[lean]
    reasons = [f"PCR is {pcr:.2f}: {positioning} across these strikes."]
    if trend == "BUILDING":
        reasons.append("Price moves need at least 15 minutes of live candles.")
    else:
        reasons.append(f"The index moved {move5:+.2f} points over 5 minutes and {move15:+.2f} over 15 minutes.")
    if feed_state not in {"LIVE", "DEMO"}:
        reasons.append(f"The feed is {feed_state}, so these readings may not be current.")

    return {
        **base,
        "available": True,
        "reasons": reasons,
        "spot": round(spot, 2),
        "pcr": round(pcr, 2),
        "pcr_lean": lean,
        "trend": trend,
        "move_5m": move5,
        "move_15m": move15,
        "range_15m_high": round(max(c["high"] for c in window), 2) if window else None,
        "range_15m_low": round(min(c["low"] for c in window), 2) if window else None,
        "candles_in_window": len(window),
        "atm_strike": atm.strike if atm else None,
    }
