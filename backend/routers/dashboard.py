from fastapi import APIRouter, HTTPException, Query

from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from models.dashboard import DashboardSnapshot, IndexSymbol


router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(symbol: IndexSymbol = Query(default="NIFTY")) -> DashboardSnapshot:
    if settings.mode == "LIVE":
        raise HTTPException(status_code=503, detail="Live Kotak market snapshot is unavailable until the SFeed worker is connected")
    return demo_snapshot(symbol)