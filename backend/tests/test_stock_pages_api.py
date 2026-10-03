"""API for the per-stock pages: meta, engine, custom EMA periods, 30m/monthly frames, gating."""
from tests.test_premium import api  # noqa: F401  (shared API fixture with the access database stubbed)


def owner(api):  # noqa: F811
    return api.cookie("paid@example.com")


def test_stock_detail_carries_name_sector_engine_and_ema_periods(api):
    j = api.client.get("/api/premium/stock/TCS?interval=5&ema_fast=5&ema_slow=40", headers=owner(api)).json()
    assert j["name"] == "Tata Consultancy Services" and j["sector"] == "IT" and j["analysis"]["ema_periods"] == [5, 40]
    e = j["engine"]
    assert e["bias"] == "Unavailable" and e["data"]["status"] == "UNAVAILABLE" and e["setup"] is None and e["generated_at"]  # no live feed in CI: no signal, never an invented one


def test_stock_without_enough_candles_is_unavailable_not_neutral(api):
    j = api.client.get("/api/premium/stock/RELIANCE", headers=owner(api)).json()
    assert j["engine"]["bias"] == "Unavailable" and j["engine"]["action"] == "NONE"


def test_new_frames_and_ema_validation(api):
    for minutes in (30, 43200):
        a = api.client.get(f"/api/premium/stock/INFY?interval={minutes}", headers=owner(api)).json()["analysis"]
        assert a["interval"] == minutes
    assert api.client.get("/api/premium/stock/INFY?ema_fast=20&ema_slow=9", headers=owner(api)).status_code == 422
    assert api.client.get("/api/premium/stock/INFY?ema_fast=1", headers=owner(api)).status_code == 422
    assert api.client.get("/api/premium/index/NIFTY?ema_fast=12&ema_slow=26", headers=owner(api)).json()["analysis"]["ema_periods"] == [12, 26]
    assert api.client.get("/api/premium/index/NIFTY?ema_fast=30&ema_slow=10", headers=owner(api)).status_code == 422


def test_stock_list_and_meta_cover_all_129_with_sectors(api):
    rows = api.client.get("/api/premium/stocks", headers=owner(api)).json()["stocks"]
    assert len(rows) == 129 and all(r["name"] and r["sector"] for r in rows)
    meta = api.client.get("/api/premium/stocks-meta", headers=owner(api)).json()
    assert len(meta["stocks"]) == 129 and "Banks" in meta["sectors"] and {"symbol", "name", "sector"} <= set(meta["stocks"][0])


def test_free_users_cannot_reach_any_of_it(api):
    free = api.cookie("viewer@example.com")
    for path in ("/api/premium/stocks-meta", "/api/premium/stock/TCS?ema_fast=5&ema_slow=40", "/api/premium/stock/TCS?interval=43200"):
        r = api.client.get(path, headers=free)
        assert r.status_code == 403 and "engine" not in r.text and "sector" not in r.text
