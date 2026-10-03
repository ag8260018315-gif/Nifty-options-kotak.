"""Breakout score and news parsing (pure)."""
import asyncio

import httpx

from premium import news
from premium.breakout import breakout_setup


def analysis(price=100.0, res=100.8, rel=2.5, pressure=65, trend="UPTREND", rsi=62.0, score=40, vwap=99.0, building=False):
    return {"interval": 5, "volume": {"available": True, "relative": rel, "buying_pressure_pct": pressure}, "trend": {"label": trend}, "vwap": vwap,
            "signal": {"action": "BUILDING" if building else "BUY", "score": score, "price": price, "rsi": rsi}, "levels": {"nearest_resistance": res, "nearest_support": 97.0}}


def test_strong_setup_scores_high_and_is_capped():
    s = breakout_setup(analysis())
    assert s["score"] >= 85 and s["score"] <= 100 and s["distance_pct"] == 0.8 and any("Volume" in r for r in s["reasons"])


def test_closer_and_heavier_volume_scores_higher():
    near, far = breakout_setup(analysis(res=100.3)), breakout_setup(analysis(res=101.8))
    low_vol = breakout_setup(analysis(rel=1.0, pressure=40))
    assert near["score"] > far["score"] and breakout_setup(analysis())["score"] > low_vol["score"]


def test_not_listed_when_far_above_or_not_enough_data():
    assert breakout_setup(analysis(res=103.0)) is None  # more than 2% away
    assert breakout_setup(analysis(res=99.0)) is None  # already above the level
    assert breakout_setup(analysis(building=True)) is None
    assert breakout_setup({"signal": {"action": "BUY", "price": 100}, "levels": {}}) is None


def test_score_is_not_presented_as_a_probability():
    s = breakout_setup(analysis())
    assert "probability" not in " ".join(s["reasons"]).lower()


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>TCS wins big deal - Economic Times</title><link>https://news.example.com/a</link><pubDate>Tue, 06 Oct 2026 09:30:00 GMT</pubDate><source url="https://et.com">Economic Times</source></item>
<item><title>Bad link item</title><link>javascript:alert(1)</link></item>
<item><title>   </title><link>https://news.example.com/blank</link></item>
<item><title>TCS results preview</title><link>http://news.example.com/b</link><source>Mint</source></item>
</channel></rss>"""


def test_rss_parser_keeps_only_safe_links_and_strips_source_suffix():
    items = news.parse_rss(RSS)
    assert [i["title"] for i in items] == ["TCS wins big deal", "TCS results preview"]
    assert items[0]["source"] == "Economic Times" and items[0]["published_at"].startswith("2026-10-06T09:30")
    assert all(i["link"].startswith(("http://", "https://")) for i in items)
    assert len(news.parse_rss(RSS, limit=1)) == 1


def test_headlines_fetch_cache_and_failure_are_honest():
    news._cache.clear()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text=RSS) if "TCS" in str(request.url) else httpx.Response(503)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            ok = await news.headlines("TCS", client=client)
            again = await news.headlines("TCS", client=client)
            bad = await news.headlines("INFY", client=client)
            return ok, again, bad

    ok, again, bad = asyncio.run(run())
    assert ok["status"] == "ok" and len(ok["items"]) == 2 and calls["n"] == 2 and again is ok  # second TCS call came from the cache
    assert bad["status"] == "unavailable" and bad["items"] == []  # no invented headlines


def test_malformed_xml_is_unavailable_not_a_crash():
    news._cache.clear()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<rss><oops"))) as client:
            return await news.headlines("ZZZ", client=client)

    assert asyncio.run(run())["status"] == "unavailable"
