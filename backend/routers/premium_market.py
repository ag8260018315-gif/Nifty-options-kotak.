"""PREMIUM routes: live SENSEX / index charts and Indian stock analysis. Every route here is behind
`lib.premium.require_premium` (see server.py), so a free user gets 403 even when calling the API directly.
Data is genuine Kotak Neo live data only; with no live connection these routes say so instead of inventing prices."""
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from lib.candles import candle_store
from lib.feed_worker import feed_worker
from lib.settings import settings
from premium.analysis import MIN_BARS, analyse, resample_ohlcv
from premium.market import IST, market_state, premium_market
from premium.universe import INDEX_NAMES

router = APIRouter(prefix="/premium", tags=["premium"])
NIFTY_INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY")
INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")
INTERVALS = (1, 5, 15)
LABEL = "PREMIUM"
_prev_cache: dict[tuple[str, str], dict[str, float] | None] = {}
_quick_cache: dict[str, tuple[float, dict[str, Any]]] = {}
QUICK_TTL = 4.0


def _live() -> bool:
    return settings.mode == "LIVE"


def _index_quote(symbol: str) -> tuple[dict[str, Any] | None, datetime | None]:
    if symbol == "SENSEX":
        return premium_market.public_quote("SENSEX"), premium_market.last_tick("SENSEX")
    snapshot = feed_worker.snapshot_for(symbol) if _live() else None
    if snapshot is None or not snapshot.spot or not snapshot.spot.ltp:
        return None, None
    status = feed_worker.status()
    idx = next((i for i in status.indices if i.symbol == symbol), None)
    spot = snapshot.spot
    return {"symbol": symbol, "name": INDEX_NAMES[symbol], "kind": "index", "ltp": spot.ltp, "change": spot.change, "change_pct": spot.pct_change,
            "open": spot.open, "high": spot.high, "low": spot.low, "prev_close": spot.prev_close, "volume": None, "updated_at": (idx.last_tick if idx and idx.last_tick else spot.timestamp or snapshot.as_of).isoformat()}, (idx.last_tick if idx else spot.timestamp)


async def _bars(symbol: str) -> tuple[list[dict[str, Any]], bool]:
    """Today's 1-minute bars and whether they carry traded volume."""
    if symbol in NIFTY_INDICES:
        return [{**c, "volume": 0} for c in (await candle_store.get(symbol, 1))["candles"]], False
    return await premium_market.today_bars(symbol), symbol not in INDEX_NAMES


async def _prev_session(symbol: str) -> dict[str, float] | None:
    if symbol not in NIFTY_INDICES:
        return await premium_market.previous_session(symbol)
    today = datetime.now(timezone.utc).astimezone(IST).date()
    key = (symbol, today.isoformat())
    if key in _prev_cache:
        return _prev_cache[key]
    result = None
    for back in range(1, 8):
        day = today - timedelta(days=back)
        candles = (await candle_store.get(symbol, 1, day))["candles"]
        if candles:
            result = {"high": max(c["high"] for c in candles), "low": min(c["low"] for c in candles), "close": candles[-1]["close"]}
            break
    _prev_cache[key] = result
    return result


async def _analyse(symbol: str, interval: int, include_series: bool = True) -> dict[str, Any]:
    quote = (_index_quote(symbol)[0] if symbol in INDICES else premium_market.public_quote(symbol))
    bars, has_volume = await _bars(symbol)
    now = datetime.now(timezone.utc)
    result = analyse(resample_ohlcv(bars, interval), interval, await _prev_session(symbol), now.timestamp(), has_volume,
                     quote.get("high") if quote else None, quote.get("low") if quote else None, include_series)
    return result


def _market_for(symbol: str) -> dict[str, Any]:
    last = _index_quote(symbol)[1] if symbol in INDICES else premium_market.last_tick(symbol)
    state = market_state(datetime.now(timezone.utc), last)
    if not _live():
        state = {"state": "NO_FEED", "message": "The live Kotak feed is not connected, so there is no live price to show.", "tick_age_seconds": None}
    return state


