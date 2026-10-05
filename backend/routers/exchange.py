"""Trader's Exchange API: a notice board for services, with owner approval, enquiries and reports. No payments. Every route needs a
signed-in account; approving and removing listings is the owner's alone."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from exchange import rules, store
from lib import access
from lib.db import db
from premium import userdata

router = APIRouter(prefix="/exchange", tags=["exchange"])

NOTE = ("Trader's Exchange is a notice board. The owner checks each listing for the rules, but does not vouch for any seller, service or claim, and no money "
        "moves through it. Nothing here is investment advice. Check who you are dealing with before you pay anyone.")


def _me(user: dict[str, Any]) -> str:
    return userdata.owner_key(user)


@router.get("/meta")
async def meta(user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    owner = _me(user)
    profile = await store.get_profile(db, owner)
    out: dict[str, Any] = {"categories": rules.CATEGORIES, "rules": rules.RULES, "note": NOTE, "display_name": (profile or {}).get("name"), "unread": await store.unread_total(db, owner),
                           "is_owner": user.get("role") == "admin", "max_listings": rules.MAX_LISTINGS}
    if out["is_owner"]:
        out["pending"] = len((await store.admin_queue(db))["pending"])
    return out


@router.put("/me/profile")
async def put_profile(name: str = Body(..., embed=True), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"display_name": (await store.set_profile(db, _me(user), name))["name"]}


@router.get("/listings")
async def listings(category: str | None = Query(None), q: str | None = Query(None, max_length=60), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"listings": await store.browse(db, _me(user), category, q), "note": NOTE}


@router.get("/listings/{listing_id}")
async def one_listing(listing_id: str, user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"listing": await store.get_listing(db, _me(user), listing_id)}


@router.get("/me/listings")
async def mine(user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"listings": await store.my_listings(db, _me(user))}


@router.post("/listings")
async def create(data: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    await store.create_listing(db, _me(user), data)
    return {"listings": await store.my_listings(db, _me(user))}


@router.put("/listings/{listing_id}")
async def edit(listing_id: str, data: dict[str, Any] = Body(...), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    await store.edit_listing(db, _me(user), listing_id, data)
    return {"listings": await store.my_listings(db, _me(user))}


@router.patch("/listings/{listing_id}")
async def pause(listing_id: str, paused: bool = Body(..., embed=True), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    await store.set_paused(db, _me(user), listing_id, paused)
    return {"listings": await store.my_listings(db, _me(user))}


@router.delete("/listings/{listing_id}")
async def remove(listing_id: str, user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    await store.delete_listing(db, _me(user), listing_id)
    return {"listings": await store.my_listings(db, _me(user))}


@router.post("/listings/{listing_id}/enquire")
async def enquire(listing_id: str, message: str = Body(..., embed=True), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"thread": await store.enquire(db, _me(user), listing_id, message)}


@router.post("/listings/{listing_id}/report")
async def report(listing_id: str, reason: str = Body(..., embed=True), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    await store.report(db, _me(user), listing_id, reason)
    return {"ok": True, "message": "Thanks. The owner will look at it."}


@router.get("/threads")
async def threads(user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"threads": await store.list_threads(db, _me(user))}


@router.get("/threads/{thread_id}")
async def thread(thread_id: str, user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"thread": await store.open_thread(db, _me(user), thread_id)}


@router.post("/threads/{thread_id}/messages")
async def send(thread_id: str, message: str = Body(..., embed=True), user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    return {"thread": await store.reply(db, _me(user), thread_id, message)}


# ------------------------------------------------------------------ owner only
@router.get("/admin/queue")
async def queue(owner: dict[str, Any] = Depends(access.require_admin)) -> dict[str, Any]:
    return await store.admin_queue(db)


@router.post("/admin/listings/{listing_id}")
async def decide(listing_id: str, action: str = Body(..., embed=True), note: str = Body("", embed=True), owner: dict[str, Any] = Depends(access.require_admin)) -> dict[str, Any]:
    await store.decide(db, listing_id, action, note)
    return await store.admin_queue(db)
