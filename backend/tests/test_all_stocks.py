"""Every NSE stock is searchable, and a stock that is not on the live feed gets an honest end-of-day page built from stored daily candles."""
import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from jobs import upstox  # noqa: E402
from premium import directory, endofday, history  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401

IST = ZoneInfo("Asia/Kolkata")
ITEMS = [{"symbol": "RELIANCE", "name": "Reliance Industries Ltd"}, {"symbol": "ZOMATO", "name": "Zomato Ltd"}, {"symbol": "RELINFRA", "name": "Reliance Infrastructure Ltd"},
         {"symbol": "TATAPOWER", "name": "Tata Power Company Ltd"}, {"symbol": "bad symbol", "name": "ignored"}, {"symbol": "ZOMATO", "name": "duplicate"}]


def daily_bars(n=80, start=100.0):
    day = datetime(2026, 6, 1, tzinfo=IST)
    bars, price = [], start
    for i in range(n):
        price += 0.8 if i % 7 else -1.5
        stamp = day + timedelta(days=i)
        if stamp.weekday() >= 5:
            continue
        bars.append({"time": int(stamp.timestamp()), "open": price - 0.4, "high": price + 1.1, "low": price - 1.2, "close": price, "volume": 1000 + i})
    return bars


def run(coro):
    return asyncio.run(coro)


def test_directory_keeps_valid_unique_symbols_and_searches_by_name_and_symbol():
    d = directory.unpack(directory.pack(ITEMS, "test"))
    assert d.symbols == ["RELIANCE", "RELINFRA", "TATAPOWER", "ZOMATO"] and d.loaded and d.names[3] == "Zomato Ltd"
    assert [h["symbol"] for h in directory.search(d, "RELIANCE")] == ["RELIANCE", "RELINFRA"]       # the exact symbol first, then a company whose name has the word
    assert [h["symbol"] for h in directory.search(d, "reli")] == ["RELIANCE", "RELINFRA"]            # symbol prefix, shortest first
    assert directory.search(d, "power")[0]["symbol"] == "TATAPOWER"                                   # matched on a word of the company name
    assert directory.search(d, "company")[0]["symbol"] == "TATAPOWER"
    assert directory.search(d, "nothing like this") == [] and len(directory.search(d, "", limit=2)) == 2


def test_missing_or_damaged_directory_falls_back_to_the_live_list_and_says_so():
    for bad in (None, {}, {"symbols": ["A"], "names": []}):
        d = directory.unpack(bad)
        assert not d.loaded and "RELIANCE" in d.symbols and len(d) >= 100


def test_only_company_shares_come_from_the_upstox_list():
    rows = [{"trading_symbol": "ABC", "name": "ABC Ltd", "instrument_key": "NSE_EQ|INE000000001", "segment": "NSE_EQ", "instrument_type": "EQ", "isin": "INE000000001"},
            {"trading_symbol": "GOLDETF", "name": "Gold ETF", "instrument_key": "NSE_EQ|INF000000001", "segment": "NSE_EQ", "instrument_type": "EQ", "isin": "INF000000001"},
            {"trading_symbol": "NIFTY24OCTFUT", "instrument_key": "NSE_FO|1", "segment": "NSE_FO", "instrument_type": "FUT"},
            {"trading_symbol": "NOKEY", "name": "No key", "segment": "NSE_EQ", "instrument_type": "EQ"},
            {"trading_symbol": "ABC", "name": "dup", "instrument_key": "NSE_EQ|X", "segment": "NSE_EQ", "instrument_type": "EQ"}]
    assert upstox.directory_items(rows) == [{"symbol": "ABC", "name": "ABC Ltd", "key": "NSE_EQ|INE000000001"}]


