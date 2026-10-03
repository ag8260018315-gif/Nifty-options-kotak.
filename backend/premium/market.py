"""In-memory live quotes and 1-minute candles (with traded volume) for SENSEX and the stock universe.

Built only from Kotak SFeed ticks. No backfill and no synthetic data: a candle exists only for minutes in which ticks
arrived, so charts and indicators start when the server starts receiving ticks. Today's candles are saved to MongoDB
(`premium_candles`) so a restart does not lose the day, and the previous session is read back for pivot levels.
"""
import logging
import time as _time
from datetime import date, datetime, time as dtime, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
OPEN_T, CLOSE_T = dtime(9, 15), dtime(15, 30)
FRESH_SECONDS = 15  # a tick older than this during market hours means the data is delayed
COLLECTION = "premium_candles"
QUOTES_COLLECTION = "premium_quotes"
FLUSH_SECONDS = 20


def market_hours(now: datetime) -> bool:
    local = now.astimezone(IST)
    return local.weekday() < 5 and OPEN_T <= local.time() < CLOSE_T


def market_state(now: datetime, last_tick: datetime | None) -> dict[str, Any]:
    """OPEN = in hours and ticks are fresh; DELAYED = in hours but ticks are old or absent; CLOSED = outside hours."""
    age = None if last_tick is None else max(0.0, (now - last_tick).total_seconds())
    if not market_hours(now):
        return {"state": "CLOSED", "message": "Market closed. Showing the last received prices.", "tick_age_seconds": age}
    if age is None:
        return {"state": "DELAYED", "message": "No live price received yet today. Check the Kotak connection, or the exchange may be closed for a holiday.", "tick_age_seconds": None}
    if age > FRESH_SECONDS:
        return {"state": "DELAYED", "message": f"Data is delayed: last price {int(age)} seconds ago.", "tick_age_seconds": age}
    return {"state": "OPEN", "message": "Live", "tick_age_seconds": age}


def _day_of(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, IST).date().isoformat()


