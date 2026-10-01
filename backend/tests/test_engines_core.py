"""Unit tests for the research/live separation. Pure Python: no running server or database needed.
Run: pytest -n 0 tests/test_engines_core.py"""
import ast
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from live import guard
from live.engine import generate, replay
from live.inputs import ChainRow, Leg, LiveInputs
from research.backtest import check_no_lookahead, decisions, run_backtest
from research.optimize import candidates, optimize, walk_forward
from shared.bars import resample
from shared.config import CalibrationBand, EngineConfig, Validation, load_config, save_config
from shared.indicators import ema, rsi
from shared.strategy import decide, decide_series

BACKEND = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))
# Wednesday 10:30 IST, inside the entry window
AS_OF = datetime(2026, 6, 3, 10, 30, 3, tzinfo=IST)


def synthetic_days(n_days: int, seed: int = 7, bars: int = 120, with_pcr: bool = True) -> dict[str, list[dict]]:
    """Regime-switching random walk: persistent trends (so a trend model has an edge) plus noise."""
    rng, days, day0 = random.Random(seed), {}, datetime(2026, 1, 5, 9, 15, tzinfo=IST)
    price = 22000.0
    for d in range(n_days):
        start = day0 + timedelta(days=d)
        drift, series = rng.choice([-1, 1]) * 0.6, []
        for m in range(bars):
            if m % 30 == 0:
                drift = rng.choice([-1, 1]) * 0.6
            o = price
            price += drift + rng.gauss(0, 1.0)
            bar = {"time": int((start + timedelta(minutes=m)).timestamp()), "open": o, "high": max(o, price) + 0.2, "low": min(o, price) - 0.2, "close": price}
            if with_pcr:
                bar["pcr"] = max(0.4, min(1.8, 1 + drift * 0.4 + rng.gauss(0, 0.1)))
            series.append(bar)
        days[start.date().isoformat()] = series
    return days


def uptrend_inputs(as_of: datetime = AS_OF, spot: float = 22500.0, n: int = 60) -> LiveInputs:
    end = int(as_of.timestamp()) // 60 * 60  # start of the forming minute
    candles = []
    for i in range(n):
        t = end - (n - i) * 60
        c = spot - (n - i) * 4 + (3 if i % 2 else 0)
        candles.append({"time": t, "open": c - 1, "high": c + 1, "low": c - 2, "close": c, "ticks": 20})
    strikes = range(22400, 22650, 50)
    chain = tuple(
        ChainRow(k, Leg(max(5, 22500 - k + 90), 2.0, 100000 + 1000 * i, 500, 14.0, max(0.05, 0.5 + (22500 - k) / 400), 5000 * (i + 1)),
                 Leg(max(5, k - 22500 + 90), -1.0, 40000 + 1000 * i, 100, 14.0, -max(0.05, 0.5 + (k - 22500) / 400), 4000 * (i + 1)))
        for i, k in enumerate(strikes)
    )
    # make puts dominate OI so PCR leans bullish too
    chain = tuple(ChainRow(r.strike, r.call, Leg(r.put.ltp, r.put.change, 260000, r.put.oi_change, r.put.iv, r.put.delta, r.put.volume)) for r in chain)
    return LiveInputs("NIFTY", as_of, "LIVE", "KOTAK_NEO", spot, as_of - timedelta(seconds=1), chain, as_of - timedelta(seconds=1), date(2026, 6, 4), tuple(candles))


CFG = EngineConfig(minimum_confidence=50)


# ------------------------------------------------------------------ separation
def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {f"{node.module}.{a.name}" for a in node.names}
    return names


def _identifiers(path: Path) -> set[str]:
    return {n.id for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Attribute)} | {a.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ImportFrom) for a in n.names}


def test_live_engine_never_imports_research_or_its_storage():
    for path in (BACKEND / "live").glob("*.py"):
        for name in _imports(path):
            assert not name.startswith("research"), f"{path.name} imports {name}"
        assert "research_db" not in _identifiers(path), f"{path.name} touches research_db"


def test_research_engine_never_imports_live_or_its_storage():
    for path in (BACKEND / "research").glob("*.py"):
        for name in _imports(path):
            assert not name.startswith("live"), f"{path.name} imports {name}"
            assert name not in {"lib.feed_worker", "lib.multi_feed_worker", "lib.candles", "lib.kotak_client"}, f"{path.name} imports {name}"
        assert "live_db" not in _identifiers(path), f"{path.name} touches live_db"


def test_shared_package_has_no_engine_or_database_dependencies():
    for path in (BACKEND / "shared").glob("*.py"):
        for name in _imports(path):
            assert not name.startswith(("research", "live", "lib", "motor", "pymongo")), f"{path.name} imports {name}"


