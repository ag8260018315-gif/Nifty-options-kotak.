"""Risk management gate and levels for the chosen strike."""
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from shared.config import EngineConfig

IST = ZoneInfo("Asia/Kolkata")


def _t(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def entry_window_reason(as_of: datetime, cfg: EngineConfig) -> str | None:
    local = as_of.astimezone(IST)
    if local.weekday() >= 5:
        return "market is closed (weekend)"
    if local.time() < _t(cfg.no_entry_before):
        return f"no new signals before {cfg.no_entry_before} IST"
    if local.time() >= _t(cfg.no_entry_after):
        return f"no new signals after {cfg.no_entry_after} IST"
    return None


def risk_levels(direction: str, premium: float, spot: float, candles: list[dict], cfg: EngineConfig) -> dict[str, Any]:
    window = candles[-cfg.index_stop_window_candles:]
    index_stop = None
    if window:
        index_stop = min(c["low"] for c in window) if direction == "CE" else max(c["high"] for c in window)
    return {
        "entry_premium": round(premium, 2),
        "premium_stop": round(premium * (1 - cfg.premium_stop_pct / 100), 2),
        "premium_target": round(premium * (1 + cfg.premium_target_pct / 100), 2),
        "reward_risk": round(cfg.premium_target_pct / cfg.premium_stop_pct, 2),
        "index_stop": None if index_stop is None else round(index_stop, 2),
        "index_stop_points": None if index_stop is None else round(abs(spot - index_stop), 2),
    }


def passes_reward_risk(levels: dict[str, Any], cfg: EngineConfig) -> bool:
    return levels["reward_risk"] >= cfg.min_reward_risk
