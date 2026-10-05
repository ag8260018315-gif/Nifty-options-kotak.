"""Plans and subscriptions. The server decides what a person has paid for; the pages only show it.

A purchase starts with explicit consent to the exact amounts and dates (`/checkout`), and becomes access only when the owner (or, later,
a payment gateway) confirms the money arrived (`/admin/orders/{id}/confirm`)."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from billing import plans, store
from lib import access

router = APIRouter(prefix="/billing", tags=["billing"])


class Consent(BaseModel):
    accept_terms: bool = False
    accept_recurring: bool = False
    terms_version: str = ""
    today_inr: int = 0
    next_charge_inr: int = 0
    next_charge_on: str = ""


class CheckoutBody(BaseModel):
    plan: str = Field(max_length=20)
    consent: Consent


class ConfirmBody(BaseModel):
    reference: str = Field(min_length=1, max_length=80)
    amount: int


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)


def _email(user: dict[str, Any]) -> str:
    if not user.get("email"):
        raise HTTPException(status_code=400, detail="Sign in with your email to manage a subscription.")
    return user["email"]


@router.get("/me")
async def my_subscription(user: dict[str, Any] = Depends(access.require_account)) -> dict[str, Any]:
    return await store.summary(user)


@router.post("/checkout")
async def checkout(body: CheckoutBody, user: dict[str, Any] = Depends(access.require_account)) -> dict[str, Any]:
    return await store.checkout(_email(user), body.plan, body.consent.model_dump())


@router.post("/cancel")
async def cancel(user: dict[str, Any] = Depends(access.require_account)) -> dict[str, Any]:
    return await store.set_cancel(_email(user), True)


@router.post("/resume")
async def resume(user: dict[str, Any] = Depends(access.require_account)) -> dict[str, Any]:
    return await store.set_cancel(_email(user), False)


# ------------------------------------------------------------------ owner only
@router.get("/admin/orders")
async def orders(owner: dict[str, Any] = Depends(access.require_admin)) -> dict[str, Any]:
    return {"orders": await store.pending_orders()}


@router.post("/admin/orders/{order_id}/confirm")
async def confirm(order_id: str, body: ConfirmBody, owner: dict[str, Any] = Depends(access.require_admin)) -> dict[str, Any]:
    await store.confirm_order(order_id, body.reference, body.amount)
    return {"orders": await store.pending_orders()}


@router.post("/admin/orders/{order_id}/decline")
async def decline(order_id: str, owner: dict[str, Any] = Depends(access.require_admin)) -> dict[str, Any]:
    await store.decline_order(order_id)
    return {"orders": await store.pending_orders()}


@router.post("/admin/payment-failed")
async def payment_failed(body: EmailBody, owner: dict[str, Any] = Depends(access.require_admin)) -> dict[str, Any]:
    await store.mark_payment_failed(body.email)
    return {"ok": True}


PRICES = {"standard_inr": plans.STANDARD_INR, "premium_intro_inr": plans.PREMIUM_INTRO_INR, "premium_inr": plans.PREMIUM_INR}