def test_config_rejects_data_smuggled_in_extra_keys():
    with pytest.raises(Exception):
        EngineConfig.model_validate({"ema_fast": 9, "training_labels": [1, 0, 1]})
    with pytest.raises(Exception):
        EngineConfig.model_validate({"future_outcomes": []})


def test_config_roundtrip_and_defaults(tmp_path):
    assert load_config(tmp_path / "missing.json") == EngineConfig()
    cfg = EngineConfig(ema_fast=5, oi_weight=0.3, validation=Validation(accuracy_pct=61.2, signals=80, period_start="a", period_end="b", horizon_bars=15), calibration=[CalibrationBand(band="70-80", signals=10, hit_rate_pct=60)])
    save_config(cfg, tmp_path / "config.json")
    assert load_config(tmp_path / "config.json") == cfg


def test_validation_block_never_changes_a_live_signal():
    plain = generate(uptrend_inputs(), CFG)
    validated = generate(uptrend_inputs(), CFG.model_copy(update={"validation": Validation(accuracy_pct=99.0, signals=500, period_start="a", period_end="b", horizon_bars=15), "generated_by": "research:x"}))
    for key in ("action", "confidence", "strike", "risk", "reasons", "input_fingerprint"):
        assert plain[key] == validated[key]
    assert plain["historical_validation"]["validated"] is False and validated["historical_validation"]["accuracy_pct"] == 99.0


# ------------------------------------------------------------------ live engine
def test_uptrend_produces_buy_ce_with_strike_and_risk_levels():
    s = generate(uptrend_inputs(), CFG)
    assert s["label"] == "LIVE SIGNAL" and s["action"] == "BUY CE", s["reasons"]
    assert s["confidence"] >= 50 and s["confidence_label"] == "Current signal confidence"
    assert s["strike"]["type"] == "CE" and s["risk"]["premium_stop"] < s["risk"]["entry_premium"] < s["risk"]["premium_target"]
    assert s["historical_validation"]["validated"] is False  # confidence and historical accuracy are separate fields
    assert "accuracy" not in s and s["data_status"]["ok"]


def test_signal_is_reproducible_from_stored_inputs():
    inputs = uptrend_inputs()
    s = generate(inputs, CFG)
    assert replay(s, inputs.to_doc(), CFG)["reproducible"] is True
    assert generate(inputs, CFG) == s  # deterministic


