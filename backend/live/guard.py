"""Anti-lookahead protection. Runs on every evaluation; any violation blocks the signal.

Checks: no data timestamped after `as_of` (spot, chain, candles), no unfinished or future candles, candles ordered
and unique, data fresh enough, expiry not already past (no expiry hindsight), feed state is real and live, no
negative/zero premiums. Because the engine is a pure function of (LiveInputs, config), a signal is reproducible
from the inputs stored with it (see live.engine.replay).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from live.inputs import LiveInputs
from shared.config import EngineConfig

IST = ZoneInfo("Asia/Kolkata")
CLOCK_SKEW = timedelta(seconds=2)


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


def validate(inputs: LiveInputs, cfg: EngineConfig, now: datetime | None = None, require_live: bool = True) -> list[Violation]:
    """`now` is the wall clock when evaluating live; pass None when replaying a stored signal (age checks then use as_of only)."""
    out: list[Violation] = []
    as_of = inputs.as_of
    if as_of.tzinfo is None:
        return [Violation("NAIVE_AS_OF", "as_of must be timezone-aware")]
    if now is not None and as_of > now + CLOCK_SKEW:
        out.append(Violation("FUTURE_AS_OF", f"as_of {as_of.isoformat()} is ahead of the clock"))
    if require_live and inputs.feed_state != "LIVE":
        out.append(Violation("FEED_NOT_LIVE", f"feed state is {inputs.feed_state}; signals need live data"))
    if require_live and inputs.source != "KOTAK_NEO":
        out.append(Violation("NOT_REAL_DATA", f"source {inputs.source} is not live market data"))
    if inputs.spot <= 0:
        out.append(Violation("NO_SPOT", "no valid live spot price"))
    limit = timedelta(seconds=cfg.max_data_age_seconds)
    for name, stamp in (("spot", inputs.spot_time), ("option_chain", inputs.chain_time)):
        if stamp is None:
            out.append(Violation("NO_TIMESTAMP", f"{name} has no timestamp"))
            continue
        if stamp > as_of + CLOCK_SKEW:
            out.append(Violation("FUTURE_DATA", f"{name} timestamp {stamp.isoformat()} is after as_of"))
        elif require_live and as_of - stamp > limit:
            out.append(Violation("STALE_DATA", f"{name} is {(as_of - stamp).total_seconds():.0f}s old (limit {cfg.max_data_age_seconds}s)"))
    if not inputs.chain:
        out.append(Violation("NO_CHAIN", "option chain is empty"))
    for row in inputs.chain:
        if row.call.ltp < 0 or row.put.ltp < 0:
            out.append(Violation("BAD_PREMIUM", f"negative premium at strike {row.strike}"))
            break
    previous = None
    width = inputs.interval_seconds
    for candle in inputs.candles:
        t = candle["time"]
        end = datetime.fromtimestamp(t + width, timezone.utc)
        if datetime.fromtimestamp(t, timezone.utc) > as_of:
            out.append(Violation("FUTURE_CANDLE", f"candle starting {t} begins after as_of"))
            break
        if end > as_of:
            out.append(Violation("UNFINISHED_CANDLE", f"candle starting {t} had not closed at as_of"))
            break
        if previous is not None and t <= previous:
            out.append(Violation("CANDLE_ORDER", "candles are not strictly increasing in time"))
            break
        previous = t
    if inputs.expiry is not None and inputs.expiry < as_of.astimezone(IST).date():
        out.append(Violation("EXPIRED_CONTRACT", f"expiry {inputs.expiry} is before the signal date"))
    return out


def closed_candles(candles: tuple[dict, ...] | list[dict], as_of: datetime, width_seconds: int) -> list[dict]:
    """Drops the still-forming candle (and anything later than as_of) before the data reaches validation."""
    cutoff = as_of.timestamp()
    return [c for c in candles if c["time"] + width_seconds <= cutoff]
