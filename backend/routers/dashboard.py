from fastapi import APIRouter, Query

from lib.kotak_adapter import demo_snapshot
from models.dashboard import DashboardSnapshot, IndexSymbol


router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(symbol: IndexSymbol = Query(default="NIFTY")) -> DashboardSnapshot:
    return demo_snapshot(symbol)