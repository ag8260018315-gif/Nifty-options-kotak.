"""Compact storage of historical stock sessions in research_db.stock_days: one document per (symbol, trading day)
holding parallel arrays, so months of 1-minute candles for many stocks stay small."""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
COLLECTION = "stock_days"
FIELDS = ("time", "open", "high", "low", "close", "volume")


def day_of(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, IST).date().isoformat()


def pack(symbol: str, trading_day: str, bars: list[dict[str, Any]], source: str) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda b: b["time"])
    return {"_id": f"{symbol}:{trading_day}", "symbol": symbol, "trading_day": trading_day, "source": source, "n": len(ordered),
            **{f: [b[f] for b in ordered] for f in FIELDS}}


def unpack(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(zip(FIELDS, row)) for row in zip(*(doc[f] for f in FIELDS))]


def group_by_day(bars: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    days: dict[str, list[dict[str, Any]]] = {}
    for bar in sorted(bars, key=lambda b: b["time"]):
        days.setdefault(day_of(int(bar["time"])), []).append(bar)
    return days


async def save_days(research_db: Any, symbol: str, bars: list[dict[str, Any]], source: str) -> int:
    """Idempotent: re-importing a day replaces its document."""
    days = group_by_day(bars)
    for day, items in days.items():
        doc = pack(symbol, day, items, source)
        await research_db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return len(days)


async def stored_days(research_db: Any, symbol: str) -> set[str]:
    docs = research_db[COLLECTION].find({"symbol": symbol}, {"trading_day": 1})
    return {d["trading_day"] async for d in docs}


async def load_symbol(research_db: Any, symbol: str) -> list[tuple[str, list[dict[str, Any]]]]:
    docs = await research_db[COLLECTION].find({"symbol": symbol}, {"_id": 0}).sort("trading_day", 1).to_list(None)
    return [(d["trading_day"], unpack(d)) for d in docs]


async def symbols_with_data(research_db: Any) -> list[str]:
    return sorted(await research_db[COLLECTION].distinct("symbol"))
