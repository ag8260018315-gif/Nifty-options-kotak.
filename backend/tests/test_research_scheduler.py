"""Daily research job: copies finished days across the bridge, waits for enough data, runs once a day, applies only if asked."""
from datetime import datetime
from zoneinfo import ZoneInfo

from mongomock_motor import AsyncMongoMockClient

from jobs.research_scheduler import run_daily
from tests.test_engines_core import synthetic_days

IST = ZoneInfo("Asia/Kolkata")
WEEKDAY_EVENING = datetime(2026, 2, 10, 16, 0, tzinfo=IST)  # Tuesday, after 15:45


async def seed(live_db, n_days):
    for day, bars in synthetic_days(n_days).items():
        for b in bars:
            await live_db.index_candles.insert_one({**{k: b[k] for k in ("time", "open", "high", "low", "close")}, "symbol": "NIFTY", "trading_day": day, "ticks": 5})


async def test_waits_for_data_then_runs_once_per_day(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGINE_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setenv("RESEARCH_TRAIN_DAYS", "8")
    monkeypatch.setenv("RESEARCH_TEST_DAYS", "4")
    monkeypatch.setenv("RESEARCH_HORIZON_BARS", "10")
    client = AsyncMongoMockClient()
    live_db, research_db = client["live"], client["research"]
    await seed(live_db, 5)
    first = await run_daily(live_db, research_db, WEEKDAY_EVENING)
    assert first["ran"] and first["symbols"]["NIFTY"]["status"] == "WAITING_FOR_DATA" and first["symbols"]["NIFTY"]["sessions"] == 5
    assert await research_db.candles.count_documents({}) > 0 and await live_db.list_collection_names() != []
    assert (await run_daily(live_db, research_db, WEEKDAY_EVENING))["ran"] is False  # already ran today


async def test_not_before_close_or_on_weekends():
    client = AsyncMongoMockClient()
    live_db, research_db = client["live"], client["research"]
    assert (await run_daily(live_db, research_db, datetime(2026, 2, 10, 12, 0, tzinfo=IST)))["ran"] is False
    assert (await run_daily(live_db, research_db, datetime(2026, 2, 14, 16, 0, tzinfo=IST)))["ran"] is False  # Saturday


async def test_today_is_never_copied():
    client = AsyncMongoMockClient()
    live_db, research_db = client["live"], client["research"]
    await live_db.index_candles.insert_one({"time": 1, "open": 1, "high": 1, "low": 1, "close": 1, "symbol": "NIFTY", "trading_day": "2026-02-10"})
    out = await run_daily(live_db, research_db, WEEKDAY_EVENING)
    assert out["symbols"]["NIFTY"]["sessions"] == 0 and await research_db.candles.count_documents({}) == 0


async def test_runs_research_when_enough_sessions_and_applies_only_when_asked(monkeypatch, tmp_path):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("ENGINE_CONFIG_PATH", str(cfg_path))
    import shared.config as sc
    monkeypatch.setattr(sc, "CONFIG_PATH", cfg_path)
    for k, v in {"RESEARCH_TRAIN_DAYS": "8", "RESEARCH_TEST_DAYS": "4", "RESEARCH_HORIZON_BARS": "10"}.items():
        monkeypatch.setenv(k, v)
    client = AsyncMongoMockClient()
    live_db, research_db = client["live"], client["research"]
    await seed(live_db, 14)
    out = await run_daily(live_db, research_db, WEEKDAY_EVENING)
    nifty = out["symbols"]["NIFTY"]
    assert nifty["status"] in {"OK", "NO_OOS_SIGNALS"} and await research_db.optimization_results.count_documents({}) == 1
    assert not cfg_path.exists() and "config_written" not in nifty  # not applied unless RESEARCH_AUTO_APPLY=true
