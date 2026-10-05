import os

import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from exchange import rules, store  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401

GOOD = {"title": "Options basics course", "category": "education", "description": "Eight recorded lessons that explain how options are priced and how risk works. Education only.", "price_text": "₹999", "accept": True}


@pytest.fixture(autouse=True)
def _fresh_limits():
    rules.limiter._hits.clear()


def test_wording_and_contact_rules():
    assert rules.clean_listing(GOOD)["title"] == "Options basics course"
    for bad in ("Daily intraday tips for you", "Guaranteed 20% returns every month", "Portfolio management service", "Join VIP calls group", "Paid signals channel", "Sure shot winners",
                "Reach me at me@example.com", "Call 98765 43210 now", "Chat on WhatsApp", "See www.example.com", "Investment advice for beginners", "Double your money fast"):
        with pytest.raises(HTTPException) as e:
            rules.clean_listing({**GOOD, "description": GOOD["description"] + " " + bad})
        assert e.value.status_code == 422, bad
    assert rules.clean_listing({**GOOD, "description": GOOD["description"] + " Covers call options and put options."})  # ordinary education wording is fine
    for field, value in (("accept", False), ("category", "tips"), ("title", "abc"), ("description", "too short")):
        with pytest.raises(HTTPException):
            rules.clean_listing({**GOOD, field: value})
    for bad in ("ab", "me@x.com", "Edgedesk Support", "x" * 30, "!!!"):
        with pytest.raises(HTTPException):
            rules.clean_name(bad)
    assert rules.clean_name("Asha K") == "Asha K"


async def test_listing_lifecycle_privacy_and_caps():
    db = AsyncMongoMockClient()["x"]
    with pytest.raises(HTTPException):
        await store.create_listing(db, "a@x.com", GOOD)                      # needs a display name first
    await store.set_profile(db, "a@x.com", "Asha")
    with pytest.raises(HTTPException) as taken:
        await store.set_profile(db, "b@x.com", "asha")
    assert taken.value.status_code == 409
    await store.set_profile(db, "b@x.com", "Ben")
    doc = await store.create_listing(db, "a@x.com", GOOD, now=1000)
    assert await store.browse(db, "b@x.com", None, None) == []               # nothing is public until approved
    with pytest.raises(HTTPException):
        await store.get_listing(db, "b@x.com", doc["_id"])
    assert (await store.get_listing(db, "a@x.com", doc["_id"]))["status"] == "pending"
    await store.decide(db, doc["_id"], "approve")
    seen = await store.browse(db, "b@x.com", None, None)
    assert len(seen) == 1 and seen[0]["seller_name"] == "Asha" and "owner" not in seen[0] and "a@x.com" not in str(seen)
    assert await store.browse(db, "b@x.com", "tools", None) == [] and len(await store.browse(db, "b@x.com", None, "options")) == 1
    await store.edit_listing(db, "a@x.com", doc["_id"], {**GOOD, "title": "Options basics, updated"})
    assert await store.browse(db, "b@x.com", None, None) == []               # an edit goes back for approval
    await store.decide(db, doc["_id"], "reject", "Not clear enough")
    assert (await store.my_listings(db, "a@x.com"))[0]["note"] == "Not clear enough"
    await store.decide(db, doc["_id"], "approve")
    assert (await store.set_paused(db, "a@x.com", doc["_id"], True))["status"] == "paused" and await store.browse(db, "b@x.com", None, None) == []
    with pytest.raises(HTTPException):
        await store.delete_listing(db, "b@x.com", doc["_id"])                # only the owner of a listing can delete it
    await store.delete_listing(db, "a@x.com", doc["_id"])
    for i in range(rules.MAX_NEW_LISTINGS_DAY):
        await store.create_listing(db, "a@x.com", GOOD, now=5000 + i)
    with pytest.raises(HTTPException) as day:
        await store.create_listing(db, "a@x.com", GOOD, now=5100)
    assert day.value.status_code == 429


async def test_enquiries_replies_unread_and_limits():
    db = AsyncMongoMockClient()["x"]
    for who, name in (("a@x.com", "Asha"), ("b@x.com", "Ben"), ("c@x.com", "Chi")):
        await store.set_profile(db, who, name)
    listing = await store.create_listing(db, "a@x.com", GOOD, now=1)
    with pytest.raises(HTTPException):
        await store.enquire(db, "b@x.com", listing["_id"], "Hello there", now=2)       # not approved yet
    await store.decide(db, listing["_id"], "approve")
    with pytest.raises(HTTPException):
        await store.enquire(db, "a@x.com", listing["_id"], "Hello there", now=2)       # not your own
    t = await store.enquire(db, "b@x.com", listing["_id"], "Is this suitable for beginners?", now=10)
    again = await store.enquire(db, "b@x.com", listing["_id"], "Also, how long is it?", now=11)
    assert again["id"] == t["id"] and len(again["messages"]) == 2                      # one thread per listing and person
    assert await store.unread_total(db, "a@x.com") == 2 and await store.unread_total(db, "b@x.com") == 0
    seen = await store.open_thread(db, "a@x.com", t["id"], now=12)
    assert seen["other_name"] == "Ben" and seen["role"] == "seller" and await store.unread_total(db, "a@x.com") == 0
    await store.reply(db, "a@x.com", t["id"], "Yes, it starts from zero.", now=13)
    assert await store.unread_total(db, "b@x.com") == 1
    with pytest.raises(HTTPException):
        await store.open_thread(db, "c@x.com", t["id"])                                  # strangers cannot read it
    with pytest.raises(HTTPException):
        await store.reply(db, "c@x.com", t["id"], "hi hi")
    with pytest.raises(HTTPException):
        await store.reply(db, "b@x.com", t["id"], "x")                                   # too short
    for i in range(rules.MAX_MESSAGES_HOUR):
        try:
            await store.reply(db, "b@x.com", t["id"], f"message {i}", now=20 + i)
        except HTTPException as exc:
            assert exc.status_code == 429
            break
    else:
        pytest.fail("message limit never applied")


