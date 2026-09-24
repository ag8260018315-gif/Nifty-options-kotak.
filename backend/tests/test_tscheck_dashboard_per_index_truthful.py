"""tscheck: Live or last-verified dashboard data is visible for every selector.

NIFTY and BANKNIFTY must show their last verified KOTAK_NEO snapshot after
close; FINNIFTY must return a 200 truthful KOTAK_NEO waiting snapshot (empty
chain, no fabricated tick) until its first market-hours tick. None may fall
back to DEMO in LIVE mode.
"""


def test_nifty_and_banknifty_show_last_verified_snapshot(client):
    for symbol in ("NIFTY", "BANKNIFTY"):
        response = client.get(f"/market-data/dashboard?symbol={symbol}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["symbol"] == symbol
        assert body["feed"]["source"] == "KOTAK_NEO", f"{symbol} fell back to non-KOTAK_NEO source"
        assert body["feed"]["last_tick"], f"{symbol} missing last verified tick"
        assert body["spot"]["ltp"] > 0, f"{symbol} spot ltp not verified/populated"
        assert len(body["option_chain"]) >= 21, f"{symbol} option chain not fully paired"


def test_finnifty_returns_truthful_waiting_snapshot_not_demo(client):
    response = client.get("/market-data/dashboard?symbol=FINNIFTY")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "FINNIFTY"
    # Must stay on the KOTAK_NEO feed identity even while waiting -- never DEMO.
    assert body["feed"]["source"] == "KOTAK_NEO"
    # No real tick has occurred yet -- must not fabricate one.
    assert body["feed"]["last_tick"] is None
    assert body["spot"]["timestamp"] is None
    assert body["option_chain"] == []
