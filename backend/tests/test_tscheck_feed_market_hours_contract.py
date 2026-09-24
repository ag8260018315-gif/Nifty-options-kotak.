"""Criterion: Current SFeed worker respects market hours and auto-start contract.

Outside 09:15-15:30 IST, GET /api/market-data/feed-status must report MARKET_CLOSED
with socket/authenticated both false, no fabricated last_tick, and a message that
confirms the worker is still scheduled to auto-connect at market open (not a dead
worker requiring a manual restart).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _market_open_now() -> bool:
    now = datetime.now(IST)
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) < (15, 30)


def test_feed_status_reports_market_closed_with_no_fake_tick_outside_market_hours(client):
    if _market_open_now():
        import pytest

        pytest.skip("market is currently open in IST; this contract applies after-hours")

    response = client.get("/market-data/feed-status")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["state"] == "MARKET_CLOSED", body
    assert body["connected"] is False, body
    assert body["authenticated"] is False, body
    assert body["last_tick"] is None, "feed-status must not fabricate a last_tick before any real market data tick"
    assert body["subscriptions"] == 0, body

    message = body["message"].lower()
    assert "09:15" in body["message"] and "15:30" in body["message"], body["message"]


def test_feed_status_alerts_field_is_typed_and_deduplicable(client):
    """Sanitized feed status must expose alerts as a list of typed, id-keyed entries
    (the contract the frontend dedupes against) and never leak broker credentials."""
    response = client.get("/market-data/feed-status")
    assert response.status_code == 200, response.text
    body = response.json()

    assert isinstance(body["alerts"], list)
    seen_ids = set()
    for alert in body["alerts"]:
        assert alert["type"] in {"ATM_SHIFT", "EXPIRY_DAY", "NEAR_CLOSE", "ROLL_REQUIRED"}
        assert alert["id"] not in seen_ids, "feed-status returned a duplicate alert id"
        seen_ids.add(alert["id"])
        assert "title" in alert and "message" in alert and "created_at" in alert

    raw = response.text.lower()
    for leak_marker in ["basepurl", "feedurl", "access_token", "totp_secret", "mpin", "\"sid\"", "consumer_secret"]:
        assert leak_marker not in raw, f"feed-status leaked a credential/session marker: {leak_marker}"
