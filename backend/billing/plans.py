"""Plans, prices and subscription rules. Pure functions: no I/O, so the money rules can be tested exhaustively.

Standard   7-day free trial (handled by lib.access), then ₹189 per month.
Premium    pay ₹189 to upgrade and get Premium for the first month as a promotional offer (once per account),
           then ₹399 per month. Premium includes everything in Standard.
A "month" is one calendar month in India time. Cancelling stops renewals; access continues to the end of the paid period.
"""
import calendar
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
STANDARD_INR = 189
PREMIUM_INTRO_INR = 189
PREMIUM_INR = 399
TERMS_VERSION = "2026-10-05"
SOON_DAYS = 3  # a renewal reminder is shown this many days ahead


def add_month(ts: float) -> float:
    d = datetime.fromtimestamp(ts, IST)
    year, month = d.year + (d.month == 12), d.month % 12 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1])).timestamp()


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).date().isoformat()


def pretty(ts: float) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y").lstrip("0")


def empty() -> dict[str, Any]:
    return {"plan": None, "period_start": None, "period_end": None, "cancel_at_period_end": False, "promo_used": False, "events": []}


def is_active(sub: dict | None, now: float, plan: str | None = None) -> bool:
    """Is a PAID period running? plan="premium" asks about Premium; plan="standard" about any paid plan (Premium includes Standard)."""
    if not sub or not sub.get("plan") or not sub.get("period_end") or sub["period_end"] <= now:
        return False
    return plan != "premium" or sub["plan"] == "premium"


def status(sub: dict | None, now: float) -> str:
    """none | active | cancelling | lapsed"""
    if not sub or not sub.get("plan"):
        return "none"
    if is_active(sub, now):
        return "cancelling" if sub.get("cancel_at_period_end") else "active"
    return "lapsed"


def promo_eligible(sub: dict | None, now: float, legacy_premium_active: bool = False) -> tuple[bool, str]:
    if (sub or {}).get("promo_used"):
        return False, "The first-month Premium offer has already been used on this account."
    if is_active(sub, now, "premium") or legacy_premium_active:
        return False, "You already have Premium."
    return True, ""


def kind_for(sub: dict | None, plan: str, now: float, legacy_premium_active: bool = False) -> str:
    if plan == "standard":
        return "standard"
    return "premium_intro" if promo_eligible(sub, now, legacy_premium_active)[0] else "premium"


def amount_for(kind: str) -> int:
    return {"standard": STANDARD_INR, "premium_intro": PREMIUM_INTRO_INR, "premium": PREMIUM_INR}[kind]


def new_period(sub: dict | None, kind: str, now: float) -> tuple[float, float]:
    """(start, end) of the period a payment of this kind buys."""
    if kind == "premium_intro":
        return now, add_month(now)  # starts now; any unused Standard time is replaced
    plan = "premium" if kind == "premium" else "standard"
    if is_active(sub, now) and sub["plan"] == plan:
        return sub["period_end"], add_month(sub["period_end"])  # renewing early adds to the running period
    return now, add_month(now)


def terms(sub: dict | None, plan: str, now: float, auto_renew: bool, legacy_premium_active: bool = False) -> dict[str, Any]:
    """Everything the buyer must be shown, and agree to, before paying. Built on the server so the page and the rules cannot disagree."""
    kind = kind_for(sub, plan, now, legacy_premium_active)
    amount = amount_for(kind)
    start, end = new_period(sub, kind, now)
    next_amount = PREMIUM_INR if plan == "premium" else STANDARD_INR
    renew_word = "will be charged automatically" if auto_renew else "will be requested from you (nothing is taken automatically)"
    if kind == "premium_intro":
        lines = [
            f"Today you pay ₹{amount}. This is the Premium upgrade offer: your first month of Premium is free.",
            f"Premium runs from {pretty(start)} to {pretty(end)}.",
            f"After that, Premium costs ₹{next_amount} per month. The first ₹{next_amount} payment {renew_word} on {pretty(end)}, then every month until you cancel.",
            "The offer is once per account. Any unused Standard time is replaced by Premium.",
            "Cancel any time from Subscription. You keep access until the end of the period you have paid for.",
        ]
    else:
        name = "Premium" if plan == "premium" else "Standard"
        lines = [
            f"Today you pay ₹{amount} for one month of {name}: {pretty(start)} to {pretty(end)}.",
            f"After that, {name} costs ₹{next_amount} per month. The next payment {renew_word} on {pretty(end)}, then every month until you cancel.",
            "Cancel any time from Subscription. You keep access until the end of the period you have paid for.",
        ]
    return {"plan": plan, "kind": kind, "today_inr": amount, "period_start": start, "period_end": end, "next_charge_inr": next_amount, "next_charge_on": day_of(end),
            "next_charge_label": pretty(end), "promo": kind == "premium_intro", "auto_renew": auto_renew, "terms_version": TERMS_VERSION, "lines": lines}


def apply_payment(sub: dict | None, kind: str, now: float, reference: str) -> dict[str, Any]:
    out = {**empty(), **(sub or {})}
    start, end = new_period(out, kind, now)
    plan = "premium" if kind in ("premium", "premium_intro") else "standard"
    out.update(plan=plan, period_start=start, period_end=end, cancel_at_period_end=False, last_payment_at=now, payment_failed_at=None)
    if kind == "premium_intro":
        out.update(promo_used=True, promo_used_at=now)
    out["events"] = [*out.get("events", [])[-49:], {"at": now, "type": f"paid_{kind}", "ref": reference}]
    return out


def notices(sub: dict | None, now: float, trial_ends_at: float | None, premium_by_grant: bool) -> list[dict[str, str]]:
    """Plain messages for the dashboard banner: what happened and what to do."""
    out: list[dict[str, str]] = []
    st = status(sub, now)
    if sub and sub.get("payment_failed_at") and st != "active":
        out.append({"level": "error", "code": "payment_failed", "text": "Your last payment didn't go through, so your plan has ended. Pick a plan to continue."})
    elif st == "lapsed":
        name = "Premium" if sub["plan"] == "premium" else "Standard"
        out.append({"level": "warn", "code": "lapsed", "text": f"Your {name} plan ended on {pretty(sub['period_end'])}. Renew to get it back."})
    elif st == "cancelling":
        out.append({"level": "info", "code": "cancelling", "text": f"Your plan is cancelled and ends on {pretty(sub['period_end'])}. You won't be charged again."})
    elif st == "active" and sub["period_end"] - now <= SOON_DAYS * 86400:
        price = PREMIUM_INR if sub["plan"] == "premium" else STANDARD_INR
        out.append({"level": "info", "code": "renew_soon", "text": f"Your plan renews on {pretty(sub['period_end'])} at ₹{price}."})
    if st in ("none", "lapsed") and not premium_by_grant and trial_ends_at:
        if trial_ends_at <= now:
            out.append({"level": "warn", "code": "trial_ended", "text": f"Your free trial ended on {pretty(trial_ends_at)}. Choose a plan to continue."})
        elif trial_ends_at - now <= SOON_DAYS * 86400:
            out.append({"level": "info", "code": "trial_ending", "text": f"Your free trial ends on {pretty(trial_ends_at)}."})
    return out
