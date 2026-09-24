from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from lib.feed_worker import feed_worker
from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from models.dashboard import (
    DashboardSnapshot,
    FeedHealth,
    FeedStatus,
    IndexSymbol,
    MarketStructure,
    SignalSnapshot,
    SpotSnapshot,
)


router = APIRouter(prefix="/market-data", tags=["market-data"])


def waiting_live_snapshot(status: FeedStatus) -> DashboardSnapshot:
    now = datetime.now(timezone.utc)
    return DashboardSnapshot(
        symbol="NIFTY",
        expiry=status.expiry or "Pending live contract",
        spot=SpotSnapshot(symbol="NIFTY", ltp=0, change=0, pct_change=0, high=0, low=0, timestamp=None),
        option_chain=[],
        structure=MarketStructure(pcr=0, max_pain=status.atm_strike or 0, bias="NEUTRAL", oi_buildup=status.message),
        signal=SignalSnapshot(recommendation="WAIT", confidence=0, reasons=[status.message], timestamp=None),
        feed=FeedHealth(
            state=status.state,
            source="KOTAK_NEO",
            last_tick=None,
            heartbeat_ms=0,
            subscriptions=status.subscriptions,
            divider_status="VERIFIED" if status.divider_verified else "PENDING",
        ),
        as_of=now,
    )


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(symbol: IndexSymbol = Query(default="NIFTY")) -> DashboardSnapshot:
    if settings.mode == "LIVE":
        if symbol != "NIFTY":
            raise HTTPException(status_code=503, detail="The first live SFeed worker currently supports NIFTY only")
        if not feed_worker.snapshot:
            return waiting_live_snapshot(feed_worker.status())
        snapshot = feed_worker.snapshot.model_copy(deep=True)
        status = feed_worker.status()
        snapshot.feed.state = status.state
        snapshot.feed.subscriptions = status.subscriptions
        snapshot.feed.divider_status = "VERIFIED" if status.divider_verified else "PENDING"
        if status.last_tick:
            snapshot.feed.last_tick = status.last_tick
            snapshot.feed.heartbeat_ms = max(0, int((datetime.now(timezone.utc) - status.last_tick).total_seconds() * 1000))
        return snapshot
    return demo_snapshot(symbol)


@router.get("/feed-status", response_model=FeedStatus)
async def get_feed_status() -> FeedStatus:
    return feed_worker.status()