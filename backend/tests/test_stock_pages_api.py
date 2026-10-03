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


def test_stock_news_is_premium_only_validates_the_symbol_and_survives_provider_failure(api, monkeypatch):
    from premium import news

    async def fake(symbol, limit=4, client=None):
        return {"status": "ok", "provider": news.PROVIDER, "items": [{"title": f"{symbol} results", "link": "https://example.com/a", "source": "Example", "published_at": None}]}

    async def boom(symbol, limit=4, client=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(news, "headlines", fake)
    ok = api.client.get("/api/premium/stock/TCS/news", headers=owner(api)).json()
    assert ok["symbol"] == "TCS" and ok["news"]["items"][0]["title"] == "TCS results" and "not verified" in ok["note"]
    assert api.client.get("/api/premium/stock/NOPE/news", headers=owner(api)).status_code == 404
    assert api.client.get("/api/premium/stock/TCS/news", headers=api.cookie("viewer@example.com")).status_code == 403
    monkeypatch.setattr(news, "headlines", boom)
    down = api.client.get("/api/premium/stock/TCS/news", headers=owner(api))
    assert down.status_code == 200 and down.json()["news"]["status"] == "unavailable" and down.json()["news"]["items"] == []


# ------------------------------------------------------------------ the last recorded session while the market is closed
def _seed_session(api, symbol, day, base=100.0, n=60):
    import asyncio
    from datetime import datetime

    from premium.market import IST

    t0 = int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())
    docs = [{"_id": f"{symbol}:{t0 + i * 60}", "symbol": symbol, "trading_day": day.isoformat(), "time": t0 + i * 60, "open": base + i * 0.1, "high": base + i * 0.1 + 0.2,
             "low": base + i * 0.1 - 0.1, "close": base + i * 0.1 + 0.1, "volume": 1000 + i, "ticks": 3} for i in range(n)]
    asyncio.run(api.db.premium_candles.insert_many(docs))


def _market(monkeypatch, open_):
    import premium.market as pm
    import routers.premium_market as rpm

    monkeypatch.setattr(rpm, "market_hours", lambda now: open_)
    monkeypatch.setattr(pm, "market_hours", lambda now: open_)
    monkeypatch.setattr(rpm, "_live", lambda: True)


def test_closed_market_with_no_candles_today_shows_the_last_recorded_session_clearly_labelled(api, monkeypatch):
    from datetime import date

    _seed_session(api, "TCS", date(2026, 5, 1))
    _seed_session(api, "TCS", date(2026, 5, 4), base=102.0)
    _market(monkeypatch, open_=False)
    j = api.client.get("/api/premium/stock/TCS?interval=1", headers=owner(api)).json()
    a = j["analysis"]
    assert a["session_day"] == "2026-05-04" and len(a["candles"]) == 60 and a["candles"][0]["open"] == 102.0
    assert a["levels"]["pivots"] is not None  # pivots come from the session BEFORE the one shown (2026-05-01)
    assert j["engine"]["data"]["status"] == "HISTORICAL" and j["engine"]["bias"] != "Unavailable"
    five = api.client.get("/api/premium/stock/TCS?interval=5", headers=owner(api)).json()["analysis"]
    assert five["session_day"] == "2026-05-04" and len(five["candles"]) == 12


def test_the_stock_list_uses_the_last_session_for_its_quick_signal_when_closed(api, monkeypatch):
    from datetime import date, datetime, timezone

    from premium.market import premium_market

    _seed_session(api, "TCS", date(2026, 5, 4))
    _market(monkeypatch, open_=False)
    now = datetime.now(timezone.utc)
    premium_market.quotes["TCS"] = {"symbol": "TCS", "name": "Tata Consultancy Services", "kind": "stock", "ltp": 106.1, "change": 1.0, "change_pct": 1.0, "updated_at": now.isoformat(), "_ts": now}
    row = next(r for r in api.client.get("/api/premium/stocks", headers=owner(api)).json()["stocks"] if r["symbol"] == "TCS")
    assert row["signal"]["action"] != "BUILDING" and row["signal"]["bars_closed"] >= 35


def test_during_market_hours_an_empty_day_is_never_filled_with_yesterdays_candles(api, monkeypatch):
    from datetime import date

    _seed_session(api, "TCS", date(2026, 5, 4))
    _market(monkeypatch, open_=True)
    a = api.client.get("/api/premium/stock/TCS?interval=1", headers=owner(api)).json()["analysis"]
    assert a["session_day"] is None and a["candles"] == []  # live means today's ticks; yesterday must not pass for them


def test_no_recorded_session_at_all_stays_empty_without_error(api, monkeypatch):
    _market(monkeypatch, open_=False)
    a = api.client.get("/api/premium/stock/INFY?interval=1", headers=owner(api)).json()["analysis"]
    assert a["session_day"] is None and a["candles"] == []


def test_announcements_parse_defensively_and_endpoint_degrades_to_unavailable(api, monkeypatch):
    from premium import announcements as an

    items = an.parse([{"desc": "Outcome of Board Meeting", "attchmntText": "Dividend declared", "an_dt": "03-Oct-2026 18:30:12", "attchmntFile": "https://nsearchives.nseindia.com/a.pdf"},
                      {"desc": "x", "attchmntFile": "javascript:alert(1)"}, "junk", {}])
    assert len(items) == 2 and items[0]["sentiment"]["tone"] == "Positive" and items[0]["published_at"].startswith("2026-10-03") and items[1]["link"] is None
    assert an.parse({"unexpected": 1}) == [] and an.parse(None) == []

    async def down(symbol, client=None):
        raise RuntimeError("blocked")

    monkeypatch.setattr(an, "fetch", down)
    r = api.client.get("/api/premium/stock/TCS/announcements", headers=owner(api))
    assert r.status_code == 200 and r.json()["announcements"]["status"] == "unavailable" and r.json()["announcements"]["items"] == []
    assert api.client.get("/api/premium/stock/NOPE/announcements", headers=owner(api)).status_code == 404
    assert api.client.get("/api/premium/stock/TCS/announcements", headers=api.cookie("viewer@example.com")).status_code == 403
