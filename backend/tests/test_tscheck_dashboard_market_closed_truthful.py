"""Criterion: Dashboard never silently falls back to DEMO in LIVE mode.

GET /api/market-data/dashboard?symbol=NIFTY must return source KOTAK_NEO. Per the
current spec, NIFTY has a verified KOTAK_NEO snapshot from trading day 2026-09-24,
so the dashboard now truthfully shows that LAST VERIFIED snapshot (real spot/chain,
real last_tick) rather than a zeroed placeholder -- it must never be DEMO data, and
FINNIFTY (which has no verified tick yet) must still return an empty chain / null
tick rather than fabricating one.
"""


def test_dashboard_reports_kotak_neo_last_verified_snapshot_for_nifty(client):
    dashboard = client.get("/market-data/dashboard", params={"symbol": "NIFTY"})
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()

    assert body["feed"]["source"] == "KOTAK_NEO", body["feed"]
    # NIFTY has a verified snapshot per seed_facts -- must show real data, not DEMO/zeroed.
    assert body["spot"]["ltp"] > 0, "NIFTY must show its last verified non-zero spot price"
    assert body["feed"]["last_tick"], "NIFTY must carry its last verified real tick timestamp"
    assert len(body["option_chain"]) >= 21


def test_dashboard_reports_finnifty_waiting_with_no_fabricated_tick(client):
    dashboard = client.get("/market-data/dashboard", params={"symbol": "FINNIFTY"})
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()

    assert body["feed"]["source"] == "KOTAK_NEO", body["feed"]
    assert body["option_chain"] == [], "FINNIFTY option chain must be empty before any real tick has arrived"
    assert body["feed"]["last_tick"] is None, (
        "FINNIFTY has no verified tick yet per seed_facts, so feed.last_tick must stay null "
        f"rather than fabricating {body['feed']['last_tick']!r}"
    )
