"""1-minute index candles built only from live Kotak index ticks (NIFTY 50 / BANKNIFTY / FINNIFTY).

No backfill and no synthetic data: a candle exists only for minutes in which the SFeed actually
delivered index ticks to this server. Candles are stored in MongoDB (`index_candles`) so a restart
does not lose the day. Every database call is guarded: a storage problem can never disturb the feed.
"""
import asyncio
import logging
from datetime import date, datetime, time as dtime, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
INTERVALS = {1: "1m", 5: "5m", 15: "15m"}
OPEN_TIME, CLOSE_TIME = dtime(9, 15), dtime(15, 31)  # ticks outside this window are ignored
CURRENT_FLUSH_SECONDS = 15
COLLECTION = "index_candles"


def symbol_for(name: str, token: str = "") -> str | None:
    """Same mapping as the feed worker, so candles and the option chain agree on the index."""
    upper = (name or "").upper()
    if "FIN" in upper and ("NIFTY" in upper or "SERVICE" in upper):
        return "FINNIFTY"
    if "BANK" in upper:
        return "BANKNIFTY"
    if "NIFTY" in upper:
        return "NIFTY"
    return "NIFTY" if token == "26000" else "BANKNIFTY" if token == "26009" else None


def _in_session(ist_now: datetime) -> bool:
    return ist_now.weekday() < 5 and OPEN_TIME <= ist_now.time() < CLOSE_TIME


