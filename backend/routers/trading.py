"""Auto-trader status and kill switch. PAPER mode by default: nothing here sends an order to a broker."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from lib.access import require_admin
from lib.db import live_db
from routers.live_signals import provide_inputs, runner as signal_runner
from trading import store
from trading.brokers import BrokerNotVerified, build_broker
from trading.runner import AutoTrader
from trading.settings import TradingSettings

router = APIRouter(prefix="/trading", tags=["trading"])
settings = TradingSettings.from_env()
try:
    broker = build_broker(settings)
    broker_error = None
except BrokerNotVerified as exc:  # LIVE refused: fall back to OFF so nothing can place an order
    broker, broker_error = None, str(exc)
    settings = TradingSettings(**{**settings.__dict__, "mode": "OFF"})
trader = AutoTrader(live_db, provide_inputs, signal_runner.latest, broker, settings) if broker else None


@router.get("/status")
async def status() -> dict:
    killed, reason = await store.is_killed(live_db)
    day = await store.day_summary(live_db, datetime.now(timezone.utc))
    day.pop("signal_ids")
    return {"label": "AUTO-TRADER", "mode": settings.mode, "real_orders": False, "broker_error": broker_error, "killed": killed, "kill_reason": reason,
            "settings": settings.public(), "today": day, "open_positions": await store.open_trades(live_db)}


@router.get("/trades")
async def trades(limit: int = Query(default=30, ge=1, le=200)) -> dict:
    return {"label": "AUTO-TRADER", "trades": await store.recent_trades(live_db, limit)}


@router.post("/kill", dependencies=[Depends(require_admin)])
async def kill() -> dict:
    await store.set_killed(live_db, True, "Stopped by the owner")
    return {"killed": True}


@router.post("/resume", dependencies=[Depends(require_admin)])
async def resume() -> dict:
    await store.set_killed(live_db, False, "")
    return {"killed": False}
