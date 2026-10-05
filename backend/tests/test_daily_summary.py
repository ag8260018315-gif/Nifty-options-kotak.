import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

import pytest  # noqa: E402

from premium import daily_summary as ds  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401


def rows():
    def r(sym, sector, pct, rvol=1.0, action="NEUTRAL"):
        return {"symbol": sym, "name": sym, "sector": sector, "quote": {"ltp": 100, "change_pct": pct}, "signal": {"action": action, "relative_volume": rvol}}
    return [r("AAA", "Banks", 2.5, 2.4, "BUY"), r("BBB", "Banks", 1.5), r("CCC", "IT", -1.2, 1.0, "SELL"), r("DDD", "IT", -0.8)]


def facts():
    from premium import sectors
    return ds.build_facts(sectors.summarize(rows()), rows(), {"state": "OPEN"})


def test_facts_and_rules_text_only_use_real_numbers():
    f = facts()
    assert f["advancers"] == 2 and f["decliners"] == 2 and f["data"] == "live" and f["top_gainers"][0] == {"symbol": "AAA", "change_pct": 2.5}
    assert f["volume_spikes"] == [{"symbol": "AAA", "relative_volume": 2.4}] and f["signals_bullish"] == 1 and f["signals_bearish"] == 1
    t = ds.rules_text(f)
    assert "Banks" in t and "2.5%" in t and "AAA" in t
    assert "no stock prices" in ds.rules_text(ds.build_facts([], [], {"state": "NO_FEED"})).lower()


async def test_ai_text_is_used_only_when_its_numbers_and_wording_check_out():
    f = facts()
    good = "The data is live. Two stocks are up and two are down, and Banks leads with 2 percent."

    async def ok(system, text, n):
        return "Data is live. 2 stocks rose and 2 fell. AAA gained 2.5%."

    assert (await ds.compose(f, ok))["source"] == "AI"

    async def invented(system, text, n):
        return "AAA gained 9.9% today."

    r = await ds.compose(f, invented)
    assert r["source"] == "RULES" and "9.9" not in r["text"]                      # invented number: refused, rules text instead

    async def advice(system, text, n):
        return "You should buy AAA, it gained 2.5%."

    assert (await ds.compose(f, advice))["source"] == "RULES"                      # advice wording: refused

    calls = []

    async def fixes_itself(system, text, n):
        calls.append(1)
        return "AAA gained 9.9%." if len(calls) == 1 else "AAA gained 2.5%."

    assert (await ds.compose(f, fixes_itself))["source"] == "AI" and len(calls) == 2   # one rewrite is allowed

    async def boom(system, text, n):
        raise RuntimeError("down")

    assert (await ds.compose(f, boom))["source"] == "RULES" and (await ds.compose(f, None))["source"] == "RULES"
    assert good


async def test_cache_is_shared_and_per_state():
    ds._cache.clear()
    n = []

    async def build():
        n.append(1)
        return facts()

    a = await ds.get(build, None, "2026-10-05", "OPEN")
    b = await ds.get(build, None, "2026-10-05", "OPEN")
    c = await ds.get(build, None, "2026-10-05", "CLOSED")
    assert a is b and len(n) == 2 and c is not a


def test_api_is_premium_only_and_labels_its_source(api):
    ds._cache.clear()
    ok = api.client.get("/api/premium/summary", headers=api.cookie("paid@example.com")).json()
    assert ok["source"] in ("AI", "RULES") and "forecast" in ok["note"] and ok["text"]
    assert api.client.get("/api/premium/summary", headers=api.cookie("viewer@example.com")).status_code == 403
