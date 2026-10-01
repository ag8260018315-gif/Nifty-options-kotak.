"""Pure indicator math. Every value at index i depends only on inputs[0..i] (never on later items)."""


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average, seeded with the first value. out[i] uses values[:i+1] only."""
    if period < 1:
        raise ValueError("period must be >= 1")
    k = 2.0 / (period + 1)
    out: list[float] = []
    for value in values:
        out.append(value if not out else value * k + out[-1] * (1 - k))
    return out


def rsi(values: list[float], period: int) -> list[float | None]:
    """Wilder RSI. None until `period` price changes exist. out[i] uses values[:i+1] only."""
    if period < 1:
        raise ValueError("period must be >= 1")
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
