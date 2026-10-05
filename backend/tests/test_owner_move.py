import os

import pytest
from mongomock_motor import AsyncMongoMockClient

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from lib.owner_move import move_owner_data  # noqa: E402

OLD, NEW = "old@gmail.com", "admin@edgedesk.in"


async def seed(db):
    await db.premium_watchlists.insert_one({"_id": OLD, "lists": {"Favourites": ["TCS"], "Banks": ["HDFCBANK"]}})
    await db.premium_watchlists.insert_one({"_id": NEW, "lists": {"Favourites": ["INFY"]}})
    await db.premium_layouts.insert_one({"_id": OLD, "layouts": {"Main": {"interval": 5}}})
    await db.premium_alerts.insert_one({"_id": "a1", "owner": OLD})
    await db.exchange_profiles.insert_one({"_id": OLD, "name": "Ravi"})
    await db.exchange_threads.insert_one({"_id": "t1", "buyer": "x@x.com", "seller": OLD})
    await db.premium_alerts.insert_one({"_id": "a2", "owner": "other@x.com"})


async def test_dry_run_changes_nothing_then_apply_moves_and_merges():
    db = AsyncMongoMockClient()["x"]
    await seed(db)
    report = await move_owner_data(db, OLD, NEW, apply=False)
    assert report["premium_watchlists"] == 2 and report["premium_alerts.owner"] == 1
    assert (await db.premium_alerts.find_one({"_id": "a1"}))["owner"] == OLD and await db.premium_layouts.find_one({"_id": OLD})
    await move_owner_data(db, OLD, NEW, apply=True)
    lists = (await db.premium_watchlists.find_one({"_id": NEW}))["lists"]
    assert lists == {"Favourites": ["INFY"], "Banks": ["HDFCBANK"]}                  # merged; the new email's own list wins a name clash
    assert await db.premium_watchlists.find_one({"_id": OLD}) is None
    assert (await db.premium_layouts.find_one({"_id": NEW}))["layouts"] == {"Main": {"interval": 5}}
    assert (await db.premium_alerts.find_one({"_id": "a1"}))["owner"] == NEW and (await db.premium_alerts.find_one({"_id": "a2"}))["owner"] == "other@x.com"
    assert (await db.exchange_profiles.find_one({"_id": NEW}))["name"] == "Ravi"
    assert (await db.exchange_threads.find_one({"_id": "t1"}))["seller"] == NEW


async def test_rejects_bad_input_and_keeps_existing_profile():
    db = AsyncMongoMockClient()["x"]
    await db.exchange_profiles.insert_one({"_id": OLD, "name": "Ravi"})
    await db.exchange_profiles.insert_one({"_id": NEW, "name": "Chief"})
    with pytest.raises(ValueError):
        await move_owner_data(db, OLD, OLD, apply=True)
    await move_owner_data(db, OLD, NEW, apply=True)
    assert (await db.exchange_profiles.find_one({"_id": NEW}))["name"] == "Chief"    # never overwritten
