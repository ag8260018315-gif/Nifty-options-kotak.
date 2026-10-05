import os

import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from premium import alerts as al  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401

UNI = {"TCS", "INFY"}


def test_validation_and_pure_conditions():
    assert al.clean_rule({"symbol": "tcs", "kind": "price_above", "value": "4000"}, UNI)["value"] == 4000.0
    for bad in ({"symbol": "NOPE", "kind": "price_above", "value": 1}, {"symbol": "TCS", "kind": "x"}, {"symbol": "TCS", "kind": "price_above", "value": "abc"},
                {"symbol": "TCS", "kind": "price_below", "value": -5}, {"symbol": "TCS", "kind": "volume_spike", "value": 500}, {"symbol": "TCS", "kind": "price_above", "value": float("nan")}):
        with pytest.raises(HTTPException):
            al.clean_rule(bad, UNI)
    q = {"ltp": 4010, "change_pct": 2.5}
    assert al.triggered({"symbol": "TCS", "kind": "price_above", "value": 4000}, q, None)
    assert al.triggered({"symbol": "TCS", "kind": "price_below", "value": 4000}, q, None) is None
    assert al.triggered({"symbol": "TCS", "kind": "change_pct_above", "value": 2}, q, None)
    assert al.triggered({"symbol": "TCS", "kind": "price_above", "value": 1}, None, None) is None
    assert al.triggered({"symbol": "TCS", "kind": "bias_bullish"}, q, {"action": "BUY"}) and al.triggered({"symbol": "TCS", "kind": "bias_bullish"}, q, {"action": "SELL"}) is None
    assert al.triggered({"symbol": "TCS", "kind": "volume_spike", "value": 3}, q, {"relative_volume": 3.4})


async def test_fire_once_never_on_stale_data_cooldown_and_email_and_cap():
    db = AsyncMongoMockClient()["a"]
    r1 = await al.add_rule(db, "u@x.com", {"symbol": "TCS", "kind": "price_above", "value": 4000, "once": True, "email": True}, UNI)
    r2 = await al.add_rule(db, "u@x.com", {"symbol": "INFY", "kind": "price_below", "value": 1500, "once": False}, UNI)
    prices = {"TCS": {"ltp": 4100, "change_pct": 1}, "INFY": {"ltp": 1400, "change_pct": -1}}
    sent = []

    async def mail(to, subject, body):
        sent.append((to, subject))
        return True

    async def quick(symbol):
        return {}

    live = {"TCS": False, "INFY": False}
    assert await al.evaluate(db, prices.get, quick, lambda s: live[s], mail, now=1000) == 0       # stale / closed: never alerts
    live.update(TCS=True, INFY=True)
    assert await al.evaluate(db, prices.get, quick, lambda s: live[s], mail, now=1000) == 2
    assert len(sent) == 1 and sent[0][0] == "u@x.com" and "TCS" in sent[0][1]                      # only the email-flagged rule mails
    assert await al.evaluate(db, prices.get, quick, lambda s: live[s], mail, now=1010) == 0       # once-rule is off; repeat rule is disarmed
    prices["INFY"] = {"ltp": 1600, "change_pct": 0}
    await al.evaluate(db, prices.get, quick, lambda s: live[s], mail, now=1020)                   # condition cleared -> re-armed
    prices["INFY"] = {"ltp": 1400, "change_pct": 0}
    assert await al.evaluate(db, prices.get, quick, lambda s: live[s], mail, now=1030) == 0       # still inside the 30 minute cooldown
    assert await al.evaluate(db, prices.get, quick, lambda s: live[s], mail, now=1030 + al.COOLDOWN + 1) == 1
    ev = await al.list_events(db, "u@x.com")
    assert ev["unread"] == 3 and (await al.list_events(db, "other@x.com"))["events"] == []
    await al.mark_read(db, "u@x.com")
    assert (await al.list_events(db, "u@x.com"))["unread"] == 0
    for _ in range(al.MAX_RULES - 2):
        await al.add_rule(db, "u@x.com", {"symbol": "TCS", "kind": "bias_bullish"}, UNI)
    with pytest.raises(HTTPException):
        await al.add_rule(db, "u@x.com", {"symbol": "TCS", "kind": "bias_bullish"}, UNI)
    assert r1["_id"] != r2["_id"]


def test_api_is_per_user_and_premium_only(api):
    owner, other, free = api.cookie("paid@example.com"), api.cookie("owner@example.com"), api.cookie("viewer@example.com")
    r = api.client.post("/api/premium/me/alerts", json={"symbol": "TCS", "kind": "price_above", "value": 5000}, headers=owner)
    assert r.status_code == 200 and len(r.json()["alerts"]) == 1
    rid = r.json()["alerts"][0]["id"]
    assert api.client.get("/api/premium/me/alerts", headers=other).json()["alerts"] == []
    assert api.client.patch(f"/api/premium/me/alerts/{rid}", json={"active": False}, headers=other).status_code == 404   # cannot touch another user's alert
    assert api.client.patch(f"/api/premium/me/alerts/{rid}", json={"active": False}, headers=owner).json()["alerts"][0]["active"] is False
    assert api.client.post("/api/premium/me/alerts", json={"symbol": "NOPE", "kind": "price_above", "value": 1}, headers=owner).status_code == 422
    assert api.client.get("/api/premium/me/alerts", headers=free).status_code == 403
    assert api.client.get("/api/premium/me/alert-events", headers=owner).json() == {"events": [], "unread": 0}
    assert api.client.delete(f"/api/premium/me/alerts/{rid}", headers=owner).json()["alerts"] == []
