"""Daily after the close (default 15:45 IST, weekdays): copy the finished day into research storage, then run the
research once enough sessions exist. The report is stored in research_db. config.json is only written when
RESEARCH_AUTO_APPLY=true (default false: the owner applies a result on purpose)."""
import asyncio
import logging
import os
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from jobs.bridge import ingest_symbol
from lib import storage
from research import data, store
from research.optimize import optimize
from shared.config import EngineConfig, load_config, save_config

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
RUN_AFTER = time(15, 45)
CHECK_SECONDS = 600


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


async def _delete_snapshots_before(live_db: Any, cutoff_day: str) -> int:
    result = await live_db.market_snapshot_history.delete_many({"trading_day": {"$lt": cutoff_day}})
    return int(result.deleted_count)


async def trim_snapshots(live_db: Any, today: str, keep_days: int | None = None) -> int:
    """Delete 5-second option-chain snapshots older than SNAPSHOT_KEEP_DAYS calendar days (default 1 = today and yesterday;
    0 turns it off). One trading day is about 60 MB, so on a 512 MB plan only the most recent days can be kept; the daily
    copy into research needs just the day before."""
    keep = _int("SNAPSHOT_KEEP_DAYS", 1) if keep_days is None else keep_days
    if keep <= 0:
        return 0
    return await _delete_snapshots_before(live_db, (datetime.fromisoformat(today) - timedelta(days=keep)).date().isoformat())


async def housekeeping(live_db: Any, research_db: Any, app_db: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Runs every few minutes, independent of the nightly research job (which can stop early): trims old snapshots, then, if
    the database is close to the plan limit, keeps only today's snapshots so a full database never blocks sign-in."""
    day = (now or datetime.now(IST)).astimezone(IST).date().isoformat()
    out: dict[str, Any] = {}
    try:
        out["snapshots_trimmed"] = await trim_snapshots(live_db, day)
    except Exception as exc:  # noqa: BLE001
        out["snapshots_trimmed"] = f"error {type(exc).__name__}"
    usage = await storage.measure({"app": app_db if app_db is not None else live_db, "live": live_db, "research": research_db})
    if usage is not None:
        out["storage"] = usage
        if usage["status"] != "OK":
            try:
                out["emergency_trimmed"] = await _delete_snapshots_before(live_db, day)
            except Exception as exc:  # noqa: BLE001
                out["emergency_trimmed"] = f"error {type(exc).__name__}"
            logger.warning("STORAGE_%s used_mb=%s limit_mb=%s percent=%s trimmed=%s", usage["status"], usage["used_mb"], usage["limit_mb"], usage["percent"], out["emergency_trimmed"])
    return out


async def run_daily(live_db: Any, research_db: Any, now: datetime | None = None) -> dict[str, Any]:
    """One pass. Safe to call repeatedly: it does nothing if it already ran for this IST day."""
    now = (now or datetime.now(IST)).astimezone(IST)
    day = now.date().isoformat()
    state = await research_db.job_state.find_one({"_id": "daily"}) or {}
    if now.weekday() >= 5 or now.time() < RUN_AFTER or state.get("last_run_day") == day:
        return {"ran": False}
    train, test, horizon = _int("RESEARCH_TRAIN_DAYS", 10), _int("RESEARCH_TEST_DAYS", 3), _int("RESEARCH_HORIZON_BARS", 15)
    summary: dict[str, Any] = {"ran": True, "day": day, "symbols": {}}
    for symbol in SYMBOLS:
        copied, _ = await ingest_symbol(live_db, research_db, symbol, today=day)
        days = await data.load_days(research_db, symbol, before_day=day)
        entry: dict[str, Any] = {"bars_copied": copied, "sessions": len(days), "status": "WAITING_FOR_DATA"}
        if len(days) >= train + test:
            report = await asyncio.to_thread(optimize, days, load_config(), horizon, train, test, None, symbol)
            await store.save_optimization(research_db, report)
            entry["status"] = report["status"]
            if report["status"] == "OK" and symbol == "NIFTY" and os.environ.get("RESEARCH_AUTO_APPLY", "false").lower() == "true":
                save_config(EngineConfig.model_validate(report["config"]))
                entry["config_written"] = True
        summary["symbols"][symbol] = entry
    await research_db.job_state.update_one({"_id": "daily"}, {"$set": {"last_run_day": day, "summary": summary}}, upsert=True)
    logger.info("RESEARCH_DAILY %s", summary)
    return summary


async def run_forever(live_db: Any, research_db: Any, app_db: Any = None) -> None:
    while True:
        try:
            await housekeeping(live_db, research_db, app_db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("HOUSEKEEPING_ERROR kind=%s", type(exc).__name__)
        try:
            await run_daily(live_db, research_db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  a research problem must never disturb the app
            logger.warning("RESEARCH_DAILY_ERROR kind=%s", type(exc).__name__)
        await asyncio.sleep(CHECK_SECONDS)