def test_end_of_day_quote_and_market_never_pose_as_live():
    bars = daily_bars()
    q, m = endofday.quote("ZOMATO", "Zomato Ltd", bars), endofday.market(bars)
    assert q["ltp"] == bars[-1]["close"] and q["prev_close"] == bars[-2]["close"] and q["end_of_day"] is True
    assert m["state"] == "END_OF_DAY" and "not a live price" in m["message"] and m["as_of"] == datetime.fromtimestamp(bars[-1]["time"], IST).date().isoformat()
    assert endofday.quote("X", "X", []) is None and endofday.market([])["as_of"] is None


def test_search_endpoint_needs_premium_and_marks_what_is_live(api):
    paid = api.cookie("paid@example.com")
    assert api.client.get("/api/premium/directory?q=reli", headers=api.cookie("viewer@example.com")).status_code == 403
    fallback = api.client.get("/api/premium/directory?q=reliance", headers=paid).json()
    assert fallback["loaded"] is False and fallback["items"][0] == {"symbol": "RELIANCE", "name": "Reliance Industries", "live": True, "sector": "Energy"}
    run(directory.save(api.db, ITEMS, "test"))
    loaded = api.client.get("/api/premium/directory?q=zom", headers=paid).json()
    assert loaded["loaded"] is True and loaded["total"] == 4 and loaded["items"] == [{"symbol": "ZOMATO", "name": "Zomato Ltd", "live": False, "sector": None}]
    assert api.client.get("/api/premium/directory?q=" + "x" * 41, headers=paid).status_code == 422


def test_stock_off_the_live_feed_gets_an_end_of_day_page_from_stored_candles(api):
    paid = api.cookie("paid@example.com")
    run(directory.save(api.db, ITEMS, "test"))
    bars = daily_bars()
    run(history.merge_save(api.db, "ZOMATO", "1d", bars))
    res = api.client.get("/api/premium/stock/zomato?interval=5", headers=paid)       # an intraday timeframe is not possible here: it becomes daily
    assert res.status_code == 200
    body = res.json()
    assert body["live"] is False and body["name"] == "Zomato Ltd" and body["market"]["state"] == "END_OF_DAY"
    assert body["quote"]["ltp"] == bars[-1]["close"] and body["analysis"]["interval"] == 1440 and body["analysis"]["history_available"] is True
    assert body["engine"]["data"]["status"] == "HISTORICAL" and "not a live price" in body["engine"]["data"]["message"]
    weekly = api.client.get("/api/premium/stock/ZOMATO?interval=10080", headers=paid).json()
    assert weekly["analysis"]["interval"] == 10080 and weekly["live"] is False


def test_a_stock_with_no_stored_history_shows_no_price_instead_of_inventing_one(api):
    run(directory.save(api.db, ITEMS, "test"))
    body = api.client.get("/api/premium/stock/RELINFRA?interval=1440", headers=api.cookie("paid@example.com")).json()
    assert body["quote"] is None and body["analysis"]["history_available"] is False and "No stored price history" in body["market"]["message"]


def test_unknown_symbols_are_still_404_and_live_stocks_still_live(api):
    paid = api.cookie("paid@example.com")
    run(directory.save(api.db, ITEMS, "test"))
    assert api.client.get("/api/premium/stock/NOTASTOCK", headers=paid).status_code == 404
    assert api.client.get("/api/premium/stock/ZOMATO?interval=7", headers=paid).status_code == 404       # not a supported timeframe
    assert api.client.get("/api/premium/stock/ZOMATO?ema_fast=20&ema_slow=9", headers=paid).status_code == 422
    assert api.client.get("/api/premium/stock/RELIANCE?interval=5", headers=paid).json()["live"] is True


def test_history_memory_cache_stays_bounded(api, monkeypatch):
    import routers.premium_market as rpm

    monkeypatch.setattr(rpm, "HISTORY_MAX", 3)
    for i in range(6):
        sym = f"S{i}"
        run(history.merge_save(api.db, sym, "1d", daily_bars(30)))
        run(rpm._history(sym))
    assert len(rpm._history_cache) == 3 and "S5" in rpm._history_cache and "S0" not in rpm._history_cache
