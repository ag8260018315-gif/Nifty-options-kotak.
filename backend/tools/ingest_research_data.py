"""The one explicit, one-way bridge from live storage to research storage.

Copies COMPLETED past trading days of index candles (never today) from live_db.index_candles into
research_db.candles, attaching the last recorded PCR of each minute. Neither engine imports this file.

  python tools/ingest_research_data.py --symbol NIFTY
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IST = ZoneInfo("Asia/Kolkata")


async def main(symbol: str) -> None:
    from lib.db import live_db, research_db
    from research.data import store_bars

    today = datetime.now(IST).date().isoformat()
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
    print(f"copied {total} bars from {len(days)} completed sessions for {symbol}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="NIFTY")
    asyncio.run(main(p.parse_args().symbol))
