"""The signal model, as a pure function of PAST information.

Both engines call `decide`: research to measure it on history, live to apply it to the present. Because the
function only receives the closes and PCR known at the decision moment, it cannot see the future by construction.

  combined = (w_ema*s_ema + w_rsi*s_rsi + w_oi*s_oi) / sum(w)      each s in [-1, 1], + = bullish
  confidence = round(100 * |combined|)                             a SIGNAL strength, not a win probability
  direction  = CE if combined > 0, PE if combined < 0; a signal exists only if confidence >= minimum_confidence
When PCR is unavailable (research on candles without OI) the OI term is dropped and the weights are renormalised.
"""
from dataclasses import dataclass, field

from shared.config import EngineConfig
from shared.indicators import ema, rsi


@dataclass(frozen=True)
class Decision:
    direction: str | None  # "CE", "PE", or None when below the confidence threshold / not enough data
    confidence: int  # 0-100
    combined: float
    components: dict[str, float | None] = field(default_factory=dict)
    reason: str = ""


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _decide_at(n: int, last: float, fast: float, slow: float, rsi_now: float | None, pcr: float | None, cfg: EngineConfig) -> Decision:
    """The decision given the indicator values at one moment; `n` = closed candles available at that moment."""
    if n < cfg.warmup_candles:
        return Decision(None, 0, 0.0, {}, f"needs {cfg.warmup_candles} closed candles, has {n}")
    if last <= 0 or rsi_now is None:
        return Decision(None, 0, 0.0, {}, "indicators not ready")
    s_ema = _clip(((fast - slow) / last * 100) / cfg.ema_spread_scale_pct)
    s_rsi = _clip((rsi_now - 50.0) / cfg.rsi_scale)
    parts = [(cfg.ema_weight, s_ema), (cfg.rsi_weight, s_rsi)]
    s_oi: float | None = None
    if pcr is not None and pcr > 0:
        s_oi = _clip((pcr - 1.0) / cfg.pcr_scale)  # more put OI than call OI leans bullish
        parts.append((cfg.oi_weight, s_oi))
    total = sum(w for w, _ in parts)
    if total <= 0:
        return Decision(None, 0, 0.0, {}, "no active weights")
    combined = sum(w * s for w, s in parts) / total
    confidence = round(100 * abs(combined))
    components = {"ema": round(s_ema, 4), "rsi": round(s_rsi, 4), "oi": None if s_oi is None else round(s_oi, 4), "rsi_value": round(rsi_now, 2)}
    if confidence < cfg.minimum_confidence or combined == 0:
        return Decision(None, confidence, combined, components, f"confidence {confidence} is below the {cfg.minimum_confidence} minimum")
    return Decision("CE" if combined > 0 else "PE", confidence, combined, components, "")


def decide(closes: list[float], pcr: float | None, cfg: EngineConfig) -> Decision:
    """`closes` = closed-candle closes up to and including the decision moment, oldest first (live path)."""
    if not closes:
        return _decide_at(0, 0.0, 0.0, 0.0, None, pcr, cfg)
    return _decide_at(len(closes), closes[-1], ema(closes, cfg.ema_fast)[-1], ema(closes, cfg.ema_slow)[-1], rsi(closes, cfg.rsi_period)[-1], pcr, cfg)


def decide_series(closes: list[float], pcrs: list[float | None], cfg: EngineConfig) -> list[Decision]:
    """Decision at every bar in one pass (research path). Equivalent to `decide(closes[:i+1], pcrs[i], cfg)` for each i,
    because every indicator value at i depends only on closes[:i+1] (verified by the tests)."""
    fast, slow, rsis = ema(closes, cfg.ema_fast), ema(closes, cfg.ema_slow), rsi(closes, cfg.rsi_period)
    return [_decide_at(i + 1, closes[i], fast[i], slow[i], rsis[i], pcrs[i], cfg) for i in range(len(closes))]
