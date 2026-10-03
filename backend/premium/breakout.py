"""Breakout watchlist score: how favourable the CURRENT setup looks for a move through the nearest resistance.

This is a transparent 0-100 SCORE, never a probability. No chance of success (and certainly not "90%") can be stated
without a historical test of this exact rule, and none exists yet, so nothing here claims one.

  proximity   up to 35  price just below the nearest resistance (within 2%; closer scores more)
  volume      up to 35  relative volume vs the last 20 candles (spike) and buying pressure
  trend       up to 15  EMA9/EMA21 uptrend
  momentum    up to 15  RSI 55-70 and a positive signal score
  VWAP        +5        price above VWAP
Only stocks below their nearest resistance by 0-2% and with enough candles are listed.
"""
from typing import Any

MAX_DISTANCE_PCT = 2.0


def breakout_setup(analysis: dict[str, Any]) -> dict[str, Any] | None:
    sig = analysis.get("signal") or {}
    levels = analysis.get("levels") or {}
    price, res = sig.get("price"), levels.get("nearest_resistance")
    if sig.get("action") in (None, "BUILDING") or not price or not res:
        return None
    distance = (res - price) / price * 100
    if distance <= 0 or distance > MAX_DISTANCE_PCT:
        return None
    vol = analysis.get("volume") or {}
    points, why = 0.0, []
    prox = (1 - distance / MAX_DISTANCE_PCT) * 35
    points += prox
    why.append(f"Price is {distance:.2f}% below resistance {res} (+{prox:.0f})")
    rel = vol.get("relative") or 0
    if vol.get("available"):
        gain = 25 if rel >= 2 else 18 if rel >= 1.5 else 10 if rel >= 1.2 else 0
        pressure = vol.get("buying_pressure_pct") or 0
        gain += 10 if pressure >= 60 else 5 if pressure >= 55 else 0
        points += gain
        why.append(f"Volume {rel}x the recent average, buying pressure {pressure}% (+{gain})")
    else:
        why.append("No volume data for this stock yet (+0)")
    label = (analysis.get("trend") or {}).get("label")
    if label == "UPTREND":
        points += 15; why.append("Trend is up: EMA9 above EMA21 (+15)")
    elif label == "SIDEWAYS":
        points += 5; why.append("Trend is sideways (+5)")
    rsi = sig.get("rsi")
    if rsi is not None and 55 <= rsi < 70:
        points += 10; why.append(f"RSI {rsi} shows firm momentum without being overbought (+10)")
    if (sig.get("score") or 0) >= 20:
        points += 5; why.append("Overall signal score is positive (+5)")
    vwap = analysis.get("vwap")
    if vwap and price > vwap:
        points += 5; why.append("Price is above VWAP (+5)")
    return {
        "score": int(min(100, round(points))), "distance_pct": round(distance, 2), "resistance": res, "support": levels.get("nearest_support"),
        "relative_volume": vol.get("relative"), "buying_pressure_pct": vol.get("buying_pressure_pct"), "trend": label, "rsi": rsi,
        "interval": analysis.get("interval"), "reasons": why,
    }
