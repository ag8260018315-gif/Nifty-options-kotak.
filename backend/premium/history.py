"""Stored multi-day candles for the index charts (collection `index_history` in the application database).
One document per (symbol, interval): parallel arrays, replaced on each import after merging by time.
Intervals: "30m" (intraday, anchored at 09:15) and "1d" (time = IST midnight)."""
from datetime import datetime, timezone
from typing import Any

COLLECTION = "index_history"
FIELDS = ("time", "open", "high", "low", "close", "volume")
CAPS = {"30m": 20000, "1d": 6000}  # most recent bars kept


def pack(symbol: str, interval: str, bars: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda b: b["time"])
    return {"_id": f"{symbol}:{interval}", "symbol": symbol, "interval": interval, "n": len(ordered),
            "updated_at": datetime.now(timezone.utc).isoformat(), **{f: [b.get(f, 0) for b in ordered] for f in FIELDS}}


def unpack(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [] if not doc else [dict(zip(FIELDS, row)) for row in zip(*(doc[f] for f in FIELDS))]


async def load(db: Any, symbol: str, interval: str) -> list[dict[str, Any]]:
    return unpack(await db[COLLECTION].find_one({"_id": f"{symbol}:{interval}"}, {"_id": 0}))


async def merge_save(db: Any, symbol: str, interval: str, bars: list[dict[str, Any]]) -> int:
    """Merge new bars into the stored ones (new wins on equal times), keep the most recent CAPS[interval]. Returns the stored count."""
    by_time = {b["time"]: b for b in await load(db, symbol, interval)}
    by_time.update({b["time"]: b for b in bars})
    merged = [by_time[t] for t in sorted(by_time)][-CAPS[interval]:]
    doc = pack(symbol, interval, merged)
    await db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return len(merged)
