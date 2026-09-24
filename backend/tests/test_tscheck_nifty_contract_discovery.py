"""Criterion: Current NIFTY contract discovery is ready.

GET /api/market-data/feed-status must expose the currently selected NIFTY expiry
sourced from the live scrip master, and neither it nor GET /api/market-data/dashboard
must ever return a broker URL, session token, sid, or raw credential value.
"""

import re

CREDENTIAL_MARKERS = [
    "baseurl",
    "feedurl",
    "\"sid\"",
    "access_token",
    "totp_secret",
    "consumer_secret",
    "mpin",
]

EXPIRY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_feed_status_exposes_current_nifty_expiry_without_credentials(client):
    response = client.get("/market-data/feed-status")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["expiry"] is not None, "feed-status must expose the currently selected NIFTY expiry"
    assert EXPIRY_PATTERN.match(body["expiry"]), body["expiry"]

    raw = response.text.lower()
    for marker in CREDENTIAL_MARKERS:
        assert marker not in raw, f"feed-status leaked marker: {marker}"


def test_dashboard_exposes_expiry_without_credentials(client):
    response = client.get("/market-data/dashboard", params={"symbol": "NIFTY"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["expiry"], "dashboard must expose the currently selected NIFTY expiry/placeholder"

    raw = response.text.lower()
    for marker in CREDENTIAL_MARKERS:
        assert marker not in raw, f"dashboard leaked marker: {marker}"
