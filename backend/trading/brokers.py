"""Brokers turn an intent into a fill. PaperBroker is complete; KotakBroker refuses until verified."""
from trading.settings import TradingSettings


class BrokerNotVerified(RuntimeError):
    pass


class PaperBroker:
    """Pretend fills: BUY pays slightly more than the quote, SELL receives slightly less. Nothing leaves this server."""

    name = "PAPER"

    def __init__(self, settings: TradingSettings) -> None:
        self.slip = settings.slippage_pct / 100

    def fill(self, side: str, quote: float) -> float:
        return round(quote * (1 + self.slip) if side == "BUY" else quote * (1 - self.slip), 2)


class KotakBroker:
    """Real orders. Deliberately NOT implemented: the Kotak order-placement endpoint, payload and product/validity
    fields have not been verified against Kotak's current documentation or tested with a real test order, and a
    wrong guess here moves real money. Until that is done, LIVE mode refuses to start."""

    name = "KOTAK"

    def fill(self, side: str, quote: float) -> float:
        raise BrokerNotVerified("Kotak order placement is not verified yet; live orders are disabled.")


def build_broker(settings: TradingSettings):
    if settings.mode == "LIVE":
        if not settings.live_confirmed:
            raise BrokerNotVerified("LIVE needs TRADING_LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK.")
        return KotakBroker()
    return PaperBroker(settings)