class PremiumMarket:
    def __init__(self) -> None:
        self.symbol_by_key: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.kinds: dict[str, str] = {}
        self.quotes: dict[str, dict[str, Any]] = {}
        self.candles: dict[str, dict[int, dict[str, Any]]] = {}
        self._day: dict[str, str] = {}
        self._last_cum: dict[str, float] = {}
        self._dirty: dict[str, set[int]] = {}
        self._loaded: set[tuple[str, str]] = set()
        self._prev_cache: dict[tuple[str, str], dict[str, float] | None] = {}
        self._last_session_cache: dict[str, tuple[str, tuple[str, list[dict[str, Any]]] | None]] = {}
        self._last_flush = 0.0
        self.collection_override: Any | None = None  # tests inject a fake collection
        self.quotes_override: Any | None = None
        self._quote_dirty: set[str] = set()
        self._quotes_restored = False
        self.subscription_error: str | None = None
        self.subscribed = False
        self.quick_drops = 0  # socket drops right after the premium subscription (circuit breaker input)
        self.ticks = 0

    # ------------------------------------------------------------------ circuit breaker
    QUICK_DROP_SECONDS = 45
    MAX_QUICK_DROPS = 2

    @property
    def circuit_open(self) -> bool:
        """True once the socket dropped twice within moments of subscribing the premium instruments: premium then stays
        off until the server restarts, so a bad premium subscription can never keep the NIFTY feed in a reconnect loop."""
        return self.quick_drops >= self.MAX_QUICK_DROPS

    def note_disconnect(self, seconds_since_subscribe: float | None) -> None:
        if seconds_since_subscribe is not None and seconds_since_subscribe < self.QUICK_DROP_SECONDS:
            self.quick_drops += 1
            if self.circuit_open:
                self.subscription_error = "Premium feed switched off: the Kotak socket kept dropping right after subscribing the extra instruments."
        elif seconds_since_subscribe is not None:
            self.quick_drops = 0

    # ------------------------------------------------------------------ setup
    def configure(self, symbol_by_key: dict[str, str], names: dict[str, str], kinds: dict[str, str]) -> None:
        self.symbol_by_key = dict(symbol_by_key)
        self.names.update(names)  # merge: instruments the feed could not resolve stay listed (without prices)
        self.kinds.update(kinds)

    def configure_static(self) -> None:
        """Make the instrument list known before any feed connects (market closed, restart, no login yet)."""
        from premium.universe import static_universe

        names, kinds = static_universe()
        for sym in kinds:
            self.names.setdefault(sym, names[sym])
            self.kinds.setdefault(sym, kinds[sym])

    def symbols(self, kind: str | None = None) -> list[str]:
        return [s for s, k in self.kinds.items() if kind is None or k == kind]

    def _col(self, name: str = COLLECTION) -> Any:
        override = self.quotes_override if name == QUOTES_COLLECTION else self.collection_override
        if override is not None:
            return override
        from lib.db import db  # lazy: no import-time database dependency

        return db[name]

    # ------------------------------------------------------------------ ingest
    def symbol_for(self, tick: dict[str, Any]) -> str | None:
        for key in tick.get("keys", []):
            if key in self.symbol_by_key:
                return self.symbol_by_key[key]
        name = str(tick.get("name", "")).upper()
        return "SENSEX" if "SENSEX" in name and "SENSEX" in self.kinds else None

    def on_tick(self, tick: dict[str, Any], now: datetime | None = None) -> None:
        symbol = self.symbol_for(tick)
        ltp = tick.get("ltp")
        if symbol is None or not ltp or ltp <= 0:
            return
        now = now or datetime.now(timezone.utc)
        self.ticks += 1
        old = self.quotes.get(symbol, {})
        quote = {
            "symbol": symbol, "name": self.names.get(symbol, symbol), "kind": self.kinds.get(symbol, "stock"), "ltp": ltp,
            "open": tick.get("open", old.get("open")), "high": tick.get("high", old.get("high")), "low": tick.get("low", old.get("low")),
            "prev_close": tick.get("close", old.get("prev_close")), "volume": tick.get("volume", old.get("volume")), "vwap": tick.get("vwap", old.get("vwap")),
            "updated_at": now.isoformat(), "_ts": now,
        }
        pc = quote["prev_close"]
        quote["change"] = tick["change"] if tick.get("change") is not None else (round(ltp - pc, 2) if pc else None)
        quote["change_pct"] = tick["change_pct"] if tick.get("change_pct") is not None else (round((ltp - pc) / pc * 100, 2) if pc else None)
        self.quotes[symbol] = quote
        self._quote_dirty.add(symbol)
        if market_hours(now):
            self._add_to_candle(symbol, ltp, tick.get("volume"), now)

    def _add_to_candle(self, symbol: str, ltp: float, cum_volume: float | None, now: datetime) -> None:
        local = now.astimezone(IST)
        day = local.date().isoformat()
        if self._day.get(symbol) != day:  # new session: start clean
            self.candles[symbol], self._dirty[symbol], self._day[symbol] = {}, set(), day
            self._last_cum.pop(symbol, None)
        minute = int(local.replace(second=0, microsecond=0).timestamp())
        bucket = self.candles.setdefault(symbol, {})
        delta = 0
        if cum_volume is not None:
            prev = self._last_cum.get(symbol)
            delta = max(0, cum_volume - prev) if prev is not None else 0  # the first tick only sets the baseline
            self._last_cum[symbol] = cum_volume
        bar = bucket.get(minute)
        if bar is None:
            bucket[minute] = {"time": minute, "open": ltp, "high": ltp, "low": ltp, "close": ltp, "volume": int(delta), "ticks": 1}
        else:
            bar["high"], bar["low"], bar["close"] = max(bar["high"], ltp), min(bar["low"], ltp), ltp
            bar["volume"] += int(delta)
            bar["ticks"] += 1
        self._dirty.setdefault(symbol, set()).add(minute)

    # ------------------------------------------------------------------ persistence
    async def flush(self, force: bool = False) -> None:
        if not force and _time.monotonic() - self._last_flush < FLUSH_SECONDS:
            return
        self._last_flush = _time.monotonic()
        if self._quote_dirty:
            symbols, self._quote_dirty = list(self._quote_dirty), set()
            try:
                for symbol in symbols:
                    q = {k: v for k, v in self.quotes[symbol].items() if not k.startswith("_")}
                    await self._col(QUOTES_COLLECTION).replace_one({"_id": symbol}, {"_id": symbol, **q}, upsert=True)
            except Exception as exc:  # noqa: BLE001
                self._quote_dirty |= set(symbols)
                logger.warning("PREMIUM_QUOTES_FLUSH_ERROR kind=%s", type(exc).__name__)
        for symbol, minutes in list(self._dirty.items()):
            if not minutes:
                continue
            todo, self._dirty[symbol] = sorted(minutes), set()
            try:
                col = self._col()
                for minute in todo:
                    bar = self.candles.get(symbol, {}).get(minute)
                    if bar:
                        await col.update_one({"_id": f"{symbol}:{minute}"}, {"$set": {**bar, "symbol": symbol, "trading_day": self._day[symbol]}}, upsert=True)
            except Exception as exc:  # noqa: BLE001  storage trouble must never disturb the feed
                self._dirty[symbol] |= set(todo)
                logger.warning("PREMIUM_FLUSH_ERROR kind=%s", type(exc).__name__)
                return

    async def ensure_quotes(self) -> None:
        """Load the last saved quotes once, so after hours (or after a restart) the page shows the last received prices."""
        if self._quotes_restored:
            return
        self._quotes_restored = True
        try:
            docs = await self._col(QUOTES_COLLECTION).find({}, {"_id": 0}).to_list(2000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PREMIUM_QUOTES_RESTORE_ERROR kind=%s", type(exc).__name__)
            return
        for d in docs:
            symbol = d.get("symbol")
            if symbol in self.quotes or not symbol or not d.get("ltp"):
                continue  # a live tick always wins over a stored one
            try:
                stamp = datetime.fromisoformat(d["updated_at"])
            except (KeyError, ValueError):
                continue
            self.quotes[symbol] = {**d, "_ts": stamp}

    async def _restore(self, symbol: str, day: str) -> None:
        if (symbol, day) in self._loaded:
            return
        self._loaded.add((symbol, day))
        try:
            docs = await self._col().find({"symbol": symbol, "trading_day": day}, {"_id": 0}).sort("time", 1).to_list(1000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PREMIUM_RESTORE_ERROR kind=%s", type(exc).__name__)
            return
        bucket = self.candles.setdefault(symbol, {})
        self._day.setdefault(symbol, day)
        for d in docs:
            bucket.setdefault(int(d["time"]), {k: d[k] for k in ("time", "open", "high", "low", "close", "volume", "ticks") if k in d})

    # ------------------------------------------------------------------ read
    async def today_bars(self, symbol: str, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(IST).date().isoformat()
        await self._restore(symbol, day)
        if self._day.get(symbol) != day:
            return []
        return [dict(self.candles[symbol][m]) for m in sorted(self.candles.get(symbol, {}))]

    async def bars_for_day(self, symbol: str, trading_day: str) -> list[dict[str, Any]]:
        """Stored 1-minute candles of one earlier session (used to fill the days between an import and today)."""
        try:
            docs = await self._col().find({"symbol": symbol, "trading_day": trading_day}, {"_id": 0}).sort("time", 1).to_list(1000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PREMIUM_DAY_BARS_ERROR kind=%s", type(exc).__name__)
            return []
        return [{k: d[k] for k in ("time", "open", "high", "low", "close", "volume") if k in d} for d in docs]

    async def last_session(self, symbol: str, now: datetime | None = None) -> tuple[str, list[dict[str, Any]]] | None:
        """(trading day, 1-minute candles) of the latest earlier session with stored candles, for weekends and holidays when today has
        none. Past sessions never change, so the result is kept in memory for the rest of the day."""
        today = (now or datetime.now(timezone.utc)).astimezone(IST).date().isoformat()
        cached = self._last_session_cache.get(symbol)
        if cached and cached[0] == today:
            return cached[1]
        result = None
        try:
            last = await self._col().find_one({"symbol": symbol, "trading_day": {"$lt": today}}, {"trading_day": 1}, sort=[("trading_day", -1)])
            if last:
                bars = await self.bars_for_day(symbol, last["trading_day"])
                result = (last["trading_day"], bars) if bars else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("PREMIUM_LAST_SESSION_ERROR kind=%s", type(exc).__name__)
            return None
        self._last_session_cache[symbol] = (today, result)
        return result

    async def previous_session(self, symbol: str, now: datetime | None = None) -> dict[str, float] | None:
        """High, low and close of the latest earlier session that has stored candles (None if there is none yet)."""
        today = (now or datetime.now(timezone.utc)).astimezone(IST).date().isoformat()
        key = (symbol, today)
        if key in self._prev_cache:
            return self._prev_cache[key]
        result = None
        try:
            col = self._col()
            last = await col.find_one({"symbol": symbol, "trading_day": {"$lt": today}}, {"trading_day": 1}, sort=[("trading_day", -1)])
            if last:
                docs = await col.find({"symbol": symbol, "trading_day": last["trading_day"]}, {"_id": 0}).sort("time", 1).to_list(1000)
                if docs:
                    result = {"high": max(d["high"] for d in docs), "low": min(d["low"] for d in docs), "close": docs[-1]["close"]}
        except Exception as exc:  # noqa: BLE001
            logger.warning("PREMIUM_PREV_ERROR kind=%s", type(exc).__name__)
            return None
        self._prev_cache[key] = result
        return result

    def last_tick(self, symbol: str | None = None) -> datetime | None:
        stamps = [q["_ts"] for s, q in self.quotes.items() if symbol is None or s == symbol]
        return max(stamps) if stamps else None

    def public_quote(self, symbol: str) -> dict[str, Any] | None:
        q = self.quotes.get(symbol)
        return None if q is None else {k: v for k, v in q.items() if not k.startswith("_")}


premium_market = PremiumMarket()
