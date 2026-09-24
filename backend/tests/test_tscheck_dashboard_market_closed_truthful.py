"""Criterion: Dashboard never silently falls back to DEMO in LIVE mode.

GET /api/market-data/dashboard?symbol=NIFTY must return source KOTAK_NEO and state
MARKET_CLOSED with an empty option chain before any real tick has arrived -- never
simulated/demo data, and never a fabricated tick timestamp that implies a real tick
was received when feed-status says no tick exists yet.
"""


def test_dashboard_reports_kotak_neo_market_closed_with_empty_chain_before_ticks(client):
    feed_status = client.get("/market-data/feed-status")
    assert feed_status.status_code == 200, feed_status.text
    status_body = feed_status.json()

    dashboard = client.get("/market-data/dashboard", params={"symbol": "NIFTY"})
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()

    assert body["feed"]["source"] == "KOTAK_NEO", body["feed"]
    assert body["feed"]["state"] == "MARKET_CLOSED", body["feed"]
    assert body["spot"]["ltp"] == 0, "spot must not carry a simulated/nonzero price before a real tick"

    if status_body["last_tick"] is None:
        assert body["option_chain"] == [], "option chain must be empty before any real tick has arrived"
        assert body["feed"]["last_tick"] is None, (
            "feed-status reports no real tick yet (last_tick=null), but the dashboard's "
            f"feed.last_tick was {body['feed']['last_tick']!r} -- this is a fabricated tick "
            "timestamp, not real market data, and the dashboard schema must allow null here"
        )