def _clean(quote: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if quote is None else {k: v for k, v in quote.items() if not k.startswith("_")}


@router.get("/status")
async def status() -> dict[str, Any]:
    stocks = premium_market.symbols("stock")
    return {
        "label": LABEL, "source": "KOTAK_NEO", "live_mode": _live(), "market": market_state(datetime.now(timezone.utc), premium_market.last_tick() or None),
        "sensex_subscribed": premium_market.subscribed, "subscription_error": premium_market.subscription_error,
        "stocks_configured": len(stocks), "stocks_with_prices": sum(1 for s in stocks if s in premium_market.quotes), "ticks_received": premium_market.ticks,
        "min_candles_for_signal": MIN_BARS,
        "note": "Prices and candles come only from live Kotak ticks. Charts start when the server starts receiving ticks; there is no historical backfill.",
    }


@router.get("/indices")
async def indices() -> dict[str, Any]:
    rows = []
    for symbol in INDICES:
        quote, _ = _index_quote(symbol)
        rows.append({"symbol": symbol, "name": INDEX_NAMES[symbol], "quote": _clean(quote), "market": _market_for(symbol)})
    return {"label": LABEL, "indices": rows}


@router.get("/index/{symbol}")
async def index_detail(symbol: str, interval: int = Query(default=1)) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in INDICES or interval not in INTERVALS:
        raise HTTPException(status_code=422, detail="Unknown index or interval.")
    quote, _ = _index_quote(symbol)
    return {"label": LABEL, "symbol": symbol, "name": INDEX_NAMES[symbol], "quote": _clean(quote), "market": _market_for(symbol), "analysis": await _analyse(symbol, interval)}


async def _quick(symbol: str) -> dict[str, Any]:
    cached = _quick_cache.get(symbol)
    if cached and time.monotonic() - cached[0] < QUICK_TTL:
        return cached[1]
    five = await _analyse(symbol, 5, include_series=False)
    chosen = five if five["bars_closed"] >= MIN_BARS else await _analyse(symbol, 1, include_series=False)
    sig = chosen["signal"]
    row = {"action": sig["action"], "score": sig.get("score", 0), "strength": sig.get("strength"), "interval": chosen["interval"], "trend": chosen["trend"]["label"],
           "relative_volume": (chosen.get("volume") or {}).get("relative"), "reasons": sig.get("reasons", [])[:4],
           "nearest_support": sig.get("nearest_support"), "nearest_resistance": sig.get("nearest_resistance"), "bars_closed": chosen["bars_closed"]}
    _quick_cache[symbol] = (time.monotonic(), row)
    return row


@router.get("/stocks")
async def stocks() -> dict[str, Any]:
    rows = []
    for symbol in premium_market.symbols("stock"):
        quote = premium_market.public_quote(symbol)
        if quote is None:
            continue
        rows.append({"symbol": symbol, "quote": quote, "signal": await _quick(symbol)})
    rows.sort(key=lambda r: r["symbol"])
    return {"label": LABEL, "market": market_state(datetime.now(timezone.utc), premium_market.last_tick() or None) if _live() else _market_for("NIFTY"),
            "count": len(rows), "configured": len(premium_market.symbols("stock")), "stocks": rows}


@router.get("/stocks/opportunities")
async def opportunities(limit: int = Query(default=8, ge=1, le=20)) -> dict[str, Any]:
    ranked = []
    for symbol in premium_market.symbols("stock"):
        quote = premium_market.public_quote(symbol)
        if quote is None:
            continue
        sig = await _quick(symbol)
        if sig["action"] == "BUY":
            ranked.append({"symbol": symbol, "quote": quote, "signal": sig})
    ranked.sort(key=lambda r: -r["signal"]["score"])
    return {"label": LABEL, "title": "Potential buying setups (informational)", "count": len(ranked), "stocks": ranked[:limit],
            "note": "Ranked by a transparent score of live trend, momentum, MACD, VWAP, volume and nearby support/resistance. It describes current conditions; it is not advice or a prediction."}


@router.get("/stock/{symbol}")
async def stock_detail(symbol: str, interval: int = Query(default=1)) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in premium_market.symbols("stock") or interval not in INTERVALS:
        raise HTTPException(status_code=404, detail="Unknown stock or interval.")
    return {"label": LABEL, "symbol": symbol, "name": premium_market.names.get(symbol, symbol), "quote": premium_market.public_quote(symbol),
            "market": _market_for(symbol), "analysis": await _analyse(symbol, interval)}
