import asyncio
import os
import time
from datetime import datetime

import pytest
from fastapi import HTTPException

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from billing import plans, store  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401

NOW = datetime(2026, 1, 31, 10, 0, tzinfo=plans.IST).timestamp()


def consent_for(t):
    return {"accept_terms": True, "accept_recurring": True, "terms_version": t["terms_version"], "today_inr": t["today_inr"], "next_charge_inr": t["next_charge_inr"], "next_charge_on": t["next_charge_on"]}


def test_months_prices_and_the_premium_offer_terms():
    assert plans.day_of(plans.add_month(NOW)) == "2026-02-28"                         # 31 Jan + 1 month clamps to month end
    assert plans.day_of(plans.add_month(datetime(2026, 12, 15, tzinfo=plans.IST).timestamp())) == "2027-01-15"
    std = plans.terms(None, "standard", NOW, False)
    assert (std["today_inr"], std["next_charge_inr"], std["promo"]) == (189, 189, False)
    prem = plans.terms(None, "premium", NOW, False)
    assert (prem["today_inr"], prem["next_charge_inr"], prem["promo"], prem["kind"]) == (189, 399, True, "premium_intro")
    text = " ".join(prem["lines"])
    assert "₹189" in text and "first month of Premium is free" in text and "₹399 per month" in text and "28 Feb 2026" in text and "once per account" in text
    assert "nothing is taken automatically" in text and "charged automatically" in " ".join(plans.terms(None, "premium", NOW, True)["lines"])


def test_offer_is_once_per_account_and_renewals_cost_399():
    sub = plans.apply_payment(None, "premium_intro", NOW, "REF1")
    assert sub["plan"] == "premium" and sub["promo_used"] and plans.is_active(sub, NOW + 86400, "premium")
    assert plans.promo_eligible(sub, NOW + 86400)[0] is False
    later = sub["period_end"] + 86400                                                # lapsed, then back for Premium: no second offer
    assert plans.status(sub, later) == "lapsed" and plans.terms(sub, "premium", later, False)["today_inr"] == 399
    renewed = plans.apply_payment(sub, "premium", sub["period_end"] - 86400, "REF2")  # renewing a day early adds to the running period
    assert renewed["period_start"] == sub["period_end"] and renewed["period_end"] == plans.add_month(sub["period_end"])
    assert plans.promo_eligible(None, NOW, legacy_premium_active=True)[0] is False   # owner-granted Premium doesn't get the offer either
    std = plans.apply_payment(None, "standard", NOW, "S1")
    assert std["plan"] == "standard" and not plans.is_active(std, NOW, "premium") and plans.is_active(std, NOW)
    upgrade = plans.apply_payment(std, "premium_intro", NOW + 86400, "S2")           # Standard -> Premium replaces the running Standard period
    assert upgrade["plan"] == "premium" and upgrade["period_start"] == NOW + 86400


def test_notices_explain_trial_cancel_and_failures():
    trial_over = plans.notices(None, NOW, NOW - 86400, False)
    assert trial_over[0]["code"] == "trial_ended"
    assert plans.notices(None, NOW, NOW + 86400, False)[0]["code"] == "trial_ending"
    sub = plans.apply_payment(None, "premium_intro", NOW, "R")
    assert plans.notices(sub, NOW + 86400, None, False) == []
    assert plans.notices(sub, sub["period_end"] - 86400, None, False)[0]["code"] == "renew_soon"
    sub["cancel_at_period_end"] = True
    assert plans.notices(sub, NOW + 86400, None, False)[0]["code"] == "cancelling"
    sub["cancel_at_period_end"] = False
    sub["payment_failed_at"] = NOW
    assert plans.notices(sub, sub["period_end"] + 5, None, False)[0]["code"] == "payment_failed"


