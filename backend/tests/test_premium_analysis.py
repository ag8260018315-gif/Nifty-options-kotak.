"""Premium analysis: indicators, support/resistance, volume, trend and the transparent signal. Pure Python."""
import random

from premium.analysis import MIN_BARS, analyse, pivots, resample_ohlcv, support_resistance
from shared.indicators import atr, bollinger, ema, macd, sma

T0 = 1_780_000_000 // 60 * 60


def trend_bars(n=80, drift=0.25, seed=3, vol=lambda i: 1000 + i * 10, start=100.0):
    rng, p, out = random.Random(seed), start, []
    for i in range(n):
        o = p
        p += drift + rng.gauss(0, 0.2)
        out.append({"time": T0 + i * 60, "open": o, "high": max(o, p) + 0.1, "low": min(o, p) - 0.1, "close": p, "volume": vol(i)})
    return out


def run(bars, **kw):
    kw.setdefault("has_volume", True)
    kw.setdefault("prev_day", {"high": 101, "low": 98, "close": 99})
    return analyse(bars, 1, kw.pop("prev_day"), T0 + (len(bars) + 1) * 60, **kw)


def test_new_indicators_are_causal():
    xs = [100 + random.Random(1).gauss(0, 2) * i % 7 for i in range(90)]
    for k in (30, 60, 89):
        assert macd(xs)[2][: k + 1] == macd(xs[: k + 1])[2]
        assert sma(xs, 20)[: k + 1] == sma(xs[: k + 1], 20)
        assert bollinger(xs)[1][: k + 1] == bollinger(xs[: k + 1])[1]
        h, l = [x + 1 for x in xs], [x - 1 for x in xs]
        assert atr(h, l, xs)[: k + 1] == atr(h[: k + 1], l[: k + 1], xs[: k + 1])


def test_uptrend_gives_buy_and_downtrend_gives_sell():
    up, down = run(trend_bars()), run(trend_bars(drift=-0.25, start=130))
    assert up["signal"]["action"] == "BUY" and up["trend"]["label"] == "UPTREND" and up["signal"]["score"] >= 35
    assert down["signal"]["action"] == "SELL" and down["trend"]["label"] == "DOWNTREND"
    assert all(isinstance(r, str) for r in up["signal"]["reasons"])


def test_not_enough_candles_is_building_never_a_signal():
    out = run(trend_bars(n=MIN_BARS - 3))
    assert out["signal"]["action"] == "BUILDING" and out["trend"]["label"] == "BUILDING" and str(MIN_BARS) in out["signal"]["reasons"][0]


def test_forming_candle_is_ignored_by_the_signal():
    bars = trend_bars()
    now = bars[-1]["time"] + 30  # the last candle is still forming
    with_crash = bars[:-1] + [{**bars[-1], "close": 1.0, "low": 1.0}]
    a = analyse(bars, 1, None, now, True)["signal"]
    b = analyse(with_crash, 1, None, now, True)["signal"]
    assert a == b  # a wild forming candle cannot change the signal
    assert analyse(bars, 1, None, now, True)["bars_closed"] == len(bars) - 1


def test_volume_spike_and_buying_pressure():
    bars = trend_bars(vol=lambda i: 5000 if i == 79 else 1000)
    v = run(bars)["volume"]
    assert v["available"] and v["spike"] and v["relative"] == 5.0 and v["buying_pressure_pct"] > 50


def test_index_without_volume_is_honest_and_has_no_vwap():
    out = run(trend_bars(vol=lambda i: 0), has_volume=False)
    assert out["volume"]["available"] is False and all(x is None for x in out["series"]["vwap"])


def test_pivots_and_levels():
    p = pivots({"high": 110.0, "low": 90.0, "close": 100.0})
    assert round(p["pp"], 2) == 100.0 and p["r1"] == 110.0 and p["s1"] == 90.0 and p["r2"] == 120.0 and p["s2"] == 80.0
    assert pivots(None) is None
    lv = support_resistance(trend_bars(), 120.0, {"high": 130.0, "low": 90.0, "close": 100.0}, 125.0, 99.0)
    assert lv["nearest_resistance"] > 120.0 > lv["nearest_support"]


def test_resample_sums_volume_and_aligns_to_ist():
    bars = trend_bars(n=10)
    five = resample_ohlcv(bars, 5)
    assert sum(b["volume"] for b in five) == sum(b["volume"] for b in bars)
    assert all(b["high"] >= b["low"] for b in five)


def test_series_lengths_match_candles():
    out = run(trend_bars())
    n = len(out["candles"])
    assert all(len(v) == n for v in out["series"].values())
