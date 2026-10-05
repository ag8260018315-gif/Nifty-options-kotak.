"""Public, read-only endpoints for the landing page (no sign-in).

Only index-level numbers are exposed here: price, change, previous close, state and time.
Option chains, OI, Greeks, signals and exports stay behind sign-in.
PUBLIC_TICKER_DELAY_MINUTES (default 0) shows prices from N minutes ago, using the live candles.
"""
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import APIRouter

from billing import plans, store as billing
from lib import access
from lib.candles import candle_store
from lib.feed_worker import feed_worker
from lib.settings import settings


router = APIRouter(prefix="/public", tags=["public"])
NAMES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "BANKNIFTY", "FINNIFTY": "FINNIFTY"}
IST = ZoneInfo("Asia/Kolkata")
_cache: dict[str, Any] = {"at": 0.0, "body": None}
_charts_cache: dict[str, Any] = {"at": 0.0, "body": None}


def _delay_minutes() -> int:
    try:
        return min(60, max(0, int(os.environ.get("PUBLIC_TICKER_DELAY_MINUTES", "0"))))
    except ValueError:
        return 0


def _price_plan() -> dict[str, Any]:
    try:
        trial_days = max(0, int(os.environ.get("TRIAL_DAYS", "7")))
    except ValueError:
        trial_days = 7
    return {"trial_days": trial_days, "price_inr": plans.STANDARD_INR, "period": "month", "payments_live": billing.payments_live(), "signups_open": access.signups_open(),
            "premium_intro_inr": plans.PREMIUM_INTRO_INR, "premium_inr": plans.PREMIUM_INR, "terms_version": plans.TERMS_VERSION}


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



async def _build_charts() -> dict[str, Any]:
    """Today's 1-minute index closes, or the most recent session that has candles. Never filled in."""
    delay = _delay_minutes()
    cutoff = time.time() - delay * 60 if delay else None
    today = datetime.now(timezone.utc).astimezone(IST).date()
    series: list[dict[str, Any]] = []
    for symbol, name in NAMES.items():
        points: list[dict[str, float]] = []
        day_used: str | None = None
        if settings.mode == "LIVE":
            for back in range(0, 7):
                day = today - timedelta(days=back)
                candles = (await candle_store.get(symbol, 1, day))["candles"]
                if cutoff is not None:
                    candles = [candle for candle in candles if candle["time"] + 60 <= cutoff]
                if candles:
                    points = [{"t": int(candle["time"]), "c": round(float(candle["close"]), 2)} for candle in candles]
                    day_used = day.isoformat()
                    break
        series.append({"symbol": symbol, "name": name, "trading_day": day_used, "is_today": day_used == today.isoformat(), "points": points})
    return {"series": series, "interval": "1m", "delay_minutes": delay, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/charts")
async def charts() -> dict[str, Any]:
    now = time.monotonic()
    if _charts_cache["body"] is None or now - _charts_cache["at"] >= 10.0:
        _charts_cache["body"] = await _build_charts()
        _charts_cache["at"] = now
    return _charts_cache["body"]
