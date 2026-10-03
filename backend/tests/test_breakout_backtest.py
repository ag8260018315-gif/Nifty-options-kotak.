"""Upstox import helpers, compact history storage and the breakout back-test (look-ahead safe)."""
import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from jobs import upstox
from premium import backtest as bt
from research import stock_history as sh

IST = ZoneInfo("Asia/Kolkata")
T0 = int(datetime(2026, 6, 3, 9, 15, tzinfo=IST).timestamp())  # Wednesday
PREV = {"high": 105.0, "low": 95.0, "close": 100.0}


def make_day(path, start=T0, volume=lambda i: 1000 + i * 20):
    bars, p = [], path[0]
    for i, c in enumerate(path):
        o, p = p, c
        bars.append({"time": start + i * 60, "open": o, "high": max(o, c) + 0.05, "low": min(o, c) - 0.05, "close": c, "volume": volume(i)})
    return bars


CLIMB = [100 + i * 0.07 for i in range(60)]


# ------------------------------------------------------------------ Upstox helpers
def row(ts, o=10, h=11, l=9, c=10.5, v=500):
    return [ts, o, h, l, c, v, 0]


def test_parse_candles_filters_sorts_and_skips_bad_rows():
    payload = {"status": "success", "data": {"candles": [
        row("2026-06-03T09:17:00+05:30"), row("2026-06-03T09:15:00+05:30"),
        row("2026-06-03T08:00:00+05:30"),           # before the session
        row("2026-06-03T15:30:00+05:30"),           # the session has ended
        row("2026-06-06T10:00:00+05:30"),           # Saturday
        ["2026-06-03T09:20:00+05:30", None, 1, 1, 1, 5],  # missing price
        row("2026-06-03T09:16:00+05:30", v=None),
    ]}}
    bars = upstox.parse_candles(payload)
    assert [b["time"] for b in bars] == sorted(b["time"] for b in bars) and len(bars) == 3
    assert bars[1]["volume"] == 0 and bars[0]["volume"] == 500
    assert upstox.parse_candles({}) == [] and upstox.parse_candles({"data": {"candles": "oops"}}) == []


def test_symbol_keys_and_windows():
    master = [{"trading_symbol": "TCS", "segment": "NSE_EQ", "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE467B01029"},
              {"trading_symbol": "TCS", "segment": "BSE_EQ", "instrument_key": "BSE_EQ|X"},
              {"trading_symbol": "INFY", "segment": "NSE_EQ", "instrument_type": "BE", "instrument_key": "NSE_EQ|Y"},
              {"trading_symbol": "ITC", "segment": "NSE_EQ", "instrument_type": "EQ", "instrument_key": "NSE_EQ|INE154A01025"}]
    assert upstox.symbol_keys(master, ["TCS", "INFY", "ITC", "NONE"]) == {"TCS": "NSE_EQ|INE467B01029", "ITC": "NSE_EQ|INE154A01025"}
    w = upstox.windows(date(2026, 1, 1), date(2026, 3, 1), 28)
    assert w[0][0] == date(2026, 1, 1) and w[-1][1] == date(2026, 3, 1) and all((b - a).days <= 27 for a, b in w)
    assert all(w[i + 1][0] == w[i][1] + (date(2026, 1, 2) - date(2026, 1, 1)) for i in range(len(w) - 1))  # no gaps, no overlap


