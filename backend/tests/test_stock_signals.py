"""Candlestick patterns, trade setup and the stock signal engine (pure)."""
import os
from datetime import datetime, timezone

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from premium import patterns as pt
from premium import stockinfo
from premium.analysis import analyse
from premium.setup import build_setup
from premium.signal_engine import data_status, stock_signal
from premium.universe import DEFAULT_STOCKS, static_universe

T0 = 1_780_000_000 // 60 * 60


def b(i, o, h, l, c, v=1000):
    return {"time": T0 + i * 60, "open": o, "high": h, "low": l, "close": c, "volume": v}


# ------------------------------------------------------------------ names and sectors
def test_all_129_stocks_have_a_name_and_sector():
    assert len(DEFAULT_STOCKS) == 129 and set(stockinfo.INFO) == set(DEFAULT_STOCKS)
    names, kinds = static_universe()
    assert names["TCS"] == "Tata Consultancy Services" and kinds["TCS"] == "stock" and stockinfo.sector_of("HDFCBANK") == "Banks"
    assert stockinfo.sector_of("UNKNOWN") == "Other" and "Banks" in stockinfo.sectors()


# ------------------------------------------------------------------ patterns
def test_core_patterns_are_detected_on_the_completing_candle():
    down = [b(0, 110, 111, 108, 109), b(1, 109, 110, 106, 107), b(2, 107, 108, 104, 105)]
    hammer = down + [b(3, 105, 105.22, 101, 105.2)]
    assert "Hammer" in [p["name"] for p in pt.detect_at(hammer, 3)]
    engulf = [b(0, 105, 106, 103, 103.5), b(1, 103, 107, 102.5, 106.5)]
    names = [p["name"] for p in pt.detect_at(engulf, 1)]
    assert "Bullish engulfing" in names and pt.detect_at(engulf, 1)[0]["direction"] == "bullish"
    bear_engulf = [b(0, 103, 106, 102.5, 105.5), b(1, 106, 106.5, 102, 102.5)]
    assert "Bearish engulfing" in [p["name"] for p in pt.detect_at(bear_engulf, 1)]
    star = [b(0, 100, 101, 95, 96), b(1, 95.5, 96.5, 94.5, 95.6), b(2, 96, 101, 95.5, 100)]
    assert "Morning star" in [p["name"] for p in pt.detect_at(star, 2)]
    up = [b(0, 100, 101.2, 99.8, 101), b(1, 101.2, 102.4, 101, 102.2), b(2, 102.4, 103.6, 102.2, 103.4)]
    assert "Three white soldiers" in [p["name"] for p in pt.detect_at(up, 2)]
    assert "Doji" in [p["name"] for p in pt.detect_at([b(0, 100, 102, 98, 100.1)], 0)]
    assert pt.detect_at([b(0, 100, 100, 100, 100)], 0) == []                      # zero range: nothing


def test_patterns_use_only_candles_up_to_the_one_being_checked():
    bars = [b(0, 105, 106, 103, 103.5), b(1, 103, 107, 102.5, 106.5), b(2, 106.5, 120, 80, 81)]
    assert [p["name"] for p in pt.detect_at(bars, 1)] == [p["name"] for p in pt.detect_at(bars[:2], 1)]
    assert all(p["time"] <= bars[-1]["time"] for p in pt.detect_recent(bars))


# ------------------------------------------------------------------ setup
def test_long_setup_levels_risk_and_reward():
    s = build_setup("LONG", 100.0, 1.0, support=[98.5, 96.0], resistance=[103.0, 106.0])
    assert s["stop"] == 98.25 and s["risk_per_share"] == 1.75 and s["targets"][0] == 103.0 and s["reward_to_risk"] == round(3.0 / 1.75, 2)
    assert s["entry_zone"] == [99.7, 100.0] and s["zone_label"] == "Buy zone" and s["stop"] < s["entry"] < s["targets"][0] < s["targets"][1]


def test_short_setup_mirrors_and_defaults_without_levels():
    s = build_setup("SHORT", 100.0, 2.0, support=[], resistance=[])
    assert s["stop"] == 103.0 and s["targets"] == [95.5, 92.5] and s["reward_to_risk"] == 1.5 and s["zone_label"] == "Sell zone"
    assert s["stop"] > s["entry"] > s["targets"][0] > s["targets"][1]


def test_stop_is_kept_between_half_and_three_atr_and_missing_atr_gives_no_setup():
    near = build_setup("LONG", 100.0, 2.0, support=[99.8], resistance=[])        # support too close: falls back to 1.5 ATR
    assert near["risk_per_share"] == 3.0
    far = build_setup("LONG", 100.0, 1.0, support=[90.0], resistance=[])         # support too far: also 1.5 ATR
    assert far["risk_per_share"] == 1.5
    assert build_setup("LONG", 100.0, None, [], []) is None and build_setup("LONG", 100.0, 0, [], []) is None


