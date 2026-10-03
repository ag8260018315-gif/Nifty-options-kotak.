"""Premium: server-side access control, entitlement lifecycle, live-data store, analysis and feed classification."""
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from mongomock_motor import AsyncMongoMockClient

IST = ZoneInfo("Asia/Kolkata")

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")


@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from lib import access, premium

    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SECRET", "x" * 40)
    monkeypatch.setenv("ADMIN_EMAILS", "owner@example.com")
    db = AsyncMongoMockClient()["t"]
    for name in ("access_users", "access_trials", "premium_access", "premium_requests", "access_codes", "access_requests"):
        monkeypatch.setitem(access._collection_override, name, db[name])
    from lib.candles import candle_store
    from premium.market import premium_market
    import routers.premium_market as rpm

    monkeypatch.setattr(candle_store, "_collection_override", db["index_candles"])
    monkeypatch.setattr(premium_market, "collection_override", db["premium_candles"])
    monkeypatch.setattr(premium_market, "quotes_override", db["premium_quotes"])
    monkeypatch.setattr(premium_market, "_quotes_restored", False)
    premium_market.quotes.clear()
    monkeypatch.setattr(rpm, "research_db", AsyncMongoMockClient()["research"])
    rpm._prev_cache.clear()
    rpm._quick_cache.clear()
    premium._cache.clear()
    access._trial_cache.clear()
    access._db_users.clear()
    monkeypatch.setattr(access, "_db_users_loaded_at", 0.0)
    import server

    client = TestClient(server.app)

    def cookie(email, role="viewer"):
        token, _ = access.issue_session(email, role)
        return {"Cookie": f"{access.COOKIE_NAME}={token}"}

    async def seed():
        await db.access_trials.insert_one({"_id": "trial@example.com", "started_at": time.time(), "ends_at": time.time() + 86400})
        await db.access_trials.insert_one({"_id": "old@example.com", "started_at": 1, "ends_at": time.time() - 10})
        for e in ("viewer@example.com", "paid@example.com", "lapsed@example.com"):
            await db.access_users.insert_one({"_id": e})
        await db.premium_access.insert_one({"_id": "paid@example.com", "until": time.time() + 86400})
        await db.premium_access.insert_one({"_id": "lapsed@example.com", "until": time.time() - 5})

    import asyncio

    asyncio.run(seed())
    return SimpleNamespace(client=client, cookie=cookie, db=db)


PREMIUM_PATHS = ["/api/premium/status", "/api/premium/indices", "/api/premium/index/NIFTY", "/api/premium/stocks",
                 "/api/premium/stocks/opportunities", "/api/premium/stock/RELIANCE"]


@pytest.mark.parametrize("path", PREMIUM_PATHS)
def test_signed_out_is_401(api, path):
    assert api.client.get(path).status_code == 401


@pytest.mark.parametrize("email", ["trial@example.com", "viewer@example.com", "lapsed@example.com"])
@pytest.mark.parametrize("path", PREMIUM_PATHS)
def test_free_users_get_403_and_no_data(api, path, email):
    r = api.client.get(path, headers=api.cookie(email))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "premium_required"
    assert "quote" not in r.text and "analysis" not in r.text


def test_expired_trial_is_blocked_before_premium(api):
    assert api.client.get("/api/premium/status", headers=api.cookie("old@example.com")).status_code == 402


@pytest.mark.parametrize("email", ["paid@example.com", "owner@example.com"])
def test_premium_and_owner_get_through(api, email):
    r = api.client.get("/api/premium/status", headers=api.cookie(email))
    assert r.status_code == 200 and r.json()["label"] == "PREMIUM"
    assert api.client.get("/api/premium/index/NIFTY", headers=api.cookie(email)).status_code == 200


def test_me_reports_premium_flag(api):
    assert api.client.get("/api/access/me", headers=api.cookie("paid@example.com")).json()["premium"] is True
    assert api.client.get("/api/access/me", headers=api.cookie("viewer@example.com")).json()["premium"] is False


def test_only_owner_can_grant_and_revoke(api):
    body = {"email": "viewer@example.com", "days": 30}
    assert api.client.post("/api/access/admin/premium", json=body, headers=api.cookie("viewer@example.com")).status_code == 403
    assert api.client.post("/api/access/admin/premium", json=body, headers=api.cookie("paid@example.com")).status_code == 403
    assert api.client.get("/api/premium/status", headers=api.cookie("viewer@example.com")).status_code == 403
    assert api.client.post("/api/access/admin/premium", json=body, headers=api.cookie("owner@example.com")).status_code == 200
    from lib import premium

    premium._cache.clear()
    assert api.client.get("/api/premium/status", headers=api.cookie("viewer@example.com")).status_code == 200
    assert api.client.post("/api/access/admin/premium/revoke", json={"email": "viewer@example.com"}, headers=api.cookie("owner@example.com")).status_code == 200
    assert api.client.get("/api/premium/status", headers=api.cookie("viewer@example.com")).status_code == 403


