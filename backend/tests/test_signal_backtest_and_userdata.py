"""Signal back-test (win rate, drawdown), per-user watchlists/layouts, compare, and the stock-page performance block."""
import os

import pytest
from fastapi import HTTPException
from mongomock_motor import AsyncMongoMockClient

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from jobs import signal_validation as sv  # noqa: E402
from premium import signal_backtest as sb  # noqa: E402
from premium import userdata  # noqa: E402
from research import stock_history as sh  # noqa: E402
from tests.test_breakout_backtest import T0, make_day  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401


# ------------------------------------------------------------------ simulation and summary
def fut(*rows):
    return [{"open": o, "high": h, "low": l, "close": c} for o, h, l, c in rows]


def test_simulate_long_and_short_with_stop_first_on_ambiguous_candles():
    assert sb.simulate("LONG", 100, 98, 104, 2.0, fut((100, 104.5, 99.5, 104)))[:2] == ("TARGET", 2.0)
    assert sb.simulate("LONG", 100, 98, 104, 2.0, fut((100, 101, 97.5, 98)))[:2] == ("STOP", -1.0)
    assert sb.simulate("LONG", 100, 98, 104, 2.0, fut((100, 105, 97.5, 101)))[:2] == ("STOP", -1.0)     # one candle spans both: stop first
    assert sb.simulate("SHORT", 100, 102, 96, 2.0, fut((100, 100.5, 95.5, 96)))[:2] == ("TARGET", 2.0)
    assert sb.simulate("SHORT", 100, 102, 96, 2.0, fut((100, 102.5, 99.5, 101)))[:2] == ("STOP", -1.0)
    result, r, used = sb.simulate("LONG", 100, 98, 104, 2.0, fut((100, 101, 99.5, 100.5), (100.5, 101, 100, 101)))
    assert result == "TIMEOUT" and r == 0.5 and used == 2                                              # marked to market: +1 of a 2 risk


def trade(i, net, direction="LONG", result=None):
    return {"day": f"2026-06-{1 + i // 5:02d}", "time": i, "direction": direction, "score": 50, "result": result or ("TARGET" if net > 0 else "STOP"), "gross_r": net, "net_r": net, "bars": 5}


def test_summary_win_rate_expectancy_drawdown_and_streaks():
    pattern = [1.5, -1, -1, -1, 1.5, 1.5, -1, 1.5]
    trades = [trade(i, r) for i, r in enumerate(pattern * 5)]
    s = sb.summarize_trades(trades)
    assert s["trades"] == 40 and s["wins"] == 20 and s["win_rate_pct"] == 50.0 and s["reliable"] is True
    assert s["avg_r"] == round(sum(pattern * 5) / 40, 3) and s["total_r"] == 10.0 and s["max_drawdown_r"] == 3.0 and s["longest_losing_streak"] == 3
    assert s["profit_factor"] == round(30 / 20, 2) and s["win_rate_ci95_pct"][0] < 50.0 < s["win_rate_ci95_pct"][1]
    assert "past" in s["note"].lower()


def test_few_trades_are_flagged_unreliable_and_empty_is_honest():
    few = sb.summarize_trades([trade(i, 1.0) for i in range(5)])
    assert few["reliable"] is False and "too few" in few["note"].lower()
    assert sb.summarize_trades([]) == {"trades": 0, "reliable": False, "note": "No trades in the tested history."}


def test_run_symbol_uses_only_the_past_at_each_decision_and_never_overlaps_trades():
    up = [100 + i * 0.12 for i in range(300)]
    day = make_day(up, volume=lambda i: 1000 + 5 * i)
    changed = day[:150] + make_day([up[149] - j * 0.2 for j in range(1, 151)], start=day[149]["time"] + 60)
    a = sb.run_symbol([("2026-06-03", day)], sb.Rule())
    b = sb.run_symbol([("2026-06-03", changed)], sb.Rule())
    assert a and b
    early_a = [t for t in a if t["time"] <= day[149]["time"]]
    early_b = [t for t in b if t["time"] <= day[149]["time"]]
    assert [(t["time"], t["direction"], t["score"]) for t in early_a] == [(t["time"], t["direction"], t["score"]) for t in early_b]  # same decisions
    times = sorted(t["time"] for t in a)
    assert all(later - earlier >= 60 for earlier, later in zip(times, times[1:]))


def test_costs_reduce_the_result():
    day = make_day([100 + i * 0.12 for i in range(300)], volume=lambda i: 1000 + 5 * i)
    free = sb.run_symbol([("d", day)], sb.Rule(cost_pct=0.0))
    costly = sb.run_symbol([("d", day)], sb.Rule(cost_pct=0.2))
    assert free and len(free) == len(costly) and sum(t["net_r"] for t in costly) < sum(t["net_r"] for t in free)