def test_fetch_range_url_headers_and_errors(monkeypatch):
    seen = {}

    async def no_sleep(_):
        return None

    monkeypatch.setattr(upstox.asyncio, "sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.setdefault("first", (str(request.url), request.headers.get("authorization")))
        seen["calls"] = seen.get("calls", 0) + 1
        if "TOKEN401" in request.headers["authorization"]:
            return httpx.Response(401)
        if "429" in str(request.url) and seen["calls"] < 3:
            return httpx.Response(429)
        return httpx.Response(200, json={"status": "success", "data": {"candles": []}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            ok = await upstox.fetch_range(c, "secret-token", "NSE_EQ|INE848E01016", date(2026, 6, 1), date(2026, 6, 3))
            retried = await upstox.fetch_range(c, "secret-token", "NSE_EQ|429", date(2026, 6, 1), date(2026, 6, 3))
            with pytest.raises(upstox.UpstoxError, match="401"):
                await upstox.fetch_range(c, "TOKEN401", "NSE_EQ|INE848E01016", date(2026, 6, 1), date(2026, 6, 3))
            return ok, retried

    ok, retried = asyncio.run(run())
    assert ok["status"] == "success" and retried["status"] == "success"
    url, auth = seen["first"]
    assert url == "https://api.upstox.com/v2/historical-candle/NSE_EQ%7CINE848E01016/1minute/2026-06-03/2026-06-01" and auth == "Bearer secret-token"
    assert seen["calls"] == 4  # ok; one 429 then a successful retry; then the 401 (not retried)


# ------------------------------------------------------------------ compact storage
async def test_history_roundtrip_is_idempotent():
    db = AsyncMongoMockClient()["r"]
    bars = make_day(CLIMB) + make_day(CLIMB, start=T0 + 86400)
    assert await sh.save_days(db, "TCS", bars, "upstox") == 2
    assert await sh.save_days(db, "TCS", bars, "upstox") == 2  # re-import replaces, never duplicates
    assert await db.stock_days.count_documents({}) == 2 and await sh.stored_days(db, "TCS") == {"2026-06-03", "2026-06-04"}
    loaded = await sh.load_symbol(db, "TCS")
    assert [d for d, _ in loaded] == ["2026-06-03", "2026-06-04"] and loaded[0][1] == sorted(make_day(CLIMB), key=lambda b: b["time"])
    assert await sh.symbols_with_data(db) == ["TCS"]


# ------------------------------------------------------------------ back-test
def test_outcome_rules_including_stop_first_on_ambiguous_candle():
    rule = bt.Rule(target_pct=1.0, stop_pct=0.5, horizon_minutes=10)
    up = [{"open": 100, "high": 101.5, "low": 99.9, "close": 101.2}]
    assert bt.outcome(100.0, 100.8, up, rule)[0] == "SUCCESS"
    assert bt.outcome(100.0, 102.0, up, rule)[0] == "TIMEOUT"          # never closed above the resistance
    down = [{"open": 100, "high": 100.1, "low": 99.4, "close": 99.5}]
    assert bt.outcome(100.0, 100.8, down, rule)[0] == "STOP"
    both = [{"open": 100, "high": 101.5, "low": 99.4, "close": 101.3}]
    assert bt.outcome(100.0, 100.8, both, rule)[0] == "STOP"           # conservative when one candle spans both


def test_signal_is_found_and_scored_without_looking_ahead():
    up = make_day(CLIMB + [CLIMB[-1] + j * 0.12 for j in range(1, 41)])
    hit = bt.first_setup(up, PREV, bt.Rule())
    assert hit and hit["result"] == "SUCCESS" and 0 < hit["score"] <= 100
    idx = (hit["time"] - T0) // 60 - 1                                   # the bar that had just closed at the signal
    crash = up[: idx + 1] + make_day([up[idx]["close"] - j * 0.2 for j in range(1, 60)], start=up[idx]["time"] + 60)
    again = bt.first_setup(crash, PREV, bt.Rule())
    assert {k: again[k] for k in ("time", "entry", "score", "resistance", "distance_pct")} == {k: hit[k] for k in ("time", "entry", "score", "resistance", "distance_pct")}
    assert again["result"] == "STOP"  # only the OUTCOME can depend on later candles


def test_no_signal_when_too_few_candles_or_no_resistance_nearby():
    assert bt.first_setup(make_day(CLIMB[:20]), PREV, bt.Rule()) is None
    flat = make_day([100.0 + (i % 2) * 0.01 for i in range(80)])
    assert bt.first_setup(flat, {"high": 130.0, "low": 70.0, "close": 100.0}, bt.Rule()) is None  # resistance more than 2% away


def test_summary_validation_threshold_and_bands():
    recs = [{"symbol": "A", "day": f"2026-06-{(i % 28) + 1:02d}", "score": 40 + (i % 60), "result": "SUCCESS" if i % 3 else "STOP"} for i in range(250)]
    s = bt.summarize(recs, bt.Rule(), sessions_tested=60, symbols_tested=30)
    assert s["validated"] and s["setups"] == 250 and 60 < s["hit_rate_pct"] < 70 and s["ci95_low_pct"] < s["hit_rate_pct"] < s["ci95_high_pct"]
    assert sum(b["setups"] for b in s["by_score_band"]) == 250 and "not a promise" in s["note"].lower()
    few = bt.summarize(recs[:20], bt.Rule(), sessions_tested=10, symbols_tested=3)
    assert few["validated"] is False and "Not enough history" in few["note"]
    empty = bt.summarize([], bt.Rule(), 0, 0)
    assert empty["hit_rate_pct"] is None and empty["validated"] is False


async def test_run_and_store_then_router_reports_it(monkeypatch):
    from jobs import breakout_validation as bv

    db = AsyncMongoMockClient()["r"]
    assert await bv.run_and_store(db, bt.Rule()) is None  # nothing stored yet
    await sh.save_days(db, "TCS", make_day(CLIMB + [CLIMB[-1] + j * 0.12 for j in range(1, 41)]), "upstox")
    result = await bv.run_and_store(db, bt.Rule())
    assert result["setups"] == 0 or result["hit_rate_pct"] is not None
    stored = await bv.latest(db)
    assert stored["rule"]["target_pct"] == 1.0 and "definition" in stored