def test_forged_cookie_is_rejected(api):
    assert api.client.get("/api/premium/status", headers={"Cookie": "nod_session=not-a-real-token"}).status_code == 401


def test_free_users_still_reach_the_existing_dashboard(api):
    assert api.client.get("/api/market-data/feed-status", headers=api.cookie("trial@example.com")).status_code == 200


def test_no_demo_prices_when_feed_not_connected(api):
    j = api.client.get("/api/premium/indices", headers=api.cookie("owner@example.com")).json()
    assert all(r["quote"] is None and r["market"]["state"] == "NO_FEED" for r in j["indices"])


# ------------------------------------------------------------------ market store
from premium.market import PremiumMarket, market_state  # noqa: E402


def at(h, m, s=0, day=3):  # Wednesday 3 June 2026
    return datetime(2026, 6, day, h, m, s, tzinfo=IST)


def tick(key, ltp, vol=None, **extra):
    return {"kind": "premium", "keys": [key], "name": "", "token": "1", "ltp": ltp, **({"volume": vol} if vol is not None else {}), **extra}


def test_market_state_open_delayed_closed():
    assert market_state(at(11, 0, 5), at(11, 0, 1))["state"] == "OPEN"
    assert market_state(at(11, 0, 40), at(11, 0, 1))["state"] == "DELAYED"
    assert market_state(at(11, 0), None)["state"] == "DELAYED"
    assert market_state(at(16, 0), at(15, 29))["state"] == "CLOSED"
    assert market_state(at(11, 0, day=6), at(11, 0, day=6))["state"] == "CLOSED"  # Saturday


def test_candles_with_volume_deltas_and_session_hours():
    m = PremiumMarket()
    m.configure({"nse_cm|1": "TCS"}, {"TCS": "TCS"}, {"TCS": "stock"})
    m.on_tick(tick("nse_cm|1", 100, 1000), at(9, 30, 5))   # baseline only: no volume counted
    m.on_tick(tick("nse_cm|1", 101, 1500), at(9, 30, 30))
    m.on_tick(tick("nse_cm|1", 99, 1800), at(9, 31, 2))
    m.on_tick(tick("nse_cm|1", 50, 9999), at(8, 0))          # pre-open: quote updates, no candle
    bars = sorted(m.candles["TCS"].values(), key=lambda b: b["time"])
    assert [b["volume"] for b in bars] == [500, 300] and bars[0]["high"] == 101 and bars[1]["close"] == 99
    assert len(bars) == 2 and m.quotes["TCS"]["ltp"] == 50


def test_unknown_symbols_and_bad_prices_ignored():
    m = PremiumMarket()
    m.configure({"nse_cm|1": "TCS"}, {"TCS": "TCS"}, {"TCS": "stock"})
    m.on_tick(tick("nse_cm|999", 10), at(10, 0))
    m.on_tick(tick("nse_cm|1", 0), at(10, 0))
    assert m.quotes == {}


def test_sensex_matched_by_name_and_change_computed():
    m = PremiumMarket()
    m.configure({"bse_cm|SENSEX": "SENSEX"}, {"SENSEX": "SENSEX"}, {"SENSEX": "index"})
    m.on_tick({"kind": "premium", "keys": ["bse_cm|1"], "name": "SENSEX", "token": "1", "ltp": 82000.0, "close": 81000.0}, at(10, 0))
    q = m.public_quote("SENSEX")
    assert q["change"] == 1000.0 and q["change_pct"] == 1.23 and "_ts" not in q


async def test_persistence_and_previous_session_levels():
    m = PremiumMarket()
    _db = AsyncMongoMockClient()["t"]
    m.collection_override, m.quotes_override = _db["premium_candles"], _db["premium_quotes"]
    m.configure({"nse_cm|1": "TCS"}, {"TCS": "TCS"}, {"TCS": "stock"})
    for minute, price in enumerate([100, 105, 98, 102]):
        m.on_tick(tick("nse_cm|1", price, 1000 * (minute + 1)), at(10, minute, 5, day=2))
    await m.flush(force=True)
    fresh = PremiumMarket()
    fresh.collection_override, fresh.quotes_override = m.collection_override, m.quotes_override
    prev = await fresh.previous_session("TCS", at(10, 0, day=3))
    assert prev == {"high": 105, "low": 98, "close": 102}
    assert await fresh.previous_session("TCS", at(10, 0, day=2)) is None  # nothing earlier than that day
    restored = await fresh.today_bars("TCS", at(10, 5, day=2))
    assert len(restored) == 4


