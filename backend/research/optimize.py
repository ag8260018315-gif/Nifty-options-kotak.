"""Parameter search with walk-forward validation. Produces config values; never a live trade.

Walk-forward: parameters are chosen on a TRAIN window of sessions and scored only on the following TEST
sessions the search never saw. The accuracy reported for the config is the pooled out-of-sample result.
"""
import itertools
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from research.backtest import BacktestResult, check_no_lookahead, run_backtest
from shared.config import CalibrationBand, EngineConfig, Validation

GRID = {
    "ema_fast": [5, 9, 12],
    "ema_slow": [20, 26, 50],
    "rsi_period": [7, 14],
    "oi_weight": [0.0, 0.11, 0.22, 0.33],
    "minimum_confidence": [60, 70, 78, 85],
}
MIN_TRAIN_SIGNALS = 20  # a parameter set with fewer train signals is not trusted
MIN_DAYS = 8


def candidates(base: EngineConfig, grid: dict[str, list] | None = None) -> list[EngineConfig]:
    grid = grid or GRID
    keys = list(grid)
    out = []
    for values in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, values))
        if params.get("ema_slow", base.ema_slow) <= params.get("ema_fast", base.ema_fast):
            continue
        rest = 1.0 - params.get("oi_weight", base.oi_weight)
        out.append(base.model_copy(update={**params, "ema_weight": round(rest / 2, 4), "rsi_weight": round(rest / 2, 4)}))
    return out


def _wilson_lower(hits: int, n: int, z: float = 1.64) -> float:
    """Lower confidence bound of the hit rate: stops a lucky 3-for-3 outranking a solid 60-for-90."""
    if n == 0:
        return 0.0
    p = hits / n
    return (p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def _score(result: BacktestResult) -> float:
    return -1.0 if result.signals < MIN_TRAIN_SIGNALS else _wilson_lower(result.hits, result.signals)


def best_params(days: dict[str, list], base: EngineConfig, horizon_bars: int, grid: dict[str, list] | None = None) -> tuple[EngineConfig, BacktestResult]:
    best: tuple[float, EngineConfig, BacktestResult] | None = None
    for cfg in candidates(base, grid):
        result = run_backtest(days, cfg, horizon_bars)
        score = _score(result)
        if best is None or score > best[0]:
            best = (score, cfg, result)
    assert best is not None
    return best[1], best[2]


def walk_forward(days: dict[str, list], base: EngineConfig, horizon_bars: int, train_days: int, test_days: int, grid: dict[str, list] | None = None) -> dict[str, Any]:
    names = sorted(days)
    folds, oos = [], BacktestResult()
    start = 0
    while start + train_days + test_days <= len(names):
        train = {d: days[d] for d in names[start : start + train_days]}
        test = {d: days[d] for d in names[start + train_days : start + train_days + test_days]}
        cfg, in_sample = best_params(train, base, horizon_bars, grid)
        out_sample = run_backtest(test, cfg, horizon_bars)  # parameters were chosen without these sessions
        oos.trades.extend(out_sample.trades)
        folds.append({
            "train": [names[start], names[start + train_days - 1]],
            "test": [names[start + train_days], names[start + train_days + test_days - 1]],
            "params": {k: getattr(cfg, k) for k in GRID},
            "in_sample": in_sample.summary(),
            "out_of_sample": out_sample.summary(),
        })
        start += test_days
    return {"folds": folds, "oos": oos}


def optimize(days: dict[str, list], base: EngineConfig | None = None, horizon_bars: int = 15, train_days: int = 10, test_days: int = 3, grid: dict[str, list] | None = None, symbol: str = "NIFTY") -> dict[str, Any]:
    """Full research run. Returns a report; `config` is None unless there is enough data to validate."""
    base = base or EngineConfig()
    run_id = uuid.uuid4().hex[:12]
    names = sorted(days)
    report: dict[str, Any] = {
        "run_id": run_id, "symbol": symbol, "created_at": datetime.now(timezone.utc).isoformat(),
        "horizon_bars": horizon_bars, "train_days": train_days, "test_days": test_days,
        "days": len(names), "period": [names[0], names[-1]] if names else None, "grid_size": len(candidates(base, grid)),
        "status": "INSUFFICIENT_DATA", "config": None, "folds": [], "validation": None, "calibration": [],
        "leakage_check": None,
        "note": "Accuracy is out-of-sample index-direction accuracy at the horizon; it is not a live win rate and not option P&L.",
    }
    if len(names) < max(MIN_DAYS, train_days + test_days):
        report["note"] += f" Need at least {max(MIN_DAYS, train_days + test_days)} sessions, found {len(names)}."
        return report
    wf = walk_forward(days, base, horizon_bars, train_days, test_days, grid)
    oos: BacktestResult = wf["oos"]
    final_cfg, final_in_sample = best_params({d: days[d] for d in names[-train_days:]}, base, horizon_bars, grid)
    report["folds"] = wf["folds"]
    report["leakage_check"] = check_no_lookahead(days, final_cfg)
    report["in_sample_final"] = final_in_sample.summary()
    report["oos"] = oos.summary()
    if oos.signals == 0 or not report["leakage_check"]["passed"]:
        report["status"] = "LEAKAGE_DETECTED" if not report["leakage_check"]["passed"] else "NO_OOS_SIGNALS"
        return report
    validation = Validation(accuracy_pct=oos.accuracy_pct, signals=oos.signals, period_start=names[0], period_end=names[-1], horizon_bars=horizon_bars)
    calibration = [CalibrationBand(**b) for b in oos.calibration()]
    final = final_cfg.model_copy(update={"validation": validation, "calibration": calibration, "generated_at": datetime.now(timezone.utc), "generated_by": f"research:{run_id}"})
    report.update(status="OK", config=final.model_dump(mode="json"), validation=validation.model_dump(), calibration=[c.model_dump() for c in calibration])
    return report
