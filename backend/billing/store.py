"""Subscription storage and the single place a payment becomes access.

Payments are confirmed by the owner for now (`confirm_order`); a payment gateway's webhook would call the very same function once
one is connected. Access is never granted by the browser: the dashboard only reads what this module has stored.
"""
import logging
import os
import time
import uuid
from typing import Any

from fastapi import HTTPException

from billing import plans
from lib import access

logger = logging.getLogger(__name__)
SUBS, ORDERS, PAYMENTS = "billing_subscriptions", "billing_orders", "billing_payments"
CACHE_SECONDS = 10
_cache: dict[str, tuple[dict | None, float]] = {}


def payments_live() -> bool:
    """True only when a gateway that can take recurring payments is connected. None is, so renewals are requested, never auto-charged."""
    return False


def pay_to() -> dict[str, str]:
    upi, payee = os.environ.get("PAYMENT_UPI_ID", "").strip(), os.environ.get("PAYMENT_PAYEE_NAME", "").strip()
    return {"upi_id": upi, "payee": payee} if upi else {}


async def _mail(to: str, subject: str, body: str) -> None:
    if access.sign_in_configured():  # same mail settings as sign-in codes; without them nothing is sent
        await access._send_mail(to, subject, body)


async def get_sub(email: str) -> dict | None:
    email = access.normalize_email(email)
    cached = _cache.get(email)
    if cached and time.monotonic() - cached[1] < CACHE_SECONDS:
        return cached[0]
    try:
        doc = await access._collection(SUBS).find_one({"_id": email})
    except Exception as exc:  # noqa: BLE001  a storage problem must DENY paid access, never grant it
        logger.warning("BILLING_LOAD_ERROR kind=%s", type(exc).__name__)
        return None
    _cache[email] = (doc, time.monotonic())
    return doc


async def _save(email: str, sub: dict) -> None:
    sub["_id"] = email
    await access._collection(SUBS).replace_one({"_id": email}, sub, upsert=True)
    _cache[email] = (sub, time.monotonic())


