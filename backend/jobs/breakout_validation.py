"""Runs the breakout back-test over stored history and keeps the latest result in research_db.breakout_backtests."""
import asyncio
from datetime import datetime, timezone
from typing import Any

from premium.backtest import Rule, run, summarize
from research import stock_history

COLLECTION = "breakout_backtests"


async def run_and_store(research_db: Any, rule: Rule) -> dict[str, Any] | None:
    symbols: dict[str, list] = {}
    for symbol in await stock_history.symbols_with_data(research_db):
        symbols[symbol] = await stock_history.load_symbol(research_db, symbol)
    if not symbols:
        return None
    sessions = len({day for days in symbols.values() for day, _ in days})
    records = await asyncio.to_thread(run, symbols, rule)  # CPU heavy: keep it off the event loop
    result = summarize(records, rule, sessions, len(symbols))
    result["created_at"] = datetime.now(timezone.utc).isoformat()
    await research_db[COLLECTION].replace_one({"_id": "latest"}, {"_id": "latest", **result}, upsert=True)
    return result


async def latest(research_db: Any) -> dict[str, Any] | None:
    return await research_db[COLLECTION].find_one({"_id": "latest"}, {"_id": 0})
