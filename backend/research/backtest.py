"""Backtest of the shared signal model on historical bars.

Look-ahead rule: the decision at bar i is computed from `bars[: i + 1]` only; the outcome is read from
bars strictly AFTER i and is never given to `decide`. `check_no_lookahead` proves this on real data by
re-running on a truncated series and requiring identical decisions.

Scope: outcomes are measured on the INDEX (did spot move in the signal's direction `horizon_bars` later, inside
the same session). Historical option premiums are not stored, so this is direction accuracy, not option P&L.
"""
from dataclasses import dataclass, field
from typing import Any

from shared.bars import resample
from shared.config import EngineConfig
from shared.strategy import decide_series

BANDS = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 101)]


@dataclass
class TradeRecord:
    time: int
    direction: str
    confidence: int
    entry: float
    exit: float
    move_pts: float  # signed in the signal's favour
    hit: bool


@dataclass
class BacktestResult:
    trades: list[TradeRecord] = field(default_factory=list)

    @property
    def signals(self) -> int:
        return len(self.trades)

    @property
    def hits(self) -> int:
        return sum(t.hit for t in self.trades)

    @property
    def accuracy_pct(self) -> float | None:
        return round(100 * self.hits / self.signals, 2) if self.signals else None

    @property
    def expectancy_pts(self) -> float | None:
        return round(sum(t.move_pts for t in self.trades) / self.signals, 2) if self.signals else None

    def calibration(self) -> list[dict[str, Any]]:
        out = []
        for lo, hi in BANDS:
            sel = [t for t in self.trades if lo <= t.confidence < hi]
            label = f"{lo}-{min(hi, 100)}"
            out.append({"band": label, "signals": len(sel), "hit_rate_pct": round(100 * sum(t.hit for t in sel) / len(sel), 2) if sel else None})
        return out

    def summary(self) -> dict[str, Any]:
        return {"signals": self.signals, "hits": self.hits, "accuracy_pct": self.accuracy_pct, "expectancy_pts": self.expectancy_pts}


def decisions(bars: list[dict[str, Any]], cfg: EngineConfig) -> list[tuple[int, Any]]:
    """(bar index, Decision) for every bar; the decision at i depends only on bars[:i+1]."""
    out = decide_series([b["close"] for b in bars], [b.get("pcr") for b in bars], cfg)
    return list(enumerate(out))


def backtest_day(bars: list[dict[str, Any]], cfg: EngineConfig, horizon_bars: int) -> list[TradeRecord]:
    """One session. Signals do not overlap: after a signal, wait `horizon_bars` before the next."""
    bars = resample(bars, cfg.candle_minutes)
    trades: list[TradeRecord] = []
    next_allowed = 0
    for i, decision in decisions(bars, cfg):
        if i < next_allowed or decision.direction is None:
            continue
        if i + horizon_bars >= len(bars):  # outcome would fall outside this session
            break
        entry, exit_ = bars[i]["close"], bars[i + horizon_bars]["close"]
        move = (exit_ - entry) if decision.direction == "CE" else (entry - exit_)
        trades.append(TradeRecord(bars[i]["time"], decision.direction, decision.confidence, entry, exit_, round(move, 2), move > 0))
        next_allowed = i + horizon_bars
    return trades


def run_backtest(days: dict[str, list[dict[str, Any]]], cfg: EngineConfig, horizon_bars: int) -> BacktestResult:
    """Indicators restart each session so overnight gaps cannot leak into the warm-up."""
    result = BacktestResult()
    for day in sorted(days):
        result.trades.extend(backtest_day(days[day], cfg, horizon_bars))
    return result


def check_no_lookahead(days: dict[str, list[dict[str, Any]]], cfg: EngineConfig, samples: int = 5) -> dict[str, Any]:
    """Re-run each sampled session truncated at a cut point; decisions up to the cut must be identical."""
    checked = 0
    for day in sorted(days)[:samples]:
        bars = resample(days[day], cfg.candle_minutes)
        if len(bars) < cfg.warmup_candles + 4:
            continue
        cut = len(bars) * 2 // 3
        full = decisions(bars, cfg)[: cut + 1]
        trunc = decisions(bars[: cut + 1], cfg)
        for (_, a), (_, b) in zip(full, trunc, strict=True):
            if (a.direction, a.confidence, a.combined) != (b.direction, b.confidence, b.combined):
                return {"passed": False, "days_checked": checked, "detail": f"decision changed when future bars were removed ({day})"}
        checked += 1
    return {"passed": True, "days_checked": checked, "detail": "decisions identical with and without future bars"}
