"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, IndexModel

load_dotenv(Path(__file__).parent.parent / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

# Two separate stores that must never be mixed. `live_db` holds live ticks, option chains, signals and signal
# outcomes (by default the existing application database, which already holds them). `research_db` is a different
# database holding backtests, experiments, optimisation results and historical bars.
live_db = client[os.environ.get("LIVE_DB_NAME", os.environ["DB_NAME"])]
research_db = client[os.environ.get("RESEARCH_DB_NAME", os.environ["DB_NAME"] + "_research")]

logger = logging.getLogger(__name__)

# One entry per collection: every field a route filters, sorts, or dedupes on. Applied by ensure_indexes() at startup.
INDEXES: dict[str, list[IndexModel]] = {
    "kotak_sessions": [IndexModel([("updated_at", DESCENDING)], name="updated_at_desc")],
    "market_snapshots": [IndexModel([("symbol", ASCENDING), ("as_of", DESCENDING)], name="symbol_as_of")],
    "ai_messages": [IndexModel([("session_id", ASCENDING), ("created_at", DESCENDING)], name="session_created")],
    "ai_summaries": [IndexModel([("symbol", ASCENDING), ("created_at", DESCENDING)], name="symbol_created")],
    "ai_alerts": [IndexModel([("symbol", ASCENDING), ("created_at", DESCENDING)], name="symbol_created")],
    "feed_alerts": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
    ],
    "opening_reports": [IndexModel([("session_date", ASCENDING)], name="session_date", unique=True)],
    "market_snapshot_history": [
        IndexModel([("trading_day", ASCENDING), ("symbol", ASCENDING), ("captured_at", ASCENDING)], name="day_symbol_captured"),
    ],
    "live_signals": [
        IndexModel([("signal_id", ASCENDING)], name="signal_id", unique=True),
        IndexModel([("symbol", ASCENDING), ("as_of", DESCENDING)], name="symbol_as_of"),
    ],
    "signal_outcomes": [IndexModel([("signal_id", ASCENDING)], name="signal_id", unique=True)],
    "export_manifests": [IndexModel([("trading_day", ASCENDING)], name="trading_day", unique=True)],
    # premium stock/SENSEX minute candles: read by (symbol, day) to restore a day, find the previous or last session and fill history gaps
    "premium_alerts": [IndexModel([("owner", ASCENDING), ("created_at", DESCENDING)], name="owner_created"), IndexModel([("active", ASCENDING)], name="active")],
    "premium_alert_events": [IndexModel([("owner", ASCENDING), ("at", DESCENDING)], name="owner_at")],
    "premium_candles": [IndexModel([("symbol", ASCENDING), ("trading_day", ASCENDING), ("time", ASCENDING)], name="symbol_day_time")],
}


RESEARCH_INDEXES: dict[str, list[IndexModel]] = {
    "stock_days": [IndexModel([("symbol", ASCENDING), ("trading_day", ASCENDING)], name="symbol_day")],
    "candles": [IndexModel([("symbol", ASCENDING), ("time", ASCENDING)], name="symbol_time")],
    "optimization_results": [IndexModel([("created_at", DESCENDING)], name="created_at_desc")],
}
LIVE_ONLY = {"live_signals", "signal_outcomes"}  # new collections that belong to live_db


async def ensure_indexes() -> None:
    plan = [(live_db if c in LIVE_ONLY else db, c, m) for c, m in INDEXES.items()] + [(research_db, c, m) for c, m in RESEARCH_INDEXES.items()]
    for handle, collection, models in plan:
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await handle[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