async def entitlement(email: str, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    sub = await get_sub(email)
    return {"standard": plans.is_active(sub, now), "premium": plans.is_active(sub, now, "premium"), "until": (sub or {}).get("period_end")}


async def _legacy_premium(email: str, now: float) -> bool:
    from lib import premium

    until = await premium.premium_until(email)
    return bool(until and until > now)


async def summary(user: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """What the Subscription page shows: current plan, the exact terms of each plan on offer, and any notices."""
    now = time.time() if now is None else now
    email = access.normalize_email(user.get("email") or "")
    sub = await get_sub(email) if email else None
    legacy = await _legacy_premium(email, now) if email else False
    st = plans.status(sub, now)
    live = payments_live()
    pending = await access._collection(ORDERS).find_one({"email": email, "status": "pending"}) if email else None
    return {
        "email": email or None, "status": st, "plan": (sub or {}).get("plan"), "period_end": (sub or {}).get("period_end"), "period_start": (sub or {}).get("period_start"),
        "cancel_at_period_end": bool((sub or {}).get("cancel_at_period_end")), "premium": plans.is_active(sub, now, "premium") or legacy, "premium_by_owner": legacy and not plans.is_active(sub, now, "premium"),
        "trial_ends_at": user.get("trial_ends_at"), "role": user.get("role"), "promo_used": bool((sub or {}).get("promo_used")),
        "offers": {p: plans.terms(sub, p, now, live, legacy) for p in ("standard", "premium")},
        "notices": plans.notices(sub, now, user.get("trial_ends_at"), legacy), "payments_live": live, "pay_to": pay_to(),
        "pending_order": _order_view(pending) if pending else None,
    }


def _order_view(order: dict) -> dict:
    return {"id": order["_id"], "code": order["code"], "plan": order["plan"], "amount": order["amount"], "created_at": order["created_at"]}


def _same_terms(consent: dict, fresh: dict) -> bool:
    return (consent.get("accept_terms") is True and consent.get("accept_recurring") is True and consent.get("terms_version") == fresh["terms_version"]
            and consent.get("today_inr") == fresh["today_inr"] and consent.get("next_charge_inr") == fresh["next_charge_inr"] and consent.get("next_charge_on") == fresh["next_charge_on"])


async def checkout(email: str, plan: str, consent: dict, now: float | None = None) -> dict[str, Any]:
    """Start a purchase. Needs the buyer's explicit consent to the exact amounts and dates shown to them."""
    now = time.time() if now is None else now
    email = access.normalize_email(email)
    if plan not in ("standard", "premium"):
        raise HTTPException(status_code=422, detail="Pick Standard or Premium.")
    sub = await get_sub(email)
    legacy = await _legacy_premium(email, now)
    fresh = plans.terms(sub, plan, now, payments_live(), legacy)
    if not _same_terms(consent or {}, fresh):
        raise HTTPException(status_code=409, detail="Please read and tick both boxes. If the terms changed on screen, review them and try again.")
    orders = access._collection(ORDERS)
    await orders.delete_many({"email": email, "status": "pending"})  # one open order per person
    order = {"_id": uuid.uuid4().hex, "code": "ED-" + uuid.uuid4().hex[:6].upper(), "email": email, "plan": plan, "kind": fresh["kind"], "amount": fresh["today_inr"], "status": "pending",
             "consent": {**consent, "at": now}, "terms": {k: fresh[k] for k in ("today_inr", "next_charge_inr", "next_charge_on", "terms_version", "auto_renew", "promo")}, "created_at": now}
    await orders.insert_one(order)
    body = f"{email} chose {plan.title()} for ₹{order['amount']} (reference {order['code']}).\n\nOpen the Access panel on the dashboard to confirm the payment once you have received it: {access.app_url()}\n"
    for owner in sorted(access.admin_emails()):
        await _mail(owner, f"EdgeDesk: {plan.title()} request from {email}", body)
    return {"order": _order_view(order), "pay_to": pay_to(), "terms": fresh}


async def confirm_order(order_id: str, reference: str, amount: int, now: float | None = None) -> dict[str, Any]:
    """Money has arrived: turn the order into access. The amount must match the order exactly and a reference can only be used once."""
    now = time.time() if now is None else now
    reference = (reference or "").strip()[:80]
    if len(reference) < 4:
        raise HTTPException(status_code=422, detail="Enter the payment reference (UPI transaction id).")
    orders = access._collection(ORDERS)
    order = await orders.find_one({"_id": order_id})
    if not order or order["status"] != "pending":
        raise HTTPException(status_code=404, detail="That order is not waiting for payment.")
    if int(amount) != order["amount"]:
        raise HTTPException(status_code=422, detail=f"This order is for ₹{order['amount']}.")
    payments = access._collection(PAYMENTS)
    if await payments.find_one({"_id": reference}):
        raise HTTPException(status_code=409, detail="That payment reference has already been used.")
    email = order["email"]
    sub = await get_sub(email)
    kind = order["kind"]
    if kind == "premium_intro" and not plans.promo_eligible(sub, now, await _legacy_premium(email, now))[0]:
        raise HTTPException(status_code=409, detail="The first-month offer no longer applies to this account. Decline this order and ask them to check out again.")
    updated = plans.apply_payment(sub, kind, now, reference)
    await _save(email, updated)
    await payments.insert_one({"_id": reference, "email": email, "order": order_id, "kind": kind, "amount": order["amount"], "at": now})
    await orders.update_one({"_id": order_id}, {"$set": {"status": "paid", "reference": reference, "paid_at": now}})
    access._trial_cache.pop(email, None)
    await _mail(email, "EdgeDesk: payment received", f"Thanks. We received ₹{order['amount']} (reference {reference}).\n\nYour {updated['plan'].title()} plan runs until {plans.pretty(updated['period_end'])}.\n"
                            f"Next payment: ₹{plans.PREMIUM_INR if updated['plan'] == 'premium' else plans.STANDARD_INR} on {plans.pretty(updated['period_end'])}. You can cancel any time from Subscription: {access.app_url()}\n")
    logger.info("BILLING_PAID kind=%s", kind)
    return {"email": email, "plan": updated["plan"], "period_end": updated["period_end"]}


async def decline_order(order_id: str) -> None:
    res = await access._collection(ORDERS).update_one({"_id": order_id, "status": "pending"}, {"$set": {"status": "declined"}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="That order is not waiting for payment.")


async def mark_payment_failed(email: str, now: float | None = None) -> None:
    """A renewal could not be collected: the plan lapses at the end of the paid period and the user is told why."""
    now = time.time() if now is None else now
    email = access.normalize_email(email)
    sub = await get_sub(email)
    if not sub or not sub.get("plan"):
        raise HTTPException(status_code=404, detail="That person has no subscription.")
    sub["payment_failed_at"] = now
    sub["events"] = [*sub.get("events", [])[-49:], {"at": now, "type": "payment_failed"}]
    await _save(email, sub)


async def set_cancel(email: str, cancel: bool, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else now
    email = access.normalize_email(email)
    sub = await get_sub(email)
    if not plans.is_active(sub, now):
        raise HTTPException(status_code=422, detail="There's no active plan to change.")
    sub["cancel_at_period_end"] = cancel
    sub["events"] = [*sub.get("events", [])[-49:], {"at": now, "type": "cancelled" if cancel else "resumed"}]
    await _save(email, sub)
    return {"cancel_at_period_end": cancel, "period_end": sub["period_end"]}


async def pending_orders() -> list[dict]:
    rows = await access._collection(ORDERS).find({"status": "pending"}).sort("created_at", 1).to_list(200)
    return [{**_order_view(r), "email": r["email"], "kind": r["kind"]} for r in rows]
