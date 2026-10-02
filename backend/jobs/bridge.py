"""The explicit one-way bridge: completed past days of live candles -> research storage. Never today's session."""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from research.data import store_bars

IST = ZoneInfo("Asia/Kolkata")


async def ingest_symbol(live_db: Any, research_db: Any, symbol: str, today: str | None = None) -> tuple[int, int]:
    """Copies completed days (before `today`, IST) with the last recorded PCR of each minute. Idempotent.
    Returns (bars copied, days seen)."""
    today = today or datetime.now(IST).date().isoformat()
    days = await live_db.index_candles.distinct("trading_day", {"symbol": symbol, "trading_day": {"$lt": today}})
    total = 0
    for day in sorted(days):
        bars = await live_db.index_candles.find({"symbol": symbol, "trading_day": day}, {"_id": 0}).sort("time", 1).to_list(None)
        pcr_by_minute: dict[int, float] = {}
        async for doc in live_db.market_snapshot_history.find({"symbol": symbol, "trading_day": day}, {"captured_at": 1, "snapshot.structure.pcr": 1}).sort("captured_at", 1):
            pcr = doc.get("snapshot", {}).get("structure", {}).get("pcr")
            if pcr:
                pcr_by_minute[int(doc["captured_at"].timestamp()) // 60 * 60] = float(pcr)
        clean = [{k: b[k] for k in ("time", "open", "high", "low", "close")} | ({"pcr": pcr_by_minute[b["time"]]} if b["time"] in pcr_by_minute else {}) for b in bars]
        total += await store_bars(research_db, symbol, clean, source="live_db.index_candles")
    return total, len(days)
