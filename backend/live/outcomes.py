"""Signal outcomes: observed AFTER the fact from later live ticks. Never fed back into signal generation."""
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from live.inputs import LiveInputs

IST = ZoneInfo("Asia/Kolkata")
SESSION_END = time(15, 25)


def resolve(signal: dict[str, Any], inputs: LiveInputs) -> dict[str, Any] | None:
    """Compare the signal's own strike premium now (inputs are current, so later than the signal) against its stop/target."""
    if inputs.as_of <= datetime.fromisoformat(signal["as_of"]):
        return None
    strike = signal["strike"]["strike"]
    row = next((r for r in inputs.chain if r.strike == strike), None)
    if row is None:
        return None
    premium = (row.call if signal["direction"] == "CE" else row.put).ltp
    if premium <= 0:
        return None
    risk = signal["risk"]
    reason = None
    if premium <= risk["premium_stop"]:
        reason = "STOP_HIT"
    elif premium >= risk["premium_target"]:
        reason = "TARGET_HIT"
    elif inputs.as_of.astimezone(IST).time() >= SESSION_END or inputs.as_of.astimezone(IST).date() > datetime.fromisoformat(signal["as_of"]).astimezone(IST).date():
        reason = "SESSION_END"
    if reason is None:
        return None
    entry = risk["entry_premium"]
    return {
        "signal_id": signal["signal_id"], "symbol": signal["symbol"], "outcome": reason, "exit_premium": round(premium, 2),
        "return_pct": round((premium - entry) / entry * 100, 2), "resolved_at": inputs.as_of.isoformat(),
    }
