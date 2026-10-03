"""Paid-premium entitlement. Checked on the SERVER for every premium route; hiding a button is never the control.

Premium holders are the owner(s) (ADMIN_EMAILS) plus emails the owner has granted premium until a date
(collection `premium_access`). Free trial and ordinary approved viewers do NOT get premium.
"""
import logging
import time
from typing import Any

from fastapi import Depends, HTTPException

from lib import access

logger = logging.getLogger(__name__)
COLLECTION = "premium_access"
CACHE_SECONDS = 15
MAX_DAYS = 366
_cache: dict[str, tuple[float | None, float]] = {}  # email -> (premium_until or None, loaded at)


async def premium_until(email: str) -> float | None:
    email = access.normalize_email(email)
    cached = _cache.get(email)
    if cached and time.monotonic() - cached[1] < CACHE_SECONDS:
        return cached[0]
    try:
        doc = await access._collection(COLLECTION).find_one({"_id": email})
    except Exception as exc:  # noqa: BLE001  a storage problem must DENY, never grant
        logger.warning("PREMIUM_LOAD_ERROR kind=%s", type(exc).__name__)
        return None
    until = float(doc["until"]) if doc and doc.get("until") is not None else None
    _cache[email] = (until, time.monotonic())
    return until


async def status_for(user: dict[str, Any]) -> dict[str, Any]:
    if user.get("role") == "admin":
        return {"premium": True, "premium_until": None}
    email = user.get("email")
    until = await premium_until(email) if email else None
    active = bool(until and until > time.time())
    return {"premium": active, "premium_until": until if active else None}


async def require_premium(user: dict[str, Any] = Depends(access.require_user)) -> dict[str, Any]:
    status = await status_for(user)
    if not status["premium"]:
        raise HTTPException(status_code=403, detail={"code": "premium_required", "message": "An active Premium subscription is required."})
    return {**user, **status}


async def grant(email: str, days: int, owner: str | None) -> dict[str, Any]:
    email = access.normalize_email(email)
    if not access.valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    days = max(1, min(MAX_DAYS, int(days)))
    now = time.time()
    current = await premium_until(email)
    start = current if current and current > now else now  # extending an active period adds to it
    until = start + days * 86400
    await access._collection(COLLECTION).replace_one(
        {"_id": email}, {"_id": email, "until": until, "granted_at": now, "granted_by": owner or ""}, upsert=True
    )
    _cache[email] = (until, time.monotonic())
    logger.info("PREMIUM_GRANTED days=%s", days)
    return {"email": email, "premium_until": until}


async def revoke(email: str) -> dict[str, Any]:
    email = access.normalize_email(email)
    await access._collection(COLLECTION).delete_one({"_id": email})
    _cache[email] = (None, time.monotonic())
    logger.info("PREMIUM_REVOKED")
    return {"email": email, "revoked": True}


async def list_premium() -> list[dict[str, Any]]:
    docs = await access._collection(COLLECTION).find({}).sort("until", -1).to_list(2000)
    now = time.time()
    return [{"email": d["_id"], "premium_until": d.get("until"), "active": bool(d.get("until") and d["until"] > now)} for d in docs]


REQUEST_COOLDOWN_SECONDS = 6 * 3600


async def request_premium(email: str) -> dict[str, Any]:
    """A signed-in user asks the owner(s) for Premium. At most one request per user every 6 hours."""
    email = access.normalize_email(email)
    col = access._collection("premium_requests")
    now = time.time()
    existing = await col.find_one({"_id": email})
    if existing and now - float(existing.get("created_at", 0)) < REQUEST_COOLDOWN_SECONDS:
        return {"status": "already_requested"}
    await col.replace_one({"_id": email}, {"_id": email, "created_at": now}, upsert=True)
    body = f"{email} asked for Premium access (live SENSEX, index charts and stock analysis).\n\nGrant it from the Access button on the dashboard: {access.app_url()}\n"
    sent = False
    for owner in sorted(access.admin_emails()):
        sent = await access._send_mail(owner, f"Premium request from {email}", body) or sent
    logger.info("PREMIUM_REQUESTED emailed=%s", sent)
    return {"status": "requested", "emailed": sent}
