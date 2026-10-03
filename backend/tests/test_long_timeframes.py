"""1H / 4H / 1D / 1W candles for the premium charts: bucket maths, merging with live candles, storage and the API."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from mongomock_motor import AsyncMongoMockClient

from jobs import upstox
from premium import history, timeframes as tf
from premium.analysis import analyse
from tests.test_premium import api  # noqa: F401  (shared API fixture with the access database stubbed)

IST = ZoneInfo("Asia/Kolkata")


def ist(y, m, d, hh=0, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=IST).timestamp())


def bar(t, o=100.0, h=101.0, l=99.0, c=100.5, v=10):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_session_buckets_are_anchored_to_the_open():
    t = lambda hh, mm: ist(2026, 6, 3, hh, mm)  # noqa: E731
    assert tf.session_bucket(t(9, 15), 60) == t(9, 15) and tf.session_bucket(t(10, 14), 60) == t(9, 15)
    assert tf.session_bucket(t(10, 15), 60) == t(10, 15) and tf.session_bucket(t(15, 29), 60) == t(15, 15)
    assert tf.session_bucket(t(9, 15), 240) == t(9, 15) and tf.session_bucket(t(13, 14), 240) == t(9, 15)
    assert tf.session_bucket(t(13, 15), 240) == t(13, 15) and tf.session_bucket(t(15, 29), 240) == t(13, 15)


def test_day_and_week_starts_use_ist_and_monday():
    assert tf.day_start(ist(2026, 6, 3, 15, 29)) == ist(2026, 6, 3)
    assert tf.week_start(ist(2026, 6, 3, 11, 0)) == ist(2026, 6, 1)      # Wednesday -> Monday
    assert tf.week_start(ist(2026, 6, 1, 0, 0)) == ist(2026, 6, 1)       # Monday stays
    assert tf.week_start(ist(2026, 6, 7, 12, 0)) == ist(2026, 6, 1)      # Sunday -> the Monday before


def test_regroup_combines_ohlc_and_sums_volume():
    bars = [bar(ist(2026, 6, 3, 9, 15), 100, 102, 99, 101, 5), bar(ist(2026, 6, 3, 9, 45), 101, 105, 100, 104, 7), bar(ist(2026, 6, 3, 10, 15), 104, 106, 103, 105, 3)]
    out = tf.regroup(bars, lambda t: tf.session_bucket(t, 60))
    assert [b["time"] for b in out] == [ist(2026, 6, 3, 9, 15), ist(2026, 6, 3, 10, 15)]
    first = out[0]
    assert (first["open"], first["high"], first["low"], first["close"], first["volume"]) == (100, 105, 99, 104, 12)


def test_hour_and_four_hour_frames_merge_history_with_todays_live_candles():
    hist = [bar(ist(2026, 6, 2, 9, 15) + 1800 * k, 100 + k) for k in range(13)]          # yesterday, 30-minute bars
    stale_today = [bar(ist(2026, 6, 3, 9, 15), 1, 1, 1, 1)]                               # history that wrongly includes today: must be replaced
    today = [bar(ist(2026, 6, 3, 9, 15) + 60 * k, 200 + k, 201 + k, 199 + k, 200.5 + k, 0) for k in range(75)]
    four = tf.build_long_bars(240, hist + stale_today, [], today)
    assert [b["time"] for b in four if b["time"] >= ist(2026, 6, 3)] == [ist(2026, 6, 3, 9, 15)]  # 75 minutes of today: one 4H candle
    today_bar = next(b for b in four if b["time"] == ist(2026, 6, 3, 9, 15))
    assert today_bar["open"] == 200 and today_bar["high"] == 275 and today_bar["close"] == 274.5   # built from today's live candles, not the stale history row
    hour = tf.build_long_bars(60, hist, [], today)
    assert len([b for b in hour if tf.day_start(b["time"]) == ist(2026, 6, 3)]) == 2          # 75 minutes: 09:15 and 10:15 buckets


def test_daily_and_weekly_frames_include_a_forming_candle_for_today():
    days = [bar(ist(2026, 6, d), 100 + d, 110 + d, 90 + d, 105 + d, 0) for d in (1, 2, 3, 4, 5)]
    today = [bar(ist(2026, 6, 8, 9, 15) + 60 * k, 300, 301 + k, 299, 300 + k, 0) for k in range(10)]
    daily = tf.build_long_bars(tf.DAY, [], days, today)
    assert len(daily) == 6 and daily[-1]["time"] == ist(2026, 6, 8) and daily[-1]["high"] == 310
    weekly = tf.build_long_bars(tf.WEEK, [], days, today)
    assert [b["time"] for b in weekly] == [ist(2026, 6, 1), ist(2026, 6, 8)]
    assert weekly[0]["open"] == 101 and weekly[0]["close"] == 110 and weekly[0]["high"] == 115 and weekly[0]["low"] == 91
    with pytest.raises(ValueError):
        tf.build_long_bars(7, [], [], [])


def test_daily_frame_can_be_derived_from_fine_history_when_no_daily_is_stored():
    fine = [bar(ist(2026, 6, 2, 9, 15) + 60 * k, 100, 100 + k, 99, 100 + k, 5) for k in range(10)] + [bar(ist(2026, 6, 3, 9, 15) + 60 * k, 200, 201, 199, 200, 5) for k in range(10)]
    daily = tf.build_long_bars(tf.DAY, fine, [], [])
    assert len(daily) == 2 and daily[0]["volume"] == 50 and daily[1]["open"] == 200


async def test_index_history_merge_save_new_wins_and_caps():
    db = AsyncMongoMockClient()["t"]
    assert await history.load(db, "NIFTY", "1d") == []
    await history.merge_save(db, "NIFTY", "1d", [bar(ist(2026, 6, 1), c=1), bar(ist(2026, 6, 2), c=2)])
    stored = await history.merge_save(db, "NIFTY", "1d", [bar(ist(2026, 6, 2), c=99), bar(ist(2026, 6, 3), c=3)])
    rows = await history.load(db, "NIFTY", "1d")
    assert stored == 3 and [r["close"] for r in rows] == [1, 99, 3] and await db.index_history.count_documents({}) == 1
    history.CAPS["1d"] = 2
    try:
        assert await history.merge_save(db, "NIFTY", "1d", [bar(ist(2026, 6, 4), c=4)]) == 2
        assert [r["close"] for r in await history.load(db, "NIFTY", "1d")] == [3, 4]
    finally:
        history.CAPS["1d"] = 6000


def test_upstox_daily_candles_keep_their_midnight_timestamps():
    payload = {"data": {"candles": [["2026-06-02T00:00:00+05:30", 100, 110, 90, 105, 0, 0], ["2026-06-01T00:00:00+05:30", 99, 109, 89, 104, 0, 0]]}}
    assert upstox.parse_candles(payload) == []                               # intraday rule: midnight is outside the session
    daily = upstox.parse_candles(payload, session_only=False)
    assert [b["time"] for b in daily] == [ist(2026, 6, 1), ist(2026, 6, 2)] and daily[0]["close"] == 104


def test_tail_keeps_recent_candles_but_indicators_use_the_whole_history():
    bars = [bar(ist(2026, 1, 1) + 86400 * i, 100 + i * 0.2, 101 + i * 0.2, 99 + i * 0.2, 100 + i * 0.2, 0) for i in range(120)]
    now = bars[-1]["time"] + 86400 * 2
    full = analyse(bars, tf.DAY, None, now, False)
    cut = analyse(bars, tf.DAY, None, now, False, tail=50)
    assert len(cut["candles"]) == 50 and all(len(v) == 50 for v in cut["series"].values())
    assert cut["series"]["ema_slow"] == full["series"]["ema_slow"][-50:] and cut["signal"] == full["signal"]
    short = analyse(bars[:20], tf.DAY, None, now, False)
    assert short["signal"]["action"] == "BUILDING" and "history import" in short["signal"]["reasons"][0] and "daily" in short["signal"]["reasons"][0]


# ------------------------------------------------------------------ API
def _daily(n):
    start = datetime(2026, 1, 5, tzinfo=IST)
    out, d = [], 0
    while len(out) < n:
        day = start + timedelta(days=d)
        d += 1
        if day.weekday() < 5:
            k = len(out)
            out.append(bar(int(day.timestamp()), 22000 + k * 5, 22010 + k * 5, 21990 + k * 5, 22005 + k * 5, 0))
    return out


def test_api_serves_every_frame_for_premium_and_blocks_free_users(api):
    import routers.premium_market as rpm

    owner, free = api.cookie("paid@example.com"), api.cookie("viewer@example.com")
    thirty = [bar(ist(2026, 5, 4 + i // 13, 9, 15) + 1800 * (i % 13), 22000 + i, 22005 + i, 21995 + i, 22002 + i, 0) for i in range(13 * 25)]
    asyncio.run(history.merge_save(rpm.db, "NIFTY", "1d", _daily(300)))
    asyncio.run(history.merge_save(rpm.db, "NIFTY", "30m", thirty))
    for minutes in (60, 240, 1440, 10080):
        j = api.client.get(f"/api/premium/index/NIFTY?interval={minutes}", headers=owner).json()
        a = j["analysis"]
        assert a["interval"] == minutes and a["history_available"] is True and 0 < len(a["candles"]) <= 300, minutes
        assert len(a["series"]["ema_fast"]) == len(a["candles"])
    daily = api.client.get("/api/premium/index/NIFTY?interval=1440", headers=owner).json()["analysis"]
    assert daily["signal"]["action"] in {"BUY", "SELL", "NEUTRAL"} and daily["trend"]["label"] == "UPTREND"
    weekly = api.client.get("/api/premium/index/NIFTY?interval=10080", headers=owner).json()["analysis"]
    assert weekly["bars_total"] < daily["bars_total"]
    assert api.client.get("/api/premium/index/NIFTY?interval=7", headers=owner).status_code == 422
    for minutes in (60, 1440):
        assert api.client.get(f"/api/premium/index/NIFTY?interval={minutes}", headers=free).status_code == 403


def test_api_says_when_no_history_is_stored_instead_of_inventing_it(api):
    owner = api.cookie("paid@example.com")
    for symbol in ("BANKNIFTY", "SENSEX"):
        a = api.client.get(f"/api/premium/index/{symbol}?interval=1440", headers=owner).json()["analysis"]
        assert a["history_available"] is False and a["candles"] == [] and a["signal"]["action"] == "BUILDING"
        assert "history import" in a["signal"]["reasons"][0]


def _recent_weekdays(n):
    from datetime import date

    day, out = date.today() - timedelta(days=1), []
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return sorted(out)


def test_days_after_the_import_are_filled_from_recorded_candles(api):
    """History ends 3 sessions ago; the app recorded the sessions since, so the daily and weekly charts must include them."""
    import routers.premium_market as rpm
    from lib.candles import candle_store

    days = _recent_weekdays(3)
    hist_day = datetime(days[0].year, days[0].month, days[0].day, tzinfo=IST)
    older = [bar(int((hist_day - timedelta(days=k)).timestamp()), 22000 - k, 22010 - k, 21990 - k, 22005 - k, 0) for k in range(1, 80)]
    asyncio.run(history.merge_save(rpm.db, "NIFTY", "1d", older + [bar(int(hist_day.timestamp()), 22100, 22110, 22090, 22105, 0)]))
    # the app recorded two later sessions in index_candles (1-minute candles)
    col = candle_store._collection_override
    for n, d in enumerate(days[1:]):
        t0 = int(datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST).timestamp())
        for k in range(10):
            asyncio.run(col.insert_one({"symbol": "NIFTY", "trading_day": d.isoformat(), "time": t0 + 60 * k, "open": 23000 + n, "high": 23010 + n, "low": 22990 + n, "close": 23005 + n, "ticks": 3}))
    rpm._history_cache.clear()
    a = api.client.get("/api/premium/index/NIFTY?interval=1440", headers=api.cookie("paid@example.com")).json()["analysis"]
    times = {c["time"] for c in a["candles"]}
    for d in days[1:]:
        assert int(datetime(d.year, d.month, d.day, tzinfo=IST).timestamp()) in times, d
    assert a["candles"][-1]["close"] in (23005, 23006)  # the recorded sessions are the latest candles


def test_thirty_minute_and_monthly_frames():
    fine = [bar(ist(2026, 6, 2, 9, 15) + 60 * k, 100 + k, 101 + k, 99 + k, 100.5 + k, 3) for k in range(60)]
    thirty = tf.build_long_bars(30, fine, [], [])
    assert [b["time"] for b in thirty] == [ist(2026, 6, 2, 9, 15), ist(2026, 6, 2, 9, 45)] and thirty[0]["volume"] == 90
    days = [bar(ist(2026, 5, d), 100, 110 + d, 90, 100 + d, 0) for d in (5, 6, 7)] + [bar(ist(2026, 6, d), 200, 210, 190, 205, 0) for d in (1, 2)]
    months = tf.build_long_bars(tf.MONTH, [], days, [])
    assert [b["time"] for b in months] == [ist(2026, 5, 1), ist(2026, 6, 1)]
    assert months[0]["end"] == ist(2026, 6, 1) and months[1]["end"] == ist(2026, 7, 1)
    assert tf.next_month_start(ist(2026, 12, 15)) == ist(2027, 1, 1) and months[0]["high"] == 117
    # a monthly candle is not 'closed' until its month is over, even though 30 days have passed
    bars = [dict(b, **({"end": tf.next_month_start(b["time"])})) for b in [bar(ist(2026, 10, 1))]]
    assert analyse(bars, tf.MONTH, None, ist(2026, 10, 31, 10), False)["bars_closed"] == 0
    assert analyse(bars, tf.MONTH, None, ist(2026, 11, 1, 1), False)["bars_closed"] == 1


def test_custom_ema_periods_are_used_and_reported():
    bars = [bar(ist(2026, 1, 1) + 86400 * i, 100 + i * 0.3, 101 + i * 0.3, 99 + i * 0.3, 100 + i * 0.3, 0) for i in range(80)]
    now = bars[-1]["time"] + 86400 * 2
    default = analyse(bars, tf.DAY, None, now, False)
    custom = analyse(bars, tf.DAY, None, now, False, ema_fast=5, ema_slow=50)
    assert default["ema_periods"] == [9, 20] and custom["ema_periods"] == [5, 50]
    assert default["series"]["ema_slow"] != custom["series"]["ema_slow"] and "EMA9" in default["trend"]["basis"][0] and "EMA50" in custom["trend"]["basis"][0]
