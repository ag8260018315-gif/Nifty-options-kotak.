"""Trader's Exchange storage: profiles, listings, enquiry threads and reports. Everyone is identified inside the Exchange by a display
name; email addresses never leave the server."""
import time
import uuid
from typing import Any

from fastapi import HTTPException

from exchange import rules

PROFILES, LISTINGS, THREADS, REPORTS = "exchange_profiles", "exchange_listings", "exchange_threads", "exchange_reports"
PENDING, APPROVED, REJECTED, PAUSED, HIDDEN = "pending", "approved", "rejected", "paused", "hidden"
LIVE = (PENDING, APPROVED, HIDDEN)


def _404(what: str = "That listing") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} was not found.")


async def get_profile(db: Any, owner: str) -> dict | None:
    return await db[PROFILES].find_one({"_id": owner})


async def set_profile(db: Any, owner: str, name: str) -> dict:
    name = rules.clean_name(name)
    other = await db[PROFILES].find_one({"name_lower": name.lower(), "_id": {"$ne": owner}})
    if other:
        raise HTTPException(status_code=409, detail="That display name is taken. Please choose another.")
    doc = {"_id": owner, "name": name, "name_lower": name.lower(), "updated_at": time.time()}
    await db[PROFILES].replace_one({"_id": owner}, doc, upsert=True)
    return doc


async def _name_of(db: Any, owner: str) -> str:
    doc = await get_profile(db, owner)
    return (doc or {}).get("name", "Member")


def public(listing: dict, seller_name: str, mine: bool = False) -> dict:
    out = {"id": listing["_id"], "title": listing["title"], "category": listing["category"], "category_label": rules.CATEGORIES.get(listing["category"], "Other"),
           "description": listing["description"], "price_text": listing.get("price_text", ""), "seller_name": seller_name, "created_at": listing["created_at"],
           "mine": mine}
    if mine:
        out.update(status=listing["status"], note=listing.get("note", ""), reports=len(listing.get("reporters", [])))
    return out