# ------------------------------------------------------------------ signal engine
def trend_bars(n=80, drift=0.25):
    out, p = [], 100.0
    for i in range(n):
        o = p
        p += drift + (0.15 if i % 3 else -0.1)
        out.append(b(i, o, max(o, p) + 0.1, min(o, p) - 0.1, p, 1000 + i * 10))
    return out


LIVE = {"state": "OPEN", "message": "Live", "tick_age_seconds": 2}
CLOSED = {"state": "CLOSED", "message": "closed", "tick_age_seconds": 500}


def run(bars, market, interval=1, **kw):
    now = bars[-1]["time"] + 70
    an = analyse(bars, interval, {"high": 101, "low": 98, "close": 99}, now, True)
    return stock_signal(an, market, interval, datetime.fromtimestamp(now, timezone.utc), **kw)


def test_uptrend_gives_bullish_setup_with_reasons_invalidation_and_freshness():
    sig = run(trend_bars(), LIVE)
    assert sig["bias"] == "Bullish" and sig["action"] == "BUY" and sig["data"]["status"] == "LIVE"
    assert sig["setup"]["direction"] == "LONG" and sig["setup"]["stop"] < sig["setup"]["entry"] and sig["setup"]["reward_to_risk"] > 0
    assert sig["reasons"] and sig["invalidation"] and sig["generated_at"] and sig["as_of_candle"]
    assert 0 <= sig["confidence"]["value"] <= 100 and "not a probability" in sig["confidence"]["meaning"].lower()
    assert sig["momentum"]["label"] and sig["volatility"]["label"] in {"Low", "Normal", "High"} and 0 <= sig["trend_strength"] <= 100


def test_downtrend_gives_bearish_short_setup():
    sig = run([b(i, x["open"], x["high"], x["low"], x["close"], x["volume"]) for i, x in enumerate(trend_bars(drift=-0.25))][::1], LIVE)
    bars = []
    p = 130.0
    for i in range(80):
        o = p
        p -= 0.25 + (0.15 if i % 3 else -0.1)
        bars.append(b(i, o, max(o, p) + 0.1, min(o, p) - 0.1, p, 1000 + i * 10))
    sig = run(bars, LIVE)
    assert sig["bias"] == "Bearish" and sig["action"] == "SELL" and sig["setup"]["direction"] == "SHORT" and sig["setup"]["stop"] > sig["setup"]["entry"]


def test_stale_or_missing_data_produces_no_signal():
    bars = trend_bars()
    delayed = run(bars, {"state": "DELAYED", "message": "Data is delayed: last price 90 seconds ago.", "tick_age_seconds": 90})
    nofeed = run(bars, {"state": "NO_FEED", "message": "no feed", "tick_age_seconds": None})
    for sig in (delayed, nofeed):
        assert sig["bias"] == "Unavailable" and sig["action"] == "NONE" and sig["setup"] is None
    assert delayed["data"]["status"] == "DELAYED" and nofeed["data"]["status"] == "UNAVAILABLE"
    assert run(bars, None)["data"]["status"] == "UNAVAILABLE"


def test_market_closed_signal_is_labelled_historical():
    sig = run(trend_bars(), CLOSED)
    assert sig["data"]["status"] == "HISTORICAL" and "last completed session" in sig["data"]["message"] and sig["bias"] in {"Bullish", "Bearish", "Neutral"}


def test_too_few_candles_is_unavailable_not_neutral():
    sig = run(trend_bars(n=20), LIVE)
    assert sig["bias"] == "Unavailable" and "closed" in sig["reasons"][0]


def test_data_status_labels():
    assert data_status({"state": "OPEN", "tick_age_seconds": 1})["status"] == "LIVE"
    assert data_status({"state": "CLOSED"})["status"] == "HISTORICAL"
    assert data_status(None)["status"] == "UNAVAILABLE"


def test_patterns_nudge_the_score_by_a_capped_amount_and_cannot_flip_a_neutral_reading_alone():
    from premium.signal_engine import BUY_AT, PATTERN_CAP, PATTERN_WEIGHT

    assert PATTERN_CAP < BUY_AT and PATTERN_WEIGHT <= PATTERN_CAP
    bars = trend_bars()
    p = bars[-3]["close"]
    bars[-2] = b(78, p + 0.6, p + 0.7, p - 0.1, p, 1500)           # a falling candle
    bars[-1] = b(79, p - 0.1, p + 1.6, p - 0.2, p + 1.5, 2500)     # a rising candle that covers it
    now = bars[-1]["time"] + 70
    an = analyse(bars, 1, {"high": 101, "low": 98, "close": 99}, now, True)
    sig = stock_signal(an, LIVE, 1, datetime.fromtimestamp(now, timezone.utc))
    assert any(x["name"] == "Bullish engulfing" for x in sig["patterns"])
    bullish = sum(1 for x in sig["patterns"] if x["direction"] == "bullish")
    assert bullish >= 1 and sig["score"] == min(100, an["signal"]["score"] + min(PATTERN_CAP, PATTERN_WEIGHT * bullish))
    assert any("Pattern: Bullish engulfing" in r for r in sig["reasons"])
