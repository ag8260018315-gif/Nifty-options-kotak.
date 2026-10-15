"""End-of-day view of a stock that is not on the live feed: a header built from the last stored daily candles, clearly labelled.
Nothing here is a live price, and when no history is stored the header says so instead of showing a number."""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _day(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, IST).date().isoformat()


def market(daily: list[dict[str, Any]]) -> dict[str, Any]:
    """The same shape as a live market state, with its own state so no screen mistakes it for a live or merely closed feed."""
    if not daily:
        return {"state": "END_OF_DAY", "message": "No stored price history for this stock yet, so there is nothing to show.", "tick_age_seconds": None, "as_of": None}
    as_of = _day(int(daily[-1]["time"]))
    return {"state": "END_OF_DAY", "message": f"End-of-day data up to {as_of}. This stock is not on the live feed, so it is not a live price.", "tick_age_seconds": None, "as_of": as_of}


def quote(symbol: str, name: str, daily: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The last stored daily candle presented as a quote (last close, change against the close before it). None when nothing is stored."""
    if not daily:
        return None
    last = daily[-1]
    prev_close = daily[-2]["close"] if len(daily) > 1 else None
    change = round(last["close"] - prev_close, 2) if prev_close else None
    return {"symbol": symbol, "name": name, "kind": "stock", "ltp": last["close"], "change": change,
            "change_pct": round(change / prev_close * 100, 2) if change is not None and prev_close else None,
            "open": last["open"], "high": last["high"], "low": last["low"], "prev_close": prev_close, "volume": last.get("volume") or None,
            "vwap": None, "updated_at": datetime.fromtimestamp(int(last["time"]), IST).isoformat(), "end_of_day": True}