async def create_listing(db: Any, owner: str, data: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not await get_profile(db, owner):
        raise HTTPException(status_code=422, detail="Choose a display name first.")
    clean = rules.clean_listing(data)
    if await db[LISTINGS].count_documents({"owner": owner, "status": {"$in": list(LIVE)}}) >= rules.MAX_LISTINGS:
        raise HTTPException(status_code=422, detail=f"You can have up to {rules.MAX_LISTINGS} listings. Remove one first.")
    if await db[LISTINGS].count_documents({"owner": owner, "created_at": {"$gte": now - 86400}}) >= rules.MAX_NEW_LISTINGS_DAY:
        raise HTTPException(status_code=429, detail="That's enough new listings for today. Try again tomorrow.")
    doc = {"_id": uuid.uuid4().hex[:16], "owner": owner, **clean, "status": PENDING, "note": "", "reporters": [], "created_at": now}
    await db[LISTINGS].insert_one(doc)
    return doc


async def _mine(db: Any, owner: str, listing_id: str) -> dict:
    doc = await db[LISTINGS].find_one({"_id": listing_id, "owner": owner})
    if not doc:
        raise _404()
    return doc


async def edit_listing(db: Any, owner: str, listing_id: str, data: dict) -> dict:
    doc = await _mine(db, owner, listing_id)
    clean = rules.clean_listing(data)
    await db[LISTINGS].update_one({"_id": listing_id}, {"$set": {**clean, "status": PENDING, "note": ""}})  # any change is checked again
    return {**doc, **clean, "status": PENDING, "note": ""}


async def set_paused(db: Any, owner: str, listing_id: str, paused: bool) -> dict:
    doc = await _mine(db, owner, listing_id)
    if paused and doc["status"] == APPROVED:
        status = PAUSED
    elif not paused and doc["status"] == PAUSED:
        status = APPROVED
    else:
        raise HTTPException(status_code=422, detail="Only an approved listing can be paused or resumed.")
    await db[LISTINGS].update_one({"_id": listing_id}, {"$set": {"status": status}})
    return {**doc, "status": status}


async def delete_listing(db: Any, owner: str, listing_id: str) -> None:
    await _mine(db, owner, listing_id)
    await db[LISTINGS].delete_one({"_id": listing_id})


async def browse(db: Any, owner: str, category: str | None, text: str | None, limit: int = 60) -> list[dict]:
    query: dict[str, Any] = {"status": APPROVED}
    if category in rules.CATEGORIES:
        query["category"] = category
    rows = await db[LISTINGS].find(query).sort("created_at", -1).to_list(300)
    needle = (text or "").strip().lower()
    out = []
    for row in rows:
        if needle and needle not in f"{row['title']} {row['description']}".lower():
            continue
        out.append(public(row, await _name_of(db, row["owner"]), row["owner"] == owner))
        if len(out) >= limit:
            break
    return out


async def get_listing(db: Any, owner: str, listing_id: str) -> dict:
    doc = await db[LISTINGS].find_one({"_id": listing_id})
    if not doc or (doc["status"] != APPROVED and doc["owner"] != owner):
        raise _404()
    return public(doc, await _name_of(db, doc["owner"]), doc["owner"] == owner)


async def my_listings(db: Any, owner: str) -> list[dict]:
    name = await _name_of(db, owner)
    rows = await db[LISTINGS].find({"owner": owner}).sort("created_at", -1).to_list(50)
    return [public(r, name, True) for r in rows]


# ------------------------------------------------------------------ enquiries
def _view(thread: dict, owner: str, names: dict[str, str]) -> dict:
    role = "buyer" if thread["buyer"] == owner else "seller"
    other = thread["seller"] if role == "buyer" else thread["buyer"]
    read_at = thread.get(f"{role}_read_at", 0)
    unread = sum(1 for m in thread["messages"] if m["from"] != role and m["at"] > read_at)
    return {"id": thread["_id"], "listing_id": thread["listing_id"], "listing_title": thread["listing_title"], "role": role, "other_name": names.get(other, "Member"),
            "last_at": thread["last_at"], "unread": unread, "messages": [{"mine": m["from"] == role, "text": m["text"], "at": m["at"]} for m in thread["messages"]]}


async def _names(db: Any, *owners: str) -> dict[str, str]:
    return {o: await _name_of(db, o) for o in owners}


async def enquire(db: Any, owner: str, listing_id: str, text: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not await get_profile(db, owner):
        raise HTTPException(status_code=422, detail="Choose a display name first.")
    listing = await db[LISTINGS].find_one({"_id": listing_id, "status": APPROVED})
    if not listing:
        raise _404()
    if listing["owner"] == owner:
        raise HTTPException(status_code=422, detail="This is your own listing.")
    text = rules.clean_message(text)
    thread = await db[THREADS].find_one({"listing_id": listing_id, "buyer": owner})
    if thread:
        return await reply(db, owner, thread["_id"], text, now)
    rules.limiter.hit(owner, "enquiry", rules.MAX_ENQUIRIES_DAY, 86400, now)
    thread = {"_id": uuid.uuid4().hex[:16], "listing_id": listing_id, "listing_title": listing["title"], "buyer": owner, "seller": listing["owner"],
              "messages": [{"from": "buyer", "text": text, "at": now}], "buyer_read_at": now, "seller_read_at": 0, "last_at": now}
    await db[THREADS].insert_one(thread)
    return _view(thread, owner, await _names(db, owner, listing["owner"]))


async def _thread_of(db: Any, owner: str, thread_id: str) -> dict:
    thread = await db[THREADS].find_one({"_id": thread_id, "$or": [{"buyer": owner}, {"seller": owner}]})
    if not thread:
        raise _404("That conversation")
    return thread


async def reply(db: Any, owner: str, thread_id: str, text: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    thread = await _thread_of(db, owner, thread_id)
    text = rules.clean_message(text)
    if len(thread["messages"]) >= rules.MAX_THREAD_MESSAGES:
        raise HTTPException(status_code=422, detail="This conversation is full. Start a new enquiry if you need to.")
    rules.limiter.hit(owner, "message", rules.MAX_MESSAGES_HOUR, 3600, now)
    role = "buyer" if thread["buyer"] == owner else "seller"
    message = {"from": role, "text": text, "at": now}
    await db[THREADS].update_one({"_id": thread_id}, {"$push": {"messages": message}, "$set": {"last_at": now, f"{role}_read_at": now}})
    thread["messages"].append(message)
    thread["last_at"] = now
    thread[f"{role}_read_at"] = now
    return _view(thread, owner, await _names(db, thread["buyer"], thread["seller"]))


async def list_threads(db: Any, owner: str) -> list[dict]:
    rows = await db[THREADS].find({"$or": [{"buyer": owner}, {"seller": owner}]}).sort("last_at", -1).to_list(100)
    out = []
    for t in rows:
        v = _view(t, owner, await _names(db, t["buyer"], t["seller"]))
        v["messages"] = v["messages"][-1:]  # the list only needs the latest line
        out.append(v)
    return out


async def open_thread(db: Any, owner: str, thread_id: str, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    thread = await _thread_of(db, owner, thread_id)
    view = _view(thread, owner, await _names(db, thread["buyer"], thread["seller"]))
    role = view["role"]
    await db[THREADS].update_one({"_id": thread_id}, {"$set": {f"{role}_read_at": now}})
    return view


async def unread_total(db: Any, owner: str) -> int:
    return sum(t["unread"] for t in await list_threads(db, owner))


# ------------------------------------------------------------------ reports and the owner's queue
async def report(db: Any, owner: str, listing_id: str, reason: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    reason = rules.clean_reason(reason)
    listing = await db[LISTINGS].find_one({"_id": listing_id})
    if not listing or listing["status"] not in (APPROVED, HIDDEN, PAUSED):
        raise _404()
    if listing["owner"] == owner:
        raise HTTPException(status_code=422, detail="This is your own listing.")
    rules.limiter.hit(owner, "report", 10, 86400, now)
    reporters = list(listing.get("reporters", []))
    if owner in reporters:
        return  # one report per person counts
    reporters.append(owner)
    await db[REPORTS].insert_one({"_id": uuid.uuid4().hex[:16], "listing_id": listing_id, "reporter": owner, "reason": reason, "at": now})
    update: dict[str, Any] = {"reporters": reporters}
    if len(reporters) >= rules.REPORTS_TO_HIDE and listing["status"] == APPROVED:
        update["status"] = HIDDEN  # taken down until the owner has looked
    await db[LISTINGS].update_one({"_id": listing_id}, {"$set": update})


async def admin_queue(db: Any) -> dict:
    out: dict[str, list] = {"pending": [], "reported": []}
    for key, query in (("pending", {"status": PENDING}), ("reported", {"status": {"$in": [APPROVED, HIDDEN, PAUSED]}})):
        for row in await db[LISTINGS].find(query).sort("created_at", 1).to_list(500):
            if key == "reported" and not row.get("reporters"):
                continue
            item = public(row, await _name_of(db, row["owner"]), True)
            if key == "reported":
                item["reasons"] = [r["reason"] for r in await db[REPORTS].find({"listing_id": row["_id"]}).sort("at", 1).to_list(20)]
            out[key].append(item)
    return out


async def decide(db: Any, listing_id: str, action: str, note: str = "") -> dict:
    doc = await db[LISTINGS].find_one({"_id": listing_id})
    if not doc:
        raise _404()
    note = rules.one_line(note)[:300]
    if action == "approve":
        await db[LISTINGS].update_one({"_id": listing_id}, {"$set": {"status": APPROVED, "note": "", "reporters": []}})
        await db[REPORTS].delete_many({"listing_id": listing_id})
    elif action == "reject":
        await db[LISTINGS].update_one({"_id": listing_id}, {"$set": {"status": REJECTED, "note": note or "Not accepted under the Exchange rules."}})
    elif action == "remove":
        await db[LISTINGS].delete_one({"_id": listing_id})
        await db[REPORTS].delete_many({"listing_id": listing_id})
    else:
        raise HTTPException(status_code=422, detail="Unknown action.")
    return {"id": listing_id, "action": action}
