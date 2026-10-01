"""The live signal pipeline. A pure function of (LiveInputs, EngineConfig): no clock, no database, no history.

validation -> indicators -> option-chain analysis -> strike scoring -> confidence -> risk management -> signal
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from live.guard import closed_candles, validate
from live.inputs import LiveInputs
from live.risk import entry_window_reason, passes_reward_risk, risk_levels
from live.strikes import score_strikes
from shared.bars import resample
from shared.config import EngineConfig
from shared.strategy import decide

DISCLAIMER = "Informational only. The app never places orders. Confidence is a current signal-strength score, not a win probability."


def chain_pcr(inputs: LiveInputs) -> float | None:
    """Put OI / call OI over the chain window, recomputed from the inputs (not read from a stored summary)."""
    calls = sum(r.call.oi for r in inputs.chain)
    puts = sum(r.put.oi for r in inputs.chain)
    return round(puts / calls, 4) if calls > 0 else None


def fingerprint(inputs: LiveInputs, cfg: EngineConfig) -> str:
    blob = json.dumps({"inputs": inputs.to_doc(), "config": cfg.signal_params()}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _historical(cfg: EngineConfig) -> dict[str, Any]:
    """Research's validated figure, passed through for DISPLAY only. It never enters the computation above it."""
    v = cfg.validation
    return {
        "validated": v is not None,
        "accuracy_pct": v.accuracy_pct if v else None,
        "signals": v.signals if v else None,
        "period": [v.period_start, v.period_end] if v else None,
        "method": v.method if v else None,
        "measured_on": v.measured_on if v else None,
        "label": "Historical validated accuracy" if v else "Not validated historically",
        "generated_by": cfg.generated_by,
    }


def generate(inputs: LiveInputs, cfg: EngineConfig, now: datetime | None = None, require_live: bool = True) -> dict[str, Any]:
    """Returns a signal document. `action` is BUY CE / BUY PE / NO SIGNAL; `reasons` always say why."""
    width = cfg.candle_minutes * 60
    candles = closed_candles(inputs.candles, inputs.as_of, inputs.interval_seconds)  # forming candle never used
    inputs_checked = LiveInputs(**{**inputs.__dict__, "candles": tuple(candles)})
    violations = validate(inputs_checked, cfg, now=now, require_live=require_live)
    bars = resample([dict(c) for c in candles], cfg.candle_minutes)
    # a resampled bucket is only usable once its whole window has closed
    bars = [b for b in bars if b["time"] + width <= inputs.as_of.timestamp()]
    base: dict[str, Any] = {
        "label": "LIVE SIGNAL",
        "symbol": inputs.symbol,
        "as_of": inputs.as_of.isoformat(),
        "source": inputs.source,
        "simulated": inputs.source != "KOTAK_NEO",
        "action": "NO SIGNAL",
        "direction": None,
        "confidence": 0,
        "confidence_label": "Current signal confidence",
        "historical_validation": _historical(cfg),
        "strike": None,
        "alternatives": [],
        "risk": None,
        "components": {},
        "reasons": [],
        "data_status": {
            "feed_state": inputs.feed_state,
            "candles_used": len(bars),
            "candles_required": cfg.warmup_candles,
            "violations": [v.as_dict() for v in violations],
            "ok": not violations,
        },
        "config_fingerprint": cfg.fingerprint(),
        "input_fingerprint": fingerprint(inputs_checked, cfg),  # of the data actually used (forming/future candles dropped)
        "disclaimer": DISCLAIMER,
    }
    if violations:
        base["reasons"] = [f"Blocked by data check: {v.detail}" for v in violations]
        return base
    pcr = chain_pcr(inputs)
    decision = decide([b["close"] for b in bars], pcr, cfg)
    base["confidence"], base["components"] = decision.confidence, {**decision.components, "pcr": pcr}
    if decision.direction is None:
        base["reasons"] = [decision.reason or "No directional edge right now."]
        return base
    blocked = entry_window_reason(inputs.as_of, cfg)
    if blocked:
        base["reasons"] = [f"Risk gate: {blocked}."]
        return base
    ranked = score_strikes(inputs, decision.direction, cfg)
    if not ranked:
        base["reasons"] = ["No strike in the window passes the liquidity and premium filters."]
        return base
    chosen = ranked[0]
    levels = risk_levels(decision.direction, chosen["premium"], inputs.spot, bars, cfg)
    if not passes_reward_risk(levels, cfg):
        base["reasons"] = [f"Risk gate: reward/risk {levels['reward_risk']} is below the {cfg.min_reward_risk} minimum."]
        return base
    side = "bullish" if decision.direction == "CE" else "bearish"
    base.update(
        action=f"BUY {decision.direction}", direction=decision.direction, strike=chosen, alternatives=ranked[1:3], risk=levels,
        signal_id=uuid.uuid5(uuid.NAMESPACE_URL, base["input_fingerprint"]).hex,
        reasons=[
            f"Trend (EMA {cfg.ema_fast}/{cfg.ema_slow}) and RSI({cfg.rsi_period}) = {decision.components['rsi_value']} combine {side}.",
            f"Open-interest lean from PCR {pcr}." if pcr is not None else "Open interest unavailable.",
            f"Confidence {decision.confidence} meets the {cfg.minimum_confidence} minimum.",
            f"Strike {chosen['strike']} {decision.direction}: delta {chosen['delta']}, premium {chosen['premium']}.",
        ],
    )
    return base


def replay(stored: dict[str, Any], inputs_doc: dict[str, Any], cfg: EngineConfig) -> dict[str, Any]:
    """Recompute a stored signal from the inputs saved with it. Reproducible means identical action, strike and confidence."""
    again = generate(LiveInputs.from_doc(inputs_doc), cfg, now=None, require_live=stored.get("source") == "KOTAK_NEO")
    keys = ("action", "confidence", "input_fingerprint")
    same = all(again[k] == stored[k] for k in keys) and (again["strike"] or {}).get("strike") == (stored["strike"] or {}).get("strike")
    return {"reproducible": same, "recomputed_action": again["action"], "recomputed_confidence": again["confidence"], "stored_action": stored["action"], "stored_confidence": stored["confidence"]}
