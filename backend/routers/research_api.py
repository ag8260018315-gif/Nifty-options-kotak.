"""RESEARCH / HISTORICAL ANALYSIS routes. Only the research engine and research_db are used here."""
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.access import require_admin
from lib.db import research_db
from models.dashboard import IndexSymbol
from research import data, store
from research.optimize import optimize
from shared.config import EngineConfig, load_config, save_config

router = APIRouter(prefix="/research", tags=["research"])
LABEL = "RESEARCH / HISTORICAL ANALYSIS"


class RunRequest(BaseModel):
    symbol: IndexSymbol = "NIFTY"
    horizon_bars: int = Field(default=15, ge=1, le=120)
    train_days: int = Field(default=10, ge=3, le=60)
    test_days: int = Field(default=3, ge=1, le=20)
    apply: bool = False  # write the resulting parameters to config.json for the live engine


@router.get("/summary")
async def summary(symbol: IndexSymbol = Query(default="NIFTY")) -> dict[str, Any]:
    latest = await store.latest_optimization(research_db, symbol)
    cfg = load_config()
    return {"label": LABEL, "symbol": symbol, "latest_run": latest, "active_config_validation": cfg.validation.model_dump() if cfg.validation else None,
            "active_config_generated_by": cfg.generated_by, "calibration": [c.model_dump() for c in cfg.calibration]}


@router.get("/runs")
async def runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    return {"label": LABEL, "runs": await store.list_optimizations(research_db, limit)}


@router.post("/run", dependencies=[Depends(require_admin)])
async def run_research(request: RunRequest) -> dict[str, Any]:
    days = await data.load_days(research_db, request.symbol)
    report = await asyncio.to_thread(optimize, days, load_config(), request.horizon_bars, request.train_days, request.test_days, None, request.symbol)
    await store.save_optimization(research_db, report)
    report["config_written"] = False
    if request.apply:
        if report["status"] != "OK":
            raise HTTPException(status_code=409, detail=f"Config not written: {report['status']}")
        save_config(EngineConfig.model_validate(report["config"]))
        report["config_written"] = True
    return {"label": LABEL, **report}


@router.post("/apply", dependencies=[Depends(require_admin)])
async def apply_latest(symbol: IndexSymbol = Query(default="NIFTY")) -> dict[str, Any]:
    """Writes the latest successful research result to config.json (the live engine reads it on its next cycle)."""
    latest = await store.latest_optimization(research_db, symbol)
    if not latest or latest.get("status") != "OK" or not latest.get("config"):
        raise HTTPException(status_code=409, detail="No successful research result to apply yet.")
    save_config(EngineConfig.model_validate(latest["config"]))
    return {"applied": True, "run_id": latest["run_id"], "validation": latest["validation"]}
