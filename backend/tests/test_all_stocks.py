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


# ------------------------------------------------------------------ loading every stock from the server (no PC)
import gzip  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from jobs import stock_loader  # noqa: E402


def share(i):
    return {"trading_symbol": f"STK{i}", "name": f"Stock {i} Ltd", "instrument_key": f"NSE_EQ|INE{i:06d}", "segment": "NSE_EQ", "instrument_type": "EQ", "isin": f"INE{i:06d}"}


def instrument_file(n=600):
    rows = [share(i) for i in range(n)] + [{"trading_symbol": "GOLDETF", "name": "x", "instrument_key": "k", "segment": "NSE_EQ", "instrument_type": "EQ", "isin": "INF000001"},
                                           {"trading_symbol": "WEIRD", "name": 'a ] , { "quote" } [', "instrument_key": "NSE_EQ|INE777777", "segment": "NSE_EQ", "instrument_type": "EQ"}]
    return gzip.compress(json.dumps(rows, indent=1).encode())


def test_big_instrument_file_is_read_in_a_stream_whatever_the_chunk_size():
    raw = instrument_file()
    for size in (1, 7, 100, 1 << 16):
        items = upstox.directory_items(upstox.iter_json_array(upstox._text_chunks(raw, size=size)))
        assert len(items) == 601 and items[-1]["name"] == 'a ] , { "quote" } [' and all(i["symbol"] != "GOLDETF" for i in items)
    plain = json.dumps([share(1), share(2)]).encode()                            # a plain (not gzip) file works too
    assert len(upstox.directory_items(upstox.iter_json_array(upstox._text_chunks(plain, size=5)))) == 2


def test_list_load_saves_the_directory_and_refuses_a_broken_file():
    db = AsyncMongoMockClient()["d"]

    def client(body):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))

    async def go():
        async with client(instrument_file()) as c:
            items = await stock_loader.load_list(db, c)
        small = gzip.compress(json.dumps([share(i) for i in range(10)]).encode())
        async with client(small) as c:
            with pytest.raises(stock_loader.LoaderError):
                await stock_loader.load_list(db, c)
        return len(items), len(await directory.load(db))

    directory._cache.clear()
    assert run(go()) == (601, 601)                                               # the broken file did not replace the good list


class FakeUpstox:
    """Stands in for upstox.fetch_range: a fixed week of daily candles, or an error for named stocks."""

    def __init__(self, fail=(), reject=None):
        self.fail, self.reject, self.calls = set(fail), reject, []

    async def __call__(self, client, token, key, start, end, interval="1minute", retries=3):
        self.calls.append(key)
        if self.reject and key == self.reject:
            raise upstox.UpstoxError("Upstox rejected the access token (401).")
        if key in self.fail:
            raise upstox.UpstoxError("Upstox returned 500 for x")
        rows = [[f"2026-10-0{d}T00:00:00+05:30", 10 + d, 12 + d, 9 + d, 11 + d, 1000, 0] for d in range(1, 6)]
        return {"status": "success", "data": {"candles": rows}}


def test_history_load_saves_skips_fresh_counts_failures_and_stops(monkeypatch):
    db = AsyncMongoMockClient()["h"]
    items = [{"symbol": f"S{i}", "name": f"S{i}", "key": f"K{i}"} for i in range(6)]
    fake = FakeUpstox(fail={"K1"})
    monkeypatch.setattr(upstox, "fetch_range", fake)

    async def go():
        first = await stock_loader.load_history(db, None, "t", items, pause=0, limit=4)
        again = await stock_loader.load_history(db, None, "t", items, pause=0)                  # the four finished stocks are skipped
        seen = []
        stopped = await stock_loader.load_history(db, None, "t", items, pause=0, force=True, stop=lambda: len(fake.calls) >= 8 + 2)
        return first, again, stopped, await db.index_history.count_documents({"interval": "1d"})

    first, again, stopped, stored = run(go())
    assert first["saved"] == 3 and first["failed"] == 1 and first["done"] == 4                    # K1 failed, the rest were saved
    assert again["skipped"] == 3 and again["total"] == 3                                          # S1 failed so it is retried
    assert stopped["stopped"] is True and stopped["done"] < 6 and stored >= 5


def test_a_rejected_token_stops_the_run_with_the_401(monkeypatch):
    db = AsyncMongoMockClient()["t"]
    monkeypatch.setattr(upstox, "fetch_range", FakeUpstox(reject="K2"))
    items = [{"symbol": f"S{i}", "name": f"S{i}", "key": f"K{i}"} for i in range(4)]
    with pytest.raises(upstox.UpstoxError, match="401"):
        run(stock_loader.load_history(db, None, "t", items, pause=0))


def test_owner_button_endpoints_are_owner_only_and_report_plainly(api, monkeypatch):
    spawned = []
    directory._cache.clear()
    monkeypatch.setattr(stock_loader.loader, "spawn", lambda coro: (spawned.append(coro), coro.close()))
    monkeypatch.setattr(stock_loader.loader, "task", None)
    monkeypatch.setattr("lib.db.db", api.db)                                      # the owner endpoints read the application database from lib.db
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    owner, viewer = api.cookie("owner@example.com", "admin"), api.cookie("viewer@example.com")
    assert api.client.get("/api/access/admin/stocks").status_code in {401, 403}
    assert api.client.get("/api/access/admin/stocks", headers=viewer).status_code == 403
    assert api.client.post("/api/access/admin/stocks/start", json={"kind": "list"}, headers=viewer).status_code == 403
    status = api.client.get("/api/access/admin/stocks", headers=owner).json()
    assert status["running"] is False and status["token_set"] is False and status["directory"]["loaded"] is False and status["history_stocks"] == 0
    no_token = api.client.post("/api/access/admin/stocks/start", json={"kind": "history"}, headers=owner)
    assert no_token.status_code == 409 and "UPSTOX_ACCESS_TOKEN" in no_token.json()["detail"] and not spawned           # says what to do; the token is never echoed
    assert api.client.post("/api/access/admin/stocks/start", json={"kind": "bogus"}, headers=owner).status_code == 422
    ok = api.client.post("/api/access/admin/stocks/start", json={"kind": "list"}, headers=owner)
    assert ok.status_code == 200 and ok.json()["phase"] == "list" and len(spawned) == 1


def test_loader_reports_finish_stop_and_token_errors_in_plain_words(api, monkeypatch):
    async def fake_list(db, client):
        return [{"symbol": f"S{i}", "name": "n", "key": f"K{i}"} for i in range(5)]

    monkeypatch.setattr(stock_loader, "load_list", fake_list)
    monkeypatch.setenv("UPSTOX_ACCESS_TOKEN", "secret-token-value")
    loader = stock_loader.Loader()

    async def go(fetch, db):
        monkeypatch.setattr(upstox, "fetch_range", fetch)
        monkeypatch.setattr(stock_loader, "PAUSE_SECONDS", 0)
        loader.start(db, "history", 1.0)
        await loader.task
        return loader.snapshot()

    done = run(go(FakeUpstox(), AsyncMongoMockClient()["one"]))
    assert done["phase"] == "done" and "5 stocks saved" in done["message"] and done["token_set"] is True
    rejected = run(go(FakeUpstox(reject="K0"), AsyncMongoMockClient()["two"]))
    assert rejected["phase"] == "error" and "expires every day" in rejected["message"] and "secret-token-value" not in json.dumps(rejected)
