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
    assert bt.pure_outcome(100.0, up, rule) == "SUCCESS" and bt.pure_outcome(100.0, both, rule) == "STOP"
    assert bt.pure_outcome(100.0, [{"open": 100, "high": 100.3, "low": 99.9, "close": 100.1}], rule) == "TIMEOUT"


def test_moments_always_have_a_full_look_forward_window():
    rule = bt.Rule(horizon_minutes=30, eval_step_minutes=15)
    assert all(i + rule.horizon_minutes < 100 for i in bt._moments(100, rule))
    assert list(bt._moments(40, rule)) == []  # too short to evaluate


def test_scores_use_only_past_candles_later_candles_change_only_the_outcome():
    rule = bt.Rule()
    up = make_day(CLIMB + [CLIMB[-1] + j * 0.12 for j in range(1, 41)])
    crash_from = 50
    crash = up[: crash_from + 1] + make_day([up[crash_from]["close"] - j * 0.2 for j in range(1, len(up) - crash_from)], start=up[crash_from]["time"] + 60)
    a, b = bt.observe_session("X", "2026-06-03", up, PREV, rule), bt.observe_session("X", "2026-06-03", crash, PREV, rule)
    assert len(a) == len(b) and len(a) > 0
    for x, y in zip(a, b):
        moment_index = (x[1] - T0) // 60 - 1
        if moment_index <= crash_from:
            assert x[3] == y[3] and x[1] == y[1]                         # same score at the same moment
    assert any(x[4] != y[4] for x, y in zip(a, b))                       # but what happened afterwards differs


def obs(days=60, moments=3, n_stocks=20, success=lambda d, m, i: False, score=lambda d, m, i: 90 - i):
    return [(f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}", 1000 + m, f"S{i}", score(d, m, i), "SUCCESS" if success(d, m, i) else "STOP", "SUCCESS" if success(d, m, i) else "STOP")
            for d in range(days) for m in range(moments) for i in range(n_stocks)]


def test_cross_section_better_worse_same_and_unknown():
    rule = bt.Rule()
    better = bt.summarize(bt.cross_section(obs(success=lambda d, m, i: i < 5), rule), rule, 20)
    assert better["comparison"]["verdict"] == "BETTER" and better["comparison"]["listed_rate_pct"] == 50.0 and better["comparison"]["random_rate_pct"] == 25.0
    worse = bt.summarize(bt.cross_section(obs(success=lambda d, m, i: i >= 15), rule), rule, 20)
    assert worse["comparison"]["verdict"] == "WORSE"
    same = bt.summarize(bt.cross_section(obs(success=lambda d, m, i: (d + m) % 2 == 0), rule), rule, 20)  # every stock moves together
    assert same["comparison"]["verdict"] == "SAME" and same["comparison"]["difference_points"] == 0
    assert bt.summarize(bt.cross_section([], rule), rule, 0)["comparison"]["verdict"] == "UNKNOWN"


def test_matching_by_moment_removes_the_time_of_day_effect():
    """Early moments are easy for everyone; a list that is merely evaluated early must not look skilful."""
    rule = bt.Rule()
    early_is_easy = obs(days=60, moments=4, success=lambda d, m, i: m == 0)  # every stock succeeds at moment 0, none later
    s = bt.summarize(bt.cross_section(early_is_easy, rule), rule, 20)
    assert s["comparison"]["verdict"] == "SAME" and s["comparison"]["difference_points"] == 0


def test_groups_without_enough_stocks_are_skipped():
    rule = bt.Rule()
    cs = bt.cross_section(obs(n_stocks=12, success=lambda d, m, i: i < 5), rule)  # 12 < 2 x 10
    assert cs["pooled"]["moments"] == 0


def test_validation_needs_enough_days_and_stock_moments():
    rule = bt.Rule()
    big = bt.summarize(bt.cross_section(obs(days=60, moments=4, success=lambda d, m, i: i < 5), rule), rule, 20)
    assert big["validated"] is True and "not a promise" in big["note"].lower()
    small = bt.summarize(bt.cross_section(obs(days=5, moments=2, success=lambda d, m, i: i < 5), rule), rule, 20)
    assert small["validated"] is False and "Not enough history" in small["note"] and sum(b["setups"] for b in small["by_score_band"]) > 0


async def test_run_and_store_end_to_end_with_candles():
    from jobs import breakout_validation as bv

    db = AsyncMongoMockClient()["r"]
    assert await bv.run_and_store(db, bt.Rule()) is None  # nothing stored yet
    for k in range(22):  # enough stocks that a top-10 exists at each moment
        slope = 0.07 if k % 2 else 0.0
        for d in range(3):
            path = [100 + i * slope for i in range(100)]
            await sh.save_days(db, f"S{k}", make_day(path, start=T0 + d * 86400, volume=lambda i: 1000 + 10 * i), "test")
    result = await bv.run_and_store(db, bt.Rule(eval_step_minutes=15))
    assert result["symbols_tested"] == 22 and result["sessions_tested"] == 3 and result["comparison"]["verdict"] in {"BETTER", "SAME", "WORSE", "UNKNOWN"}
    assert (await bv.latest(db))["method"] == "top_10_by_score_at_each_moment"