async def test_job_stores_per_stock_and_overall_and_reports_untested_honestly():
    db = AsyncMongoMockClient()["r"]
    assert await sv.run_and_store(db, sb.Rule()) is None
    await sh.save_days(db, "TCS", make_day([100 + i * 0.12 for i in range(300)], volume=lambda i: 1000 + 5 * i), "test")
    overall = await sv.run_and_store(db, sb.Rule())
    assert overall["stocks_tested"] == 1 and overall["trades"] >= 0
    tcs = await sv.performance_for(db, "TCS")
    assert tcs["tested"] is True and tcs["overall"]["stocks_tested"] == 1 and "definition" in tcs
    other = await sv.performance_for(db, "INFY")
    assert other["tested"] is False and "no tested history" in other["note"].lower()


# ------------------------------------------------------------------ user data
async def test_watchlists_validate_dedupe_and_cap():
    db, universe = AsyncMongoMockClient()["u"], {"TCS", "INFY", "M&M"}
    lists = await userdata.put_list(db, "a@x.com", "Banks & IT", ["tcs", "TCS", "m&m"], universe)
    assert lists == {"Banks & IT": ["TCS", "M&M"]}
    for bad in (["NOPE"],):
        with pytest.raises(HTTPException):
            await userdata.put_list(db, "a@x.com", "x", bad, universe)
    for name in ("", "bad/name", "x" * 31):
        with pytest.raises(HTTPException):
            await userdata.put_list(db, "a@x.com", name, ["TCS"], universe)
    for i in range(9):
        await userdata.put_list(db, "a@x.com", f"L{i}", ["TCS"], universe)
    with pytest.raises(HTTPException):
        await userdata.put_list(db, "a@x.com", "one-too-many", ["TCS"], universe)
    assert "Banks & IT" not in await userdata.delete_list(db, "a@x.com", "Banks & IT")
    assert await userdata.get_lists(db, "b@x.com") == {}                                              # other users see nothing


async def test_layouts_keep_only_known_typed_fields():
    db = AsyncMongoMockClient()["u"]
    layouts = await userdata.put_layout(db, "a@x.com", "Swing", {"ema_fast": 5, "ema_slow": 50, "interval": 1440, "pane": "macd", "bb": True, "evil": "<script>", "ema": 0})
    assert layouts["Swing"] == {"ema_fast": 5, "ema_slow": 50, "interval": 1440, "pane": "macd", "ema": False, "bb": True, "vwap": True, "levels": True, "patterns": True, "setup": True}
    for bad in ({"ema_fast": 50, "ema_slow": 20}, {"interval": 7}, {"pane": "x"}, {"ema_fast": "abc"}):
        with pytest.raises(HTTPException):
            await userdata.put_layout(db, "a@x.com", "bad", bad)


# ------------------------------------------------------------------ API
def test_api_watchlists_layouts_are_per_user_and_premium_only(api):
    owner, other, free = api.cookie("paid@example.com"), api.cookie("owner@example.com"), api.cookie("viewer@example.com")
    r = api.client.put("/api/premium/me/watchlists/Core", json={"symbols": ["TCS", "INFY"]}, headers=owner)
    assert r.status_code == 200 and r.json()["watchlists"] == {"Core": ["TCS", "INFY"]}
    assert api.client.get("/api/premium/me/watchlists", headers=other).json()["watchlists"] == {}       # another premium user cannot see it
    assert api.client.put("/api/premium/me/watchlists/Core", json={"symbols": ["NOPE"]}, headers=owner).status_code == 422
    assert api.client.get("/api/premium/me/watchlists", headers=free).status_code == 403
    assert api.client.put("/api/premium/me/layouts/L1", json={"ema_fast": 9, "ema_slow": 20, "interval": 5}, headers=owner).status_code == 200
    assert api.client.get("/api/premium/me/layouts", headers=owner).json()["layouts"]["L1"]["interval"] == 5
    assert api.client.get("/api/premium/me/layouts", headers=other).json()["layouts"] == {}
    assert api.client.delete("/api/premium/me/layouts/L1", headers=owner).json()["layouts"] == {}
    assert api.client.put("/api/premium/me/layouts/L1", json={"interval": 3}, headers=owner).status_code == 422
    assert api.client.get("/api/premium/me/layouts", headers=free).status_code == 403


def test_api_compare_validates_and_never_invents_data(api):
    owner = api.cookie("paid@example.com")
    ok = api.client.get("/api/premium/stocks/compare?symbols=TCS,INFY&interval=1440", headers=owner)
    assert ok.status_code == 200
    rows = ok.json()["stocks"]
    assert [r["symbol"] for r in rows] == ["TCS", "INFY"] and all(r["series"] == [] and r["bias"] == "Unavailable" for r in rows)   # no history/feed in CI: empty, not invented
    for q in ("symbols=TCS", "symbols=TCS,INFY,HDFCBANK,SBIN,ITC", "symbols=TCS,NOPE", "symbols=TCS,INFY&interval=7", "symbols=TCS,TCS"):
        assert api.client.get(f"/api/premium/stocks/compare?{q}", headers=owner).status_code == 422, q
    assert api.client.get("/api/premium/stocks/compare?symbols=TCS,INFY", headers=api.cookie("viewer@example.com")).status_code == 403


def test_api_stock_detail_includes_tested_performance_or_says_untested(api):
    j = api.client.get("/api/premium/stock/TCS", headers=api.cookie("paid@example.com")).json()
    assert j["performance"]["tested"] is False and "no tested history" in j["performance"]["note"].lower()
