"""research_db persistence: backtests, experiments, optimization results. Takes the db handle as an argument."""
from typing import Any

COLLECTIONS = ("backtests", "experiments", "optimization_results", "candles")


async def save_optimization(research_db: Any, report: dict[str, Any]) -> None:
    await research_db.optimization_results.replace_one({"_id": report["run_id"]}, {"_id": report["run_id"], **report}, upsert=True)


async def save_backtest(research_db: Any, doc: dict[str, Any]) -> None:
    await research_db.backtests.replace_one({"_id": doc["run_id"]}, {"_id": doc["run_id"], **doc}, upsert=True)


async def save_experiment(research_db: Any, doc: dict[str, Any]) -> None:
    await research_db.experiments.replace_one({"_id": doc["run_id"]}, {"_id": doc["run_id"], **doc}, upsert=True)


async def latest_optimization(research_db: Any, symbol: str | None = None) -> dict[str, Any] | None:
    query = {"symbol": symbol} if symbol else {}
    return await research_db.optimization_results.find_one(query, {"_id": 0}, sort=[("created_at", -1)])


async def list_optimizations(research_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    docs = research_db.optimization_results.find({}, {"_id": 0, "folds": 0, "config": 0}).sort("created_at", -1).limit(limit)
    return await docs.to_list(limit)
