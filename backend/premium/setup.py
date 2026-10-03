"""A transparent trade setup (entry, stop, targets, risk-to-reward, zones) from the analysis. Pure.

Rules (all shown to the user):
  entry   = the last closed price (a zone of 0.3 ATR is shown, on the side where a better price would be)
  stop    = just beyond the nearest opposite support/resistance (0.25 ATR past it) when it lies within 0.5-2.5 ATR,
            otherwise 1.5 ATR from the entry; always between 0.5 and 3 ATR
  targets = the next support/resistance levels that are at least 1R away, filled with 1.5R / 2.5R when levels are missing
  R:R     = distance to target 1 divided by the distance to the stop
These are mechanical levels from past prices. They describe a setup and its risk; they do not predict the outcome.
"""
from typing import Any

MIN_STOP_ATR, MAX_STOP_ATR, DEFAULT_STOP_ATR, ZONE_ATR = 0.5, 3.0, 1.5, 0.3


def _nums(values: list[Any]) -> list[float]:
    return [float(v) for v in values if v is not None]


def build_setup(direction: str, price: float, atr: float | None, support: list[Any], resistance: list[Any]) -> dict[str, Any] | None:
    """direction: 'LONG' or 'SHORT'. Returns None when there is no usable volatility figure."""
    if not atr or atr <= 0 or price <= 0:
        return None
    sup, res = sorted(_nums(support), reverse=True), sorted(_nums(resistance))
    long_ = direction == "LONG"
    barrier = next((s for s in sup if price - s >= MIN_STOP_ATR * atr and price - s <= 2.5 * atr), None) if long_ else next((r for r in res if r - price >= MIN_STOP_ATR * atr and r - price <= 2.5 * atr), None)
    if barrier is not None:
        stop = barrier - 0.25 * atr if long_ else barrier + 0.25 * atr
    else:
        stop = price - DEFAULT_STOP_ATR * atr if long_ else price + DEFAULT_STOP_ATR * atr
    risk = abs(price - stop)
    risk = min(max(risk, MIN_STOP_ATR * atr), MAX_STOP_ATR * atr)
    stop = price - risk if long_ else price + risk
    ahead = [r for r in res if r - price >= risk] if long_ else [s for s in sup if price - s >= risk]
    t1 = ahead[0] if ahead else (price + 1.5 * risk if long_ else price - 1.5 * risk)
    t2 = ahead[1] if len(ahead) > 1 else (price + 2.5 * risk if long_ else price - 2.5 * risk)
    if (t2 - t1 if long_ else t1 - t2) <= 0:
        t2 = price + 2.5 * risk if long_ else price - 2.5 * risk
    reward = abs(t1 - price)
    zone = [round(price - ZONE_ATR * atr, 2), round(price, 2)] if long_ else [round(price, 2), round(price + ZONE_ATR * atr, 2)]
    return {
        "direction": direction, "entry": round(price, 2), "entry_zone": zone, "stop": round(stop, 2), "targets": [round(t1, 2), round(t2, 2)],
        "risk_per_share": round(risk, 2), "reward_to_risk": round(reward / risk, 2), "atr": round(atr, 2),
        "zone_label": "Buy zone" if long_ else "Sell zone",
        "method": "Entry at the last close; stop beyond the nearest support/resistance (or 1.5 ATR); targets at the next levels at least 1R away.",
    }
