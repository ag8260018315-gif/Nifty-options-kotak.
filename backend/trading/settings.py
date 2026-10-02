import os
from dataclasses import dataclass, field

DEFAULT_LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65}  # VERIFY against the exchange circular; override with env


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class TradingSettings:
    mode: str = "PAPER"  # OFF | PAPER | LIVE
    lots: int = 1
    lot_sizes: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LOT_SIZES))
    max_open_positions: int = 1
    max_trades_per_day: int = 5
    max_daily_loss: float = 2000.0  # rupees; entries stop once the day's realised loss reaches this
    slippage_pct: float = 0.5  # paper fills are this much worse than the quoted premium
    squareoff_time: str = "15:15"  # IST; open positions are closed at/after this time
    live_confirmed: bool = False

    @staticmethod
    def from_env() -> "TradingSettings":
        mode = os.environ.get("TRADING_MODE", "PAPER").upper()
        sizes = {s: int(_num(f"TRADING_LOT_SIZE_{s}", DEFAULT_LOT_SIZES[s])) for s in DEFAULT_LOT_SIZES}
        return TradingSettings(
            mode=mode if mode in {"OFF", "PAPER", "LIVE"} else "OFF",
            lots=max(1, int(_num("TRADING_LOTS", 1))),
            lot_sizes=sizes,
            max_open_positions=max(1, int(_num("TRADING_MAX_OPEN", 1))),
            max_trades_per_day=max(1, int(_num("TRADING_MAX_TRADES_PER_DAY", 5))),
            max_daily_loss=max(0.0, _num("TRADING_MAX_DAILY_LOSS", 2000)),
            slippage_pct=min(5.0, max(0.0, _num("TRADING_SLIPPAGE_PCT", 0.5))),
            squareoff_time=os.environ.get("TRADING_SQUAREOFF", "15:15"),
            live_confirmed=os.environ.get("TRADING_LIVE_CONFIRM", "") == "I_ACCEPT_REAL_MONEY_RISK",
        )

    def quantity(self, symbol: str) -> int:
        return self.lots * self.lot_sizes.get(symbol, 0)

    def public(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "live_confirmed"}
