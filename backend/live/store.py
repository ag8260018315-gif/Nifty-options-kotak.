"""live_db persistence: signals and signal outcomes. Takes the db handle as an argument (pass `live_db`)."""
from datetime import datetime
from typing import Any

from live.inputs import LiveInputs
from shared.config import EngineConfig


async def save_signal(live_db: Any, signal: dict[str, Any], inputs: LiveInputs, cfg: EngineConfig) -> bool:
    """Stores the signal with the exact inputs and config that produced it, so it can be replayed."""
    doc = {**signal, "inputs": inputs.to_doc(), "config": cfg.signal_params(), "created_at": datetime.fromisoformat(signal["as_of"])}
    doc["signal_id"] = signal["signal_id"]
    result = await live_db.live_signals.update_one({"signal_id": doc["signal_id"]}, {"$setOnInsert": doc}, upsert=True)
    return result.upserted_id is not None


async def recent_signals(live_db: Any, symbol: str | None, limit: int = 20) -> list[dict[str, Any]]:
    query = {"symbol": symbol} if symbol else {}
    docs = await live_db.live_signals.find(query, {"_id": 0, "inputs": 0, "config": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    outcomes = {o["signal_id"]: o async for o in live_db.signal_outcomes.find({"signal_id": {"$in": [d["signal_id"] for d in docs]}}, {"_id": 0})}
    for d in docs:
        d["outcome"] = outcomes.get(d["signal_id"])
        d.pop("created_at", None)
    return docs


async def last_signal_time(live_db: Any, symbol: str) -> datetime | None:
    doc = await live_db.live_signals.find_one({"symbol": symbol}, {"created_at": 1}, sort=[("created_at", -1)])
    return doc["created_at"] if doc else None


async def get_signal_with_inputs(live_db: Any, signal_id: str) -> dict[str, Any] | None:
    return await live_db.live_signals.find_one({"signal_id": signal_id}, {"_id": 0})


async def open_signals(live_db: Any, symbol: str) -> list[dict[str, Any]]:
    docs = await live_db.live_signals.find({"symbol": symbol, "action": {"$in": ["BUY CE", "BUY PE"]}}, {"_id": 0, "inputs": 0}).sort("created_at", -1).limit(50).to_list(50)
    done = {o["signal_id"] async for o in live_db.signal_outcomes.find({"signal_id": {"$in": [d["signal_id"] for d in docs]}}, {"signal_id": 1})}
    return [d for d in docs if d["signal_id"] not in done]


async def save_outcome(live_db: Any, outcome: dict[str, Any]) -> None:
    await live_db.signal_outcomes.update_one({"signal_id": outcome["signal_id"]}, {"$setOnInsert": outcome}, upsert=True)