async def test_reports_hide_listing_and_owner_queue():
    db = AsyncMongoMockClient()["x"]
    await store.set_profile(db, "a@x.com", "Asha")
    listing = await store.create_listing(db, "a@x.com", GOOD, now=1)
    await store.decide(db, listing["_id"], "approve")
    with pytest.raises(HTTPException):
        await store.report(db, "a@x.com", listing["_id"], "my own thing")
    await store.report(db, "r1@x.com", listing["_id"], "Looks like it sells tips", now=2)
    await store.report(db, "r1@x.com", listing["_id"], "Looks like it sells tips", now=3)   # same person again: counted once
    await store.report(db, "r2@x.com", listing["_id"], "Promises returns", now=4)
    assert len(await store.browse(db, "z@x.com", None, None)) == 1
    await store.report(db, "r3@x.com", listing["_id"], "Spam listing", now=5)
    assert await store.browse(db, "z@x.com", None, None) == []                          # three different people: hidden
    queue = await store.admin_queue(db)
    assert len(queue["reported"]) == 1 and len(queue["reported"][0]["reasons"]) == 3
    await store.decide(db, listing["_id"], "approve")                                   # owner reviewed and restored it
    assert len(await store.browse(db, "z@x.com", None, None)) == 1 and (await store.admin_queue(db))["reported"] == []
    await store.decide(db, listing["_id"], "remove")
    assert await store.browse(db, "z@x.com", None, None) == []


def test_api_signed_in_only_owner_approves_and_emails_stay_private(api, monkeypatch):
    import routers.exchange as rx

    monkeypatch.setattr(rx, "db", AsyncMongoMockClient()["ex"])
    import asyncio

    for e in ("seller@example.com", "buyer@example.com", "other@example.com"):
        asyncio.run(api.db.access_users.insert_one({"_id": e}))
    c, owner, seller, buyer = api.client, api.cookie("owner@example.com", "admin"), api.cookie("seller@example.com"), api.cookie("buyer@example.com")
    assert c.get("/api/exchange/listings").status_code == 401
    r = c.put("/api/exchange/me/profile", json={"name": "Asha"}, headers=seller)
    assert r.json().get("display_name") == "Asha", (r.status_code, r.text)
    assert c.put("/api/exchange/me/profile", json={"name": "Ben"}, headers=buyer).status_code == 200
    made = c.post("/api/exchange/listings", json=GOOD, headers=seller)
    assert made.status_code == 200
    lid = made.json()["listings"][0]["id"]
    assert c.post("/api/exchange/listings", json={**GOOD, "description": GOOD["description"] + " plus daily tips"}, headers=seller).status_code == 422
    assert c.get("/api/exchange/listings", headers=buyer).json()["listings"] == []
    assert c.get("/api/exchange/admin/queue", headers=seller).status_code == 403
    assert c.post(f"/api/exchange/admin/listings/{lid}", json={"action": "approve"}, headers=buyer).status_code == 403
    assert c.get("/api/exchange/meta", headers=owner).json()["pending"] == 1
    assert c.post(f"/api/exchange/admin/listings/{lid}", json={"action": "approve"}, headers=owner).status_code == 200
    shown = c.get("/api/exchange/listings", headers=buyer).json()
    assert shown["listings"][0]["seller_name"] == "Asha" and "seller@example.com" not in str(shown) and "not vouch" in shown["note"]
    sent = c.post(f"/api/exchange/listings/{lid}/enquire", json={"message": "Is this for beginners?"}, headers=buyer).json()["thread"]
    assert c.get("/api/exchange/meta", headers=seller).json()["unread"] == 1
    assert c.get(f"/api/exchange/threads/{sent['id']}", headers=seller).json()["thread"]["other_name"] == "Ben"
    assert c.get(f"/api/exchange/threads/{sent['id']}", headers=api.cookie("other@example.com")).status_code == 404
    assert c.post(f"/api/exchange/listings/{lid}/report", json={"reason": "Seems misleading"}, headers=buyer).status_code == 200