def resample(candles: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    """Combine 1-minute candles (sorted by time) into `minutes`-minute candles aligned to the IST clock."""
    if minutes <= 1:
        return [dict(c) for c in candles]
    bucket_seconds = minutes * 60
    out: list[dict[str, Any]] = []
    for candle in candles:
        # IST has a fixed +05:30 offset, so align on IST wall-clock, not on UTC epoch multiples
        ist_epoch = candle["time"] + 19800
        start = ist_epoch - (ist_epoch % bucket_seconds) - 19800
        if out and out[-1]["time"] == start:
            last = out[-1]
            last["high"] = max(last["high"], candle["high"])
            last["low"] = min(last["low"], candle["low"])
            last["close"] = candle["close"]
            last["ticks"] += candle["ticks"]
        else:
            out.append({**candle, "time": start})
    return out


class CandleStore:
    def __init__(self) -> None:
        self._today: dict[str, dict[int, dict[str, Any]]] = {s: {} for s in SYMBOLS}
        self._day: dict[str, date | None] = {s: None for s in SYMBOLS}
        self._dirty: dict[str, set[int]] = {s: set() for s in SYMBOLS}
        self._last_flush: dict[str, float] = {s: 0.0 for s in SYMBOLS}
        self._loaded: set[tuple[str, date]] = set()
        self._index_ready = False
        self._collection_override: Any | None = None  # tests inject a fake collection here
        self.ticks_seen: dict[str, int] = {s: 0 for s in SYMBOLS}
        self.last_error: str | None = None

    # ------------------------------------------------------------------ storage helpers
    def _collection(self) -> Any:
        if self._collection_override is not None:
            return self._collection_override
        from lib.db import db  # imported lazily so this module has no import-time database dependency

        return db[COLLECTION]

    async def _ensure_index(self, collection: Any) -> None:
        if self._index_ready:
            return
        try:
            await collection.create_index([("symbol", 1), ("trading_day", 1), ("time", 1)], name="symbol_day_time")
        except Exception as exc:  # noqa: BLE001
            logger.warning("CANDLES_INDEX_ERROR %s: %s", type(exc).__name__, str(exc)[:160])
        self._index_ready = True

    async def _load_day(self, symbol: str, day: date) -> None:
        if (symbol, day) in self._loaded:
            return
        self._loaded.add((symbol, day))
        try:
            collection = self._collection()
            await self._ensure_index(collection)
            docs = await collection.find({"symbol": symbol, "trading_day": day.isoformat()}, {"_id": 0}).sort("time", 1).to_list(1000)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"load {type(exc).__name__}"
            logger.warning("CANDLES_LOAD_ERROR %s: %s", type(exc).__name__, str(exc)[:160])
            return
        bucket = self._today[symbol] if self._day[symbol] == day else {}
        for doc in docs:
            bucket.setdefault(int(doc["time"]), {k: doc[k] for k in ("time", "open", "high", "low", "close", "ticks")})
        if self._day[symbol] == day:
            self._today[symbol] = bucket
        if docs:
            logger.info("CANDLES_RESTORED symbol=%s day=%s candles=%s", symbol, day, len(docs))

    async def _flush(self, symbol: str, day: date, force: bool = False) -> None:
        dirty = self._dirty[symbol]
        if not dirty:
            return
        now = asyncio.get_running_loop().time()
        if not force and now - self._last_flush[symbol] < CURRENT_FLUSH_SECONDS:
            return
        self._last_flush[symbol] = now
        times, self._dirty[symbol] = sorted(dirty), set()
        try:
            collection = self._collection()
            for minute in times:
                candle = self._today[symbol].get(minute)
                if not candle:
                    continue
                await collection.update_one(
                    {"_id": f"{symbol}:{minute}"},
                    {"$set": {**candle, "symbol": symbol, "trading_day": day.isoformat(), "source": "KOTAK_NEO"}},
                    upsert=True,
                )
        except Exception as exc:  # noqa: BLE001
            self._dirty[symbol] |= set(times)  # retry on the next flush
            self.last_error = f"flush {type(exc).__name__}"
            logger.warning("CANDLES_FLUSH_ERROR %s: %s", type(exc).__name__, str(exc)[:160])

    # ------------------------------------------------------------------ ingest
    async def add_index_tick(self, name: str, ltp: float, token: str = "", at: datetime | None = None) -> None:
        symbol = symbol_for(name, token)
        if symbol is None or not ltp or ltp <= 0:
            return
        moment = (at or datetime.now(timezone.utc)).astimezone(IST)
        if not _in_session(moment):
            return
        day = moment.date()
        if self._day[symbol] != day:  # new trading day: start clean, then restore anything already stored
            self._today[symbol], self._dirty[symbol], self._day[symbol] = {}, set(), day
        await self._load_day(symbol, day)
        minute = int(moment.replace(second=0, microsecond=0).timestamp())
        bucket = self._today[symbol]
        candle = bucket.get(minute)
        rolled = False
        if candle is None:
            rolled = bool(bucket)  # a new minute after earlier ones means the previous candle just closed
            previous = max(bucket) if bucket else None
            bucket[minute] = {"time": minute, "open": ltp, "high": ltp, "low": ltp, "close": ltp, "ticks": 1}
            if previous is not None:
                self._dirty[symbol].add(previous)
        else:
            candle["high"] = max(candle["high"], ltp)
            candle["low"] = min(candle["low"], ltp)
            candle["close"] = ltp
            candle["ticks"] += 1
        self._dirty[symbol].add(minute)
        self.ticks_seen[symbol] += 1
        await self._flush(symbol, day, force=rolled)

    # ------------------------------------------------------------------ read
    async def get(self, symbol: str, interval: int = 1, day: date | None = None) -> dict[str, Any]:
        if symbol not in SYMBOLS:
            raise ValueError("unknown symbol")
        interval = interval if interval in INTERVALS else 1
        target = day or datetime.now(timezone.utc).astimezone(IST).date()
        if self._day[symbol] == target:
            await self._load_day(symbol, target)
            base = [dict(self._today[symbol][key]) for key in sorted(self._today[symbol])]
        else:
            try:
                collection = self._collection()
                docs = await collection.find({"symbol": symbol, "trading_day": target.isoformat()}, {"_id": 0}).sort("time", 1).to_list(1000)
                base = [{k: doc[k] for k in ("time", "open", "high", "low", "close", "ticks")} for doc in docs]
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"read {type(exc).__name__}"
                base = []
        return {
            "symbol": symbol,
            "interval": INTERVALS[interval],
            "trading_day": target.isoformat(),
            "source": "KOTAK_NEO",
            "candles": resample(base, interval),
            "note": None if base else "No live index ticks have been recorded for this day yet.",
        }


candle_store = CandleStore()
