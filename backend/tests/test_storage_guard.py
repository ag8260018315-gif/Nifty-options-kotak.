"""A full free-plan database must neither block sign-in silently nor keep filling: snapshots are trimmed on their own,
the owner can see the usage, and a database error answers in plain words."""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import WriteError

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from jobs import research_scheduler  # noqa: E402
from lib import storage  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401

IST = ZoneInfo("Asia/Kolkata")
FULL_ERROR = WriteError("you are over your space quota, using 532 MB of 512 MB", code=8000)


def run(coro):
    return asyncio.run(coro)


def test_default_keeps_today_and_yesterday_only(monkeypatch):
    monkeypatch.delenv("SNAPSHOT_KEEP_DAYS", raising=False)
    live = AsyncMongoMockClient()["l"]

    async def go():
        await live.market_snapshot_history.insert_many([{"trading_day": d} for d in ("2026-10-10", "2026-10-13", "2026-10-14", "2026-10-15")])
        deleted = await research_scheduler.trim_snapshots(live, "2026-10-15")
        return deleted, sorted(await live.market_snapshot_history.distinct("trading_day"))

    assert run(go()) == (2, ["2026-10-14", "2026-10-15"])


def test_housekeeping_trims_and_only_squeezes_harder_when_the_plan_is_nearly_full(monkeypatch):
    monkeypatch.delenv("SNAPSHOT_KEEP_DAYS", raising=False)
    now = datetime(2026, 10, 15, 11, 0, tzinfo=IST)
    live, research = AsyncMongoMockClient()["l"], AsyncMongoMockClient()["r"]
    state = {"status": "OK"}

    async def fake_measure(handles):
        return {"limit_mb": 512.0, "used_mb": 300.0, "percent": 59, "status": state["status"], "databases": {}}

    monkeypatch.setattr(storage, "measure", fake_measure)

    async def go():
        await live.market_snapshot_history.insert_many([{"trading_day": d} for d in ("2026-10-13", "2026-10-14", "2026-10-15")])
        calm = await research_scheduler.housekeeping(live, research, now=now)
        left_after_calm = sorted(await live.market_snapshot_history.distinct("trading_day"))
        state["status"] = "HIGH"
        tight = await research_scheduler.housekeeping(live, research, now=now)
        return calm, left_after_calm, tight, sorted(await live.market_snapshot_history.distinct("trading_day"))

    calm, left_after_calm, tight, left_after_tight = run(go())
    assert calm["snapshots_trimmed"] == 1 and "emergency_trimmed" not in calm and left_after_calm == ["2026-10-14", "2026-10-15"]
    assert tight["emergency_trimmed"] == 1 and left_after_tight == ["2026-10-15"]  # today's snapshots are never touched


def test_the_quota_error_is_recognised_and_explained_in_plain_words():
    assert storage.is_storage_full(FULL_ERROR)
    assert storage.explain_db_error(FULL_ERROR) == storage.FULL_MESSAGE
    assert not storage.is_storage_full(WriteError("duplicate key", code=11000))
    assert storage.explain_db_error(WriteError("duplicate key", code=11000)) == storage.DOWN_MESSAGE


def test_measure_reports_status_and_survives_a_database_that_cannot_answer(monkeypatch):
    class Handle:
        def __init__(self, name, mb, fail=False):
            self.name, self.mb, self.fail = name, mb, fail

        async def command(self, _):
            if self.fail:
                raise RuntimeError("nope")
            return {"dataSize": self.mb * 1_048_576}

    monkeypatch.setenv("DB_LIMIT_MB", "512")
    same = Handle("a", 300)
    out = run(storage.measure({"app": same, "live": same, "research": Handle("b", 140)}))
    assert out["used_mb"] == 440.0 and out["status"] == "HIGH" and out["databases"] == {"a": 300.0, "b": 140.0}  # one database is counted once
    assert run(storage.measure({"x": Handle("c", 540)}))["status"] == "FULL"
    assert run(storage.measure({"x": Handle("d", 10, fail=True)})) is None


def test_sign_in_on_a_full_database_says_so_and_sends_no_dead_code(api, monkeypatch):
    from lib import access

    monkeypatch.setenv("SMTP_USERNAME", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    mailed = []

    async def fake_mail(to, subject, body):
        mailed.append(to)
        return True

    class FullCodes:
        async def find_one(self, *args, **kwargs):
            return None

        async def replace_one(self, *args, **kwargs):
            raise FULL_ERROR

    monkeypatch.setattr(access, "_send_mail", fake_mail)
    monkeypatch.setitem(access._collection_override, "access_codes", FullCodes())
    res = api.client.post("/api/access/request-code", json={"email": "owner@example.com"})
    assert res.status_code == 503 and res.json()["detail"] == storage.FULL_MESSAGE
    assert mailed == []  # the email goes out only after the code was saved


def test_a_failed_email_does_not_leave_a_code_or_use_up_the_resend_wait(api, monkeypatch):
    from lib import access

    monkeypatch.setenv("SMTP_USERNAME", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")

    async def mail_fails(to, subject, body):
        return False

    monkeypatch.setattr(access, "_send_mail", mail_fails)
    res = api.client.post("/api/access/request-code", json={"email": "owner@example.com"})
    assert res.status_code == 502
    assert run(api.db.access_codes.count_documents({})) == 0
    assert api.client.post("/api/access/request-code", json={"email": "owner@example.com"}).status_code == 502  # still a mail error, not "wait N seconds"


def test_owner_can_read_storage_usage(api, monkeypatch):
    async def fake_measure(handles):
        return {"limit_mb": 512.0, "used_mb": 100.0, "percent": 20, "status": "OK", "databases": {"t": 100.0}}

    monkeypatch.setattr(storage, "measure", fake_measure)
    assert api.client.get("/api/access/admin/storage").status_code in {401, 403}
    res = api.client.get("/api/access/admin/storage", headers=api.cookie("owner@example.com", "admin"))
    assert res.status_code == 200 and res.json()["status"] == "OK"
    assert api.client.get("/api/access/admin/storage", headers=api.cookie("viewer@example.com")).status_code == 403