def test_full_flow_through_the_api(api):
    c = api.client
    for e in ("new@example.com", "other@example.com"):
        asyncio.run(api.db.access_trials.insert_one({"_id": e, "started_at": time.time(), "ends_at": time.time() + 7 * 86400}))
    owner, user, other = api.cookie("owner@example.com", "admin"), api.cookie("new@example.com"), api.cookie("other@example.com")
    assert c.get("/api/billing/me").status_code == 401

    me = c.get("/api/billing/me", headers=user).json()                               # day 1: free trial, nothing paid, Premium locked
    assert me["status"] == "none" and me["offers"]["premium"]["today_inr"] == 189 and me["offers"]["premium"]["next_charge_inr"] == 399 and not me["premium"]
    assert c.get("/api/access/me", headers=user).json()["premium"] is False
    assert c.get("/api/premium/indices", headers=user).status_code == 403

    offer = me["offers"]["premium"]
    ok = consent_for(offer)
    for bad in ({**ok, "accept_recurring": False}, {**ok, "accept_terms": False}, {**ok, "next_charge_inr": 189}, {**ok, "terms_version": "old"}):
        assert c.post("/api/billing/checkout", json={"plan": "premium", "consent": bad}, headers=user).status_code == 409
    assert c.post("/api/billing/checkout", json={"plan": "gold", "consent": ok}, headers=user).status_code == 422
    made = c.post("/api/billing/checkout", json={"plan": "premium", "consent": ok}, headers=user).json()
    oid = made["order"]["id"]
    assert made["order"]["amount"] == 189 and made["order"]["code"].startswith("ED-")
    assert c.get("/api/premium/indices", headers=user).status_code == 403            # asking is not paying: still locked
    assert c.get("/api/billing/admin/orders", headers=user).status_code == 403
    assert c.post(f"/api/billing/admin/orders/{oid}/confirm", json={"reference": "UPI123456", "amount": 189}, headers=user).status_code == 403
    assert c.post(f"/api/billing/admin/orders/{oid}/confirm", json={"reference": "UPI123456", "amount": 100}, headers=owner).status_code == 422
    assert c.post(f"/api/billing/admin/orders/{oid}/confirm", json={"reference": "UPI123456", "amount": 189}, headers=owner).status_code == 200
    paid = c.get("/api/billing/me", headers=user).json()
    assert paid["status"] == "active" and paid["plan"] == "premium" and paid["premium"] and paid["promo_used"]
    assert c.get("/api/access/me", headers=user).json()["premium"] is True
    assert c.get("/api/premium/indices", headers=user).status_code == 200
    assert paid["offers"]["premium"]["today_inr"] == 399 and paid["offers"]["premium"]["promo"] is False

    again = c.post("/api/billing/checkout", json={"plan": "premium", "consent": consent_for(paid["offers"]["premium"])}, headers=user).json()
    assert again["order"]["amount"] == 399                                           # renewal price, no second offer
    assert c.post(f"/api/billing/admin/orders/{again['order']['id']}/confirm", json={"reference": "UPI123456", "amount": 399}, headers=owner).status_code == 409  # reference reuse
    assert c.post(f"/api/billing/admin/orders/{again['order']['id']}/confirm", json={"reference": "UPI999999", "amount": 399}, headers=owner).status_code == 200
    assert c.get("/api/billing/me", headers=user).json()["period_end"] > paid["period_end"]

    assert c.post("/api/billing/cancel", headers=user).json()["cancel_at_period_end"] is True
    assert c.get("/api/billing/me", headers=user).json()["status"] == "cancelling" and c.get("/api/premium/indices", headers=user).status_code == 200
    assert c.post("/api/billing/resume", headers=user).json()["cancel_at_period_end"] is False

    std = c.get("/api/billing/me", headers=other).json()["offers"]["standard"]       # Standard for ₹189 keeps the desk open, not Premium
    o2 = c.post("/api/billing/checkout", json={"plan": "standard", "consent": consent_for(std)}, headers=other).json()["order"]
    assert o2["amount"] == 189
    assert c.post(f"/api/billing/admin/orders/{o2['id']}/confirm", json={"reference": "UPI555555", "amount": 189}, headers=owner).status_code == 200
    got = c.get("/api/billing/me", headers=other).json()
    assert got["plan"] == "standard" and not got["premium"] and c.get("/api/premium/indices", headers=other).status_code == 403
    assert c.get("/api/access/me", headers=other).json()["role"] == "subscriber"       # the desk itself stays open


def test_lapse_trial_expiry_and_failed_payment_close_paid_access(api):
    c = api.client
    asyncio.run(api.db.access_trials.insert_one({"_id": "gone@example.com", "started_at": 1, "ends_at": time.time() - 100}))
    user, owner = api.cookie("gone@example.com"), api.cookie("owner@example.com", "admin")
    assert c.get("/api/billing/me", headers=user).json()["notices"][0]["code"] == "trial_ended"   # trial over: the plans page still opens
    assert c.get("/api/premium/indices", headers=user).status_code == 402
    t = plans.terms(None, "standard", time.time(), False)
    order = asyncio.run(store.checkout("gone@example.com", "standard", consent_for(t)))["order"]
    asyncio.run(store.confirm_order(order["id"], "UPI777777", 189, now=time.time() - 40 * 86400))   # bought 40 days ago: that month is over
    assert c.get("/api/premium/indices", headers=user).status_code == 402              # that paid month is over
    asyncio.run(store.mark_payment_failed("gone@example.com"))
    sub = asyncio.run(store.get_sub("gone@example.com"))
    assert plans.notices(sub, time.time(), time.time() - 100, False)[0]["code"] == "payment_failed"
    with pytest.raises(HTTPException):
        asyncio.run(store.mark_payment_failed("nobody@example.com"))
    assert c.post("/api/billing/admin/payment-failed", json={"email": "gone@example.com"}, headers=api.cookie("viewer@example.com")).status_code == 403
    assert c.get("/api/public/plan").json()["premium_inr"] == 399 and c.get("/api/public/plan").json()["price_inr"] == 189