def test_future_candles_are_never_used_and_do_not_change_the_signal():
    inputs = uptrend_inputs()
    base = generate(inputs, CFG)
    future = tuple({"time": int(inputs.as_of.timestamp()) // 60 * 60 + 60 * k, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "ticks": 1} for k in range(0, 10))
    poisoned = LiveInputs(**{**inputs.__dict__, "candles": inputs.candles + future})
    assert generate(poisoned, CFG) == base  # identical in every field, including the fingerprint of the data actually used


def test_forming_candle_excluded_from_indicators():
    inputs = uptrend_inputs()
    forming = {"time": int(inputs.as_of.timestamp()) // 60 * 60, "open": 5.0, "high": 5.0, "low": 5.0, "close": 5.0, "ticks": 1}
    s = generate(LiveInputs(**{**inputs.__dict__, "candles": inputs.candles + (forming,)}), CFG)
    assert s["action"] == "BUY CE"


@pytest.mark.parametrize("mutate,code", [
    (lambda i: {"candles": i.candles + ({"time": int(i.as_of.timestamp()) + 600, "open": 1, "high": 1, "low": 1, "close": 1},)}, "FUTURE_CANDLE"),
    (lambda i: {"candles": i.candles + ({"time": int(i.as_of.timestamp()) // 60 * 60, "open": 1, "high": 1, "low": 1, "close": 1},)}, "UNFINISHED_CANDLE"),
    (lambda i: {"spot_time": i.as_of + timedelta(seconds=30)}, "FUTURE_DATA"),
    (lambda i: {"chain_time": i.as_of - timedelta(seconds=60)}, "STALE_DATA"),
    (lambda i: {"expiry": date(2026, 6, 2)}, "EXPIRED_CONTRACT"),
    (lambda i: {"feed_state": "STALE"}, "FEED_NOT_LIVE"),
    (lambda i: {"source": "DEMO"}, "NOT_REAL_DATA"),
    (lambda i: {"chain": ()}, "NO_CHAIN"),
    (lambda i: {"candles": tuple(reversed(i.candles))}, "CANDLE_ORDER"),
])
def test_guard_blocks(mutate, code):
    inputs = uptrend_inputs()
    bad = LiveInputs(**{**inputs.__dict__, **mutate(inputs)})
    codes = {v.code for v in guard.validate(bad, CFG, now=AS_OF)}
    assert code in codes


def test_as_of_ahead_of_clock_is_blocked():
    codes = {v.code for v in guard.validate(uptrend_inputs(), CFG, now=AS_OF - timedelta(minutes=5))}
    assert "FUTURE_AS_OF" in codes


def test_demo_data_is_flagged_simulated_when_allowed():
    inputs = uptrend_inputs()
    s = generate(LiveInputs(**{**inputs.__dict__, "source": "DEMO", "feed_state": "DEMO"}), CFG, require_live=False)
    assert s["simulated"] is True
    assert generate(LiveInputs(**{**inputs.__dict__, "source": "DEMO", "feed_state": "DEMO"}), CFG)["action"] == "NO SIGNAL"


def test_risk_gate_outside_entry_window():
    late = datetime(2026, 6, 3, 15, 10, 3, tzinfo=IST)
    s = generate(uptrend_inputs(as_of=late), CFG)
    assert s["action"] == "NO SIGNAL" and "Risk gate" in s["reasons"][0]


def test_insufficient_candles_gives_no_signal():
    s = generate(uptrend_inputs(n=10), CFG)
    assert s["action"] == "NO SIGNAL" and "closed candles" in s["reasons"][0]


# ------------------------------------------------------------------ research
def test_indicators_are_causal():
    rng = random.Random(1)
    xs = [100 + rng.gauss(0, 2) for _ in range(80)]
    for k in (20, 50, 79):
        assert ema(xs, 9)[: k + 1] == ema(xs[: k + 1], 9)
        assert rsi(xs, 14)[: k + 1] == rsi(xs[: k + 1], 14)


def test_series_decisions_equal_prefix_decisions():
    days = synthetic_days(1)
    bars = next(iter(days.values()))
    closes, pcrs = [b["close"] for b in bars], [b["pcr"] for b in bars]
    cfg = EngineConfig(minimum_confidence=40)
    series = decide_series(closes, pcrs, cfg)
    for i in range(0, len(bars), 7):
        assert series[i] == decide(closes[: i + 1], pcrs[i], cfg)


def test_no_lookahead_check_passes_and_catches_a_leaky_series(monkeypatch):
    days = synthetic_days(4)
    assert check_no_lookahead(days, EngineConfig(minimum_confidence=40))["passed"]
    import research.backtest as bt

    real = bt.decide_series

    def leaky(closes, pcrs, cfg):  # peeks one bar ahead: centered smoothing
        smoothed = [(closes[min(i + 1, len(closes) - 1)] + closes[i]) / 2 for i in range(len(closes))]
        return real(smoothed, pcrs, cfg)

    monkeypatch.setattr(bt, "decide_series", leaky)
    assert check_no_lookahead(days, EngineConfig(minimum_confidence=40))["passed"] is False


def test_resample_pcr_and_alignment():
    days = synthetic_days(1)
    bars = next(iter(days.values()))
    five = resample(bars, 5)
    assert len(five) == len(bars) // 5 and "pcr" in five[0]


def test_walk_forward_test_sessions_never_in_training():
    days = synthetic_days(14)
    grid = {"ema_fast": [5, 9], "ema_slow": [20], "rsi_period": [14], "oi_weight": [0.0, 0.22], "minimum_confidence": [40, 60]}
    wf = walk_forward(days, EngineConfig(), 10, train_days=6, test_days=2, grid=grid)
    assert wf["folds"]
    for fold in wf["folds"]:
        assert fold["train"][1] < fold["test"][0]


def test_optimize_returns_validated_config_with_separate_accuracy():
    days = synthetic_days(16)
    grid = {"ema_fast": [5, 9], "ema_slow": [20], "rsi_period": [14], "oi_weight": [0.0, 0.22], "minimum_confidence": [30, 50]}
    report = optimize(days, EngineConfig(), horizon_bars=10, train_days=8, test_days=4, grid=grid)
    assert report["status"] == "OK", report
    assert report["leakage_check"]["passed"]
    cfg = EngineConfig.model_validate(report["config"])
    assert cfg.validation and cfg.validation.signals == report["oos"]["signals"]
    assert cfg.generated_by.startswith("research:")


def test_optimize_refuses_with_too_little_data_and_writes_no_config():
    report = optimize(synthetic_days(3), EngineConfig(), train_days=10, test_days=3)
    assert report["status"] == "INSUFFICIENT_DATA" and report["config"] is None


def test_candidate_grid_never_has_slow_below_fast():
    assert all(c.ema_slow > c.ema_fast for c in candidates(EngineConfig()))
