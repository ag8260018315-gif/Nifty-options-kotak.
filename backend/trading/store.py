"""live_db persistence for the auto-trader."""
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


async def day_summary(live_db: Any, now: datetime) -> dict[str, Any]:
    day = now.astimezone(IST).date().isoformat()
    trades = await live_db.auto_trades.find({"trading_day": day}, {"_id": 0}).to_list(500)
    closed = [t for t in trades if t["status"] == "CLOSED"]
    return {
        "trading_day": day, "trades": len(trades), "open_positions": sum(t["status"] == "OPEN" for t in trades),
        "pnl": round(sum(t["pnl"] for t in closed), 2), "wins": sum(t["pnl"] > 0 for t in closed), "losses": sum(t["pnl"] <= 0 for t in closed),
        "signal_ids": {t["signal_id"] for t in trades},
    }


async def open_trades(live_db: Any) -> list[dict[str, Any]]:
    return await live_db.auto_trades.find({"status": "OPEN"}, {"_id": 0}).to_list(50)


async def save_trade(live_db: Any, trade: dict[str, Any]) -> None:
    await live_db.auto_trades.replace_one({"trade_id": trade["trade_id"]}, trade, upsert=True)


async def recent_trades(live_db: Any, limit: int = 30) -> list[dict[str, Any]]:
    return await live_db.auto_trades.find({}, {"_id": 0}).sort("opened_at", -1).limit(limit).to_list(limit)


async def is_killed(live_db: Any) -> tuple[bool, str | None]:
    doc = await live_db.trading_state.find_one({"_id": "state"})
    return (bool(doc and doc.get("killed")), doc.get("reason") if doc else None)


async def set_killed(live_db: Any, killed: bool, reason: str) -> None:
    await live_db.trading_state.update_one({"_id": "state"}, {"$set": {"killed": killed, "reason": reason}}, upsert=True)
