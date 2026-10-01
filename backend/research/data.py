"""Historical inputs for research: bars grouped by trading day, read from research_db or a CSV file."""
import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
BAR_FIELDS = ("time", "open", "high", "low", "close")


def _day_of(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, IST).date().isoformat()


def group_by_day(bars: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    days: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for bar in sorted(bars, key=lambda b: b["time"]):
        days[_day_of(int(bar["time"]))].append(bar)
    return dict(sorted(days.items()))


def load_csv(path: Path | str) -> list[dict[str, Any]]:
    """CSV columns: time (epoch seconds or ISO-8601 with offset), open, high, low, close[, pcr]."""
    bars: list[dict[str, Any]] = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            raw = row["time"].strip()
            epoch = int(raw) if raw.isdigit() else int(datetime.fromisoformat(raw).timestamp())
            bar: dict[str, Any] = {"time": epoch, **{k: float(row[k]) for k in BAR_FIELDS[1:]}}
            if row.get("pcr") not in (None, ""):
                bar["pcr"] = float(row["pcr"])
            bars.append(bar)
    return bars


async def load_days(research_db: Any, symbol: str, before_day: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Completed trading days stored in research_db.candles. `before_day` excludes that day and later."""
    query: dict[str, Any] = {"symbol": symbol}
    if before_day:
        query["trading_day"] = {"$lt": before_day}
    docs = await research_db.candles.find(query, {"_id": 0}).sort("time", 1).to_list(None)
    return group_by_day(docs)


async def store_bars(research_db: Any, symbol: str, bars: list[dict[str, Any]], source: str) -> int:
    """Idempotent upsert of historical bars into research_db.candles."""
    for bar in bars:
        await research_db.candles.update_one(
            {"_id": f"{symbol}:{int(bar['time'])}"},
            {"$set": {**bar, "symbol": symbol, "trading_day": _day_of(int(bar["time"])), "source": source}},
            upsert=True,
        )
    return len(bars)
