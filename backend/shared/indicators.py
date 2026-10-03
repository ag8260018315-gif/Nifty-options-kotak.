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


def sma(values: list[float], period: int) -> list[float | None]:
    """Simple moving average. None until `period` values exist. out[i] uses values[:i+1] only."""
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    """(macd line, signal line, histogram). Causal like ema."""
    line = [a - b for a, b in zip(ema(values, fast), ema(values, slow))]
    sig = ema(line, signal)
    return line, sig, [m - s for m, s in zip(line, sig)]


def bollinger(values: list[float], period: int = 20, k: float = 2.0) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """(middle, upper, lower) bands from a rolling mean and population standard deviation."""
    mid = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)
    for i, m in enumerate(mid):
        if m is None:
            continue
        window = values[i - period + 1 : i + 1]
        sd = (sum((x - m) ** 2 for x in window) / period) ** 0.5
        upper[i], lower[i] = m + k * sd, m - k * sd
    return mid, upper, lower


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    """Average true range (Wilder smoothing). None until `period` bars exist."""
    out: list[float | None] = [None] * len(closes)
    trs = []
    for i in range(len(closes)):
        prev = closes[i - 1] if i else closes[i]
        trs.append(max(highs[i] - lows[i], abs(highs[i] - prev), abs(lows[i] - prev)))
    if len(trs) < period:
        return out
    value = sum(trs[:period]) / period
    out[period - 1] = value
    for i in range(period, len(trs)):
        value = (value * (period - 1) + trs[i]) / period
        out[i] = value
    return out
