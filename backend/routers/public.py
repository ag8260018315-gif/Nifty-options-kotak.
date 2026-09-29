"""Public, read-only endpoints for the landing page (no sign-in).

Only index-level numbers are exposed here: price, change, previous close, state and time.
Option chains, OI, Greeks, signals and exports stay behind sign-in.
PUBLIC_TICKER_DELAY_MINUTES (default 0) shows prices from N minutes ago, using the live candles.
"""
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from lib import access
from lib.candles import candle_store
from lib.feed_worker import feed_worker
from lib.settings import settings


router = APIRouter(prefix="/public", tags=["public"])
NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "BANKNIFTY", "FINNIFTY": "FINNIFTY"}
_cache: dict[str, Any] = {"at": 0.0, "body": None}


def _delay_minutes() -> int:
    try:
        return min(60, max(0, int(os.environ.get("PUBLIC_TICKER_DELAY_MINUTES", "0"))))
    except ValueError:
        return 0


def _price_plan() -> dict[str, Any]:
    try:
        price = int(os.environ.get("PLAN_PRICE_INR", "189"))
    except ValueError:
        price = 189
    try:
        trial_days = max(0, int(os.environ.get("TRIAL_DAYS", "7")))
    except ValueError:
        trial_days = 7
    return {"trial_days": trial_days, "price_inr": price, "period": "month", "payments_live": False, "signups_open": access.signups_open()}


@router.get("/plan")
async def plan() -> dict[str, Any]:
    return _price_plan()


async def _build_ticker() -> dict[str, Any]:
    delay = _delay_minutes()
    items: list[dict[str, Any]] = []
    if settings.mode != "LIVE":
        for symbol, name in NAMES.items():
            items.append({"symbol": symbol, "name": name, "available": False, "state": "UNAVAILABLE", "ltp": None, "change": None, "pct_change": None, "prev_close": None, "last_tick": None})
        return {"items": items, "delay_minutes": delay, "refresh_seconds": 2, "generated_at": datetime.now(timezone.utc).isoformat()}
    status = feed_worker.status()
    states = {item.symbol: item for item in status.indices}
    for symbol, name in NAMES.items():
        snapshot = feed_worker.snapshot_for(symbol)
        index_state = states.get(symbol)
        state = index_state.state if index_state else status.state
        entry: dict[str, Any] = {"symbol": symbol, "name": name, "available": False, "state": state, "ltp": None, "change": None, "pct_change": None, "prev_close": None, "last_tick": None}
        if snapshot is not None and snapshot.spot.ltp > 0:
            spot = snapshot.spot
            prev_close = spot.prev_close
            ltp, stamp = spot.ltp, snapshot.feed.last_tick or spot.timestamp
            if delay > 0:
                candles = (await candle_store.get(symbol, 1))["candles"]
                cutoff = time.time() - delay * 60
                older = [candle for candle in candles if candle["time"] + 60 <= cutoff]
                if older:
                    ltp, stamp = older[-1]["close"], datetime.fromtimestamp(older[-1]["time"] + 60, timezone.utc)
                elif state == "LIVE":
                    ltp = None  # nothing old enough yet: show nothing rather than live data
            if ltp is not None:
                change = round(ltp - prev_close, 2) if prev_close else None
                entry.update(
                    available=True,
                    ltp=round(ltp, 2),
                    change=change,
                    pct_change=round(change / prev_close * 100, 2) if change is not None and prev_close else None,
                    prev_close=prev_close,
                    last_tick=stamp.isoformat() if stamp else None,
                )
        items.append(entry)
    return {"items": items, "delay_minutes": delay, "refresh_seconds": 2, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/ticker")
async def ticker() -> dict[str, Any]:
    now = time.monotonic()
    if _cache["body"] is None or now - _cache["at"] >= 1.0:  # one computation per second, however many visitors
        _cache["body"] = await _build_ticker()
        _cache["at"] = now
    return _cache["body"]
