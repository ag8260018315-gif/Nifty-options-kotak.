"""tscheck: All three Kotak indices are represented by the live worker.

GET /api/market-data/feed-status must expose NIFTY, BANKNIFTY, and FINNIFTY
index entries with master-derived expiries, truthful MARKET_CLOSED state
after hours, and no broker secrets/URLs leaked in the response body.
"""

import json

SECRET_MARKERS = (
    "baseurl", "feedurl", '"sid"', "access_token", "accesstoken",
    "totp_secret", "consumer_secret", "mpin", "password", "hsserverid",
)


def test_feed_status_exposes_all_three_indices_without_secrets(client):
    response = client.get("/market-data/feed-status")
    assert response.status_code == 200, response.text
    body = response.json()

    symbols = {item["symbol"] for item in body["indices"]}
    assert symbols == {"NIFTY", "BANKNIFTY", "FINNIFTY"}, f"unexpected index set: {symbols}"

    for item in body["indices"]:
        assert item["expiry"], f"{item['symbol']} missing master-derived expiry"
        assert item["expected_pairs"] == 21

    # Market is closed per seed_facts -> state must be truthfully reported, not faked LIVE.
    assert body["state"] == "MARKET_CLOSED"
    for item in body["indices"]:
        assert item["state"] == "MARKET_CLOSED"

    raw_lower = json.dumps(body).lower()
    for marker in SECRET_MARKERS:
        assert marker not in raw_lower, f"leaked secret marker '{marker}' in feed-status body"
