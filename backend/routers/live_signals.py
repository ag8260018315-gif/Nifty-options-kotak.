"""LIVE SIGNAL routes. Only the live engine and live_db are used here; nothing from research except config.json (via the engine)."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from lib.candles import candle_store
from lib.db import live_db
from lib.feed_worker import feed_worker
from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from live import store
from live.engine import replay
from live.inputs import LiveInputs, from_snapshot
from live.runner import LiveSignalRunner
from models.dashboard import IndexSymbol
from shared.config import EngineConfig, load_config

router = APIRouter(prefix="/live", tags=["live-signals"])


async def provide_inputs(symbol: str) -> LiveInputs | None:
    if settings.mode == "LIVE":
        snapshot = feed_worker.snapshot_for(symbol)
        if snapshot is None or not snapshot.option_chain:
            return None
        status = feed_worker.status()
        index_status = next((i for i in status.indices if i.symbol == symbol), None)
        state = index_status.state if index_status else status.state
        if index_status and index_status.last_tick:
            snapshot = snapshot.model_copy(deep=True)
            snapshot.feed.last_tick = index_status.last_tick
    else:
        snapshot, state = demo_snapshot(symbol), "DEMO"
    candles = (await candle_store.get(symbol, 1))["candles"]
    return from_snapshot(snapshot, candles, state, datetime.now(timezone.utc))  # as_of is taken AFTER reading the data


runner = LiveSignalRunner(live_db, provide_inputs)


@router.get("/signal")
async def current_signal(symbol: IndexSymbol = Query(default="NIFTY")) -> dict:
    """The current LIVE signal, computed from current data only. Not research, not a backtest."""
    latest = runner.latest.get(symbol) if settings.mode == "LIVE" else None
    if latest and (datetime.now(timezone.utc) - datetime.fromisoformat(latest["as_of"])).total_seconds() < 30:
        return latest
    return await runner.evaluate(symbol, persist=False)


@router.get("/signals")
async def signal_history(symbol: IndexSymbol | None = Query(default=None), limit: int = Query(default=20, ge=1, le=100)) -> dict:
    return {"label": "LIVE SIGNAL HISTORY", "signals": await store.recent_signals(live_db, symbol, limit)}


@router.get("/signals/{signal_id}/replay")
async def replay_signal(signal_id: str) -> dict:
    """Recompute a stored signal using only the inputs and config saved with it, to show it is reproducible."""
    doc = await store.get_signal_with_inputs(live_db, signal_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Signal not found")
    return replay(doc, doc["inputs"], EngineConfig.model_validate(doc["config"]))


@router.get("/config")
async def live_config() -> dict:
    """The parameters the live engine is running with (read from config.json)."""
    cfg = load_config()
    return {**cfg.model_dump(mode="json"), "fingerprint": cfg.fingerprint()}
