"""Runs the stock signal back-test over stored 1-minute history and keeps one result per stock (plus an overall one)."""
import asyncio
from datetime import datetime, timezone
from typing import Any

from premium.signal_backtest import Rule, rule_dict, run_symbol, summarize_trades
from research import stock_history

COLLECTION = "signal_backtests"
DEFINITION = ("A trade opens when the engine says Bullish or Bearish with a setup, at the last close. It ends at target 1 (+R), the stop (-1R) or the time limit "
              "(marked to market); a candle touching both counts as a stop. One trade at a time per stock; a round-trip cost is charged.")


async def run_and_store(research_db: Any, rule: Rule, progress: Any = None) -> dict[str, Any] | None:
    symbols = await stock_history.symbols_with_data(research_db)
    if not symbols:
        return None
    all_trades: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()
    for number, symbol in enumerate(symbols, start=1):
        days = await stock_history.load_symbol(research_db, symbol)
        trades = await asyncio.to_thread(run_symbol, days, rule)  # CPU heavy: off the event loop
        all_trades.extend({**t, "symbol": symbol} for t in trades)
        doc = {"_id": symbol, "symbol": symbol, "created_at": now, "rule": rule_dict(rule), "definition": DEFINITION, "sessions": len(days), **summarize_trades(trades)}
        await research_db[COLLECTION].replace_one({"_id": symbol}, doc, upsert=True)
        if progress:
            progress(number, len(symbols), symbol, len(trades))
    overall = {"_id": "_overall", "symbol": "_overall", "created_at": now, "rule": rule_dict(rule), "definition": DEFINITION, "stocks_tested": len(symbols), **summarize_trades(all_trades)}
    await research_db[COLLECTION].replace_one({"_id": "_overall"}, overall, upsert=True)
    return overall


async def performance_for(research_db: Any, symbol: str) -> dict[str, Any]:
    """The stored result for one stock, the overall result, and an honest 'not tested' when there is none."""
    doc = await research_db[COLLECTION].find_one({"_id": symbol}, {"_id": 0})
    overall = await research_db[COLLECTION].find_one({"_id": "_overall"}, {"_id": 0})
    if not doc:
        return {"tested": False, "note": "This stock has no tested history yet (needs stored 1-minute candles).", "overall": overall}
    return {"tested": True, **doc, "overall": overall}