# ------------------------------------------------------------------ feed classification and universe
def test_premium_ticks_are_separated_from_nifty_ticks():
    from lib import kotak_feed
    from premium.universe import PremiumPlan

    plan = PremiumPlan(symbol_by_key={"nse_cm|1594": "INFY", "bse_cm|SENSEX": "SENSEX"})
    feed = kotak_feed.KotakSFeed.__new__(kotak_feed.KotakSFeed)
    feed.premium = plan

    class Scrip(kotak_feed.SFeedScrip):  # real SDK class so the isinstance checks hold
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Index(kotak_feed.SFeedIndex):
        def __init__(self, **kw):
            self.__dict__.update(kw)

    stock = feed._premium_tick(Scrip(exchange_segment="nse_cm", instrument_token="1594", last_traded_price=1500.5, volume_traded_today=12345, close_price=1490.0, average_trade_price=1498.2))
    assert stock["kind"] == "premium" and stock["ltp"] == 1500.5 and stock["volume"] == 12345 and stock["vwap"] == 1498.2
    sensex = feed._premium_tick(Index(exchange_segment="bse_cm", instrument_token="1", name="SENSEX", last_traded_price=82000.0))
    assert sensex and sensex["name"] == "SENSEX"
    nifty = Index(exchange_segment="nse_cm", instrument_token="26000", name="Nifty 50", last_traded_price=22500.0)
    assert feed._premium_tick(nifty) is None  # NIFTY stays on the existing path
    assert feed._to_tick(nifty)["kind"] == "index"


def test_scrip_master_parser_picks_equity_rows_only():
    from premium.universe import parse_equities

    text = "pSymbol;,pSymbolName;,pTrdSymbol;,pGroup;\n1594,INFY,INFY-EQ,EQ\n9999,INFY,INFY-BE,BE\n2885,RELIANCE,RELIANCE-EQ,EQ\n1,OTHER,OTHER-EQ,EQ\n"
    found = parse_equities(text, ["INFY", "RELIANCE", "MISSING"])
    assert found == {"INFY": {"token": "1594", "trading_symbol": "INFY-EQ"}, "RELIANCE": {"token": "2885", "trading_symbol": "RELIANCE-EQ"}}


def test_premium_user_sees_stock_rows_with_real_ticks_only(api):
    from premium.market import premium_market

    premium_market.configure({"nse_cm|1": "TCS"}, {"TCS": "TCS"}, {"TCS": "stock"})
    premium_market.quotes.clear()
    premium_market.candles.clear()
    now = datetime.now(timezone.utc)
    premium_market.on_tick(tick("nse_cm|1", 4000.0, 100, close=3950.0), now)
    j = api.client.get("/api/premium/stocks", headers=api.cookie("paid@example.com")).json()
    row = next(r for r in j["stocks"] if r["symbol"] == "TCS")
    assert j["count"] == 1 and row["quote"]["ltp"] == 4000.0 and row["quote"]["change"] == 50.0
    assert row["signal"]["action"] == "BUILDING"  # a single tick is not enough for any signal
    assert api.client.get("/api/premium/stock/NOPE", headers=api.cookie("paid@example.com")).status_code == 404
    assert api.client.get("/api/premium/stocks", headers=api.cookie("viewer@example.com")).status_code == 403


def test_premium_request_is_rate_limited_and_needs_sign_in(api, monkeypatch):
    from lib import access

    async def fake_mail(*args, **kwargs):
        return True

    monkeypatch.setattr(access, "_send_mail", fake_mail)
    assert api.client.post("/api/access/premium-request").status_code == 401
    first = api.client.post("/api/access/premium-request", headers=api.cookie("viewer@example.com")).json()
    again = api.client.post("/api/access/premium-request", headers=api.cookie("viewer@example.com")).json()
    assert first["status"] == "requested" and again["status"] == "already_requested"


def test_circuit_breaker_switches_premium_off_after_quick_drops():
    m = PremiumMarket()
    m.note_disconnect(300)  # a normal long-lived connection
    assert not m.circuit_open
    m.note_disconnect(5)
    assert not m.circuit_open
    m.note_disconnect(8)
    assert m.circuit_open and "switched off" in m.subscription_error
    m2 = PremiumMarket()
    m2.note_disconnect(5)
    m2.note_disconnect(None)
    m2.note_disconnect(3600)  # a healthy session resets the count
    assert m2.quick_drops == 0


async def test_feed_off_switch_builds_an_empty_plan(monkeypatch):
    from premium.universe import build_plan

    monkeypatch.setenv("PREMIUM_FEED", "off")
    plan = await build_plan()
    assert plan.index_tokens == [] and plan.scrip_tokens == [] and "off" in plan.error


