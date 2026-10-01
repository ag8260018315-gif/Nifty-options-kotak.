"""Strike scoring: pick the option to express a CE/PE direction from the CURRENT chain.

score = 0.40 * delta closeness to target + 0.35 * liquidity (OI and volume vs the window) + 0.25 * premium momentum
Candidates: strikes within `strike_window` of ATM whose premium and OI pass the config minimums.
"""
from typing import Any

from live.inputs import ChainRow, LiveInputs
from shared.config import EngineConfig


def _rank(value: float, values: list[float]) -> float:
    top = max(values) if values else 0
    return value / top if top > 0 else 0.0


def score_strikes(inputs: LiveInputs, direction: str, cfg: EngineConfig) -> list[dict[str, Any]]:
    rows = sorted(inputs.chain, key=lambda r: r.strike)
    if not rows:
        return []
    atm = min(rows, key=lambda r: abs(r.strike - inputs.spot))
    step_rows = [r for r in rows if abs(rows.index(r) - rows.index(atm)) <= cfg.strike_window]
    legs = [(r, r.call if direction == "CE" else r.put) for r in step_rows]
    legs = [(r, leg) for r, leg in legs if leg.ltp >= cfg.min_premium and leg.ltp > 0 and leg.oi >= cfg.min_strike_oi]
    if not legs:
        return []
    oi_vals = [float(leg.oi) for _, leg in legs]
    vol_vals = [float(leg.volume or 0) for _, leg in legs]
    out = []
    for row, leg in legs:
        delta = abs(leg.delta)
        delta_score = max(0.0, 1 - abs(delta - cfg.target_delta) / cfg.target_delta)
        liquidity = 0.6 * _rank(leg.oi, oi_vals) + 0.4 * _rank(leg.volume or 0, vol_vals)
        momentum = max(0.0, min(1.0, 0.5 + (leg.change / leg.ltp) * 2.5)) if leg.ltp else 0.0
        out.append({
            "strike": row.strike, "type": direction, "premium": round(leg.ltp, 2), "delta": round(delta, 3), "iv": round(leg.iv, 2),
            "oi": leg.oi, "volume": leg.volume, "is_atm": row.strike == atm.strike,
            "score": round(0.40 * delta_score + 0.35 * liquidity + 0.25 * momentum, 4),
        })
    return sorted(out, key=lambda s: (-s["score"], abs(s["strike"] - inputs.spot)))