def test_stock_list_exists_before_any_feed_and_shows_no_invented_prices(api):
    """The reported bug: with the market closed and no feed, the page said 'No stock list is configured'."""
    j = api.client.get("/api/premium/stocks", headers=api.cookie("owner@example.com")).json()
    assert j["configured"] >= 100 and j["count"] == 0
    assert all(r["quote"] is None for r in j["stocks"]) and {"RELIANCE", "TCS", "M&M"} <= {r["symbol"] for r in j["stocks"]}
    assert api.client.get("/api/premium/stock/M%26M", headers=api.cookie("owner@example.com")).status_code == 200


async def test_last_prices_survive_a_restart():
    m = PremiumMarket()
    db = AsyncMongoMockClient()["t"]
    m.collection_override, m.quotes_override = db["c"], db["q"]
    m.configure({"nse_cm|1": "TCS"}, {"TCS": "TCS"}, {"TCS": "stock"})
    m.on_tick(tick("nse_cm|1", 4000.0, 100, close=3950.0), at(15, 20))
    await m.flush(force=True)
    fresh = PremiumMarket()
    fresh.collection_override, fresh.quotes_override = db["c"], db["q"]
    await fresh.ensure_quotes()
    q = fresh.public_quote("TCS")
    assert q["ltp"] == 4000.0 and q["change"] == 50.0 and fresh.last_tick("TCS") is not None
    fresh.configure({"nse_cm|1": "TCS"}, {"TCS": "TCS"}, {"TCS": "stock"})
    fresh.on_tick(tick("nse_cm|1", 4100.0, 100), at(9, 20, day=4))
    assert fresh.quotes["TCS"]["ltp"] == 4100.0  # a live tick replaces the stored one


def test_breakout_endpoint_ranks_by_score_and_never_claims_a_probability(api, monkeypatch):
    import routers.premium_market as rpm

    async def fake_news(symbol, *a, **k):
        return {"status": "ok", "provider": "Google News", "items": [{"title": f"{symbol} headline", "link": "https://example.com/x", "source": "Example", "published_at": None}]}

    monkeypatch.setattr(rpm.news, "headlines", fake_news)
    from premium.market import premium_market

    premium_market.configure({"nse_cm|1": "TCS", "nse_cm|2": "INFY"}, {}, {})
    now = datetime.now(timezone.utc)
    premium_market.on_tick(tick("nse_cm|1", 100.0, 10, close=99.0), now)
    premium_market.on_tick(tick("nse_cm|2", 50.0, 10, close=49.0), now)

    async def fake_analysis(symbol):
        base = {"interval": 5, "volume": {"available": True, "relative": 2.4, "buying_pressure_pct": 66}, "trend": {"label": "UPTREND"}, "vwap": 99.0}
        res = 100.8 if symbol == "TCS" else 51.5
        return {**base, "signal": {"action": "BUY", "score": 60, "price": 100.0 if symbol == "TCS" else 50.0, "rsi": 61.0}, "levels": {"nearest_resistance": res, "nearest_support": 98.0}}

    monkeypatch.setattr(rpm, "_quick_analysis", fake_analysis)
    j = api.client.get("/api/premium/stocks/breakouts", headers=api.cookie("paid@example.com")).json()
    assert [r["symbol"] for r in j["stocks"]] == ["TCS"]  # INFY is 3% below resistance: not listed
    top = j["stocks"][0]
    assert 0 < top["setup"]["score"] <= 100 and top["news"]["items"][0]["title"] == "TCS headline" and j["accuracy"]["validated"] is False
    assert "probab" in j["accuracy"]["note"] and "90" not in str(j)
    assert api.client.get("/api/premium/stocks/breakouts", headers=api.cookie("viewer@example.com")).status_code == 403


def test_breakout_list_shows_the_backtest_only_when_one_exists(api):
    import asyncio

    import routers.premium_market as rpm
    from premium import backtest as bt

    path = {"Cookie": api.cookie("paid@example.com")["Cookie"]}
    none = api.client.get("/api/premium/stocks/breakouts", headers=path).json()["accuracy"]
    assert none["validated"] is False and "backtest" not in none

    recs = [{"symbol": "A", "day": f"2026-06-{(i % 28) + 1:02d}", "score": 70, "result": "SUCCESS" if i % 2 else "STOP"} for i in range(250)]
    stored = bt.summarize(recs, bt.Rule(), sessions_tested=60, symbols_tested=30)
    asyncio.run(rpm.research_db["breakout_backtests"].replace_one({"_id": "latest"}, {"_id": "latest", **stored}, upsert=True))
    shown = api.client.get("/api/premium/stocks/breakouts", headers=path).json()["accuracy"]
    assert shown["validated"] is True and shown["backtest"]["setups"] == 250 and shown["backtest"]["hit_rate_pct"] == 50.0
    assert "definition" in shown["backtest"] and "promise" in shown["note"].lower()
