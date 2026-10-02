"""Loop: manage open positions first (exits), then consider the latest live signal for a new entry."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from live.inputs import LiveInputs
from trading import engine, store
from trading.brokers import BrokerNotVerified
from trading.settings import TradingSettings

logger = logging.getLogger(__name__)
SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
INTERVAL_SECONDS = 3


def _quote(inputs: LiveInputs, strike: int, direction: str) -> float | None:
    row = next((r for r in inputs.chain if r.strike == strike), None)
    leg = None if row is None else (row.call if direction == "CE" else row.put)
    return leg.ltp if leg and leg.ltp > 0 else None


class AutoTrader:
    def __init__(self, live_db: Any, provider: Callable[[str], Awaitable[LiveInputs | None]], latest_signals: dict[str, dict[str, Any]], broker: Any, settings: TradingSettings) -> None:
        self.db, self.provider, self.latest, self.broker, self.settings = live_db, provider, latest_signals, broker, settings

    async def step(self, symbol: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        inputs = await self.provider(symbol)
        if inputs is None or inputs.source != "KOTAK_NEO":
            return
        killed, _ = await store.is_killed(self.db)
        for position in [p for p in await store.open_trades(self.db) if p["symbol"] == symbol]:
            quote = _quote(inputs, position["strike"], position["direction"])
            if quote is None:
                continue
            reason = engine.exit_reason(position, quote, now, self.settings, killed)
            if reason:
                await store.save_trade(self.db, engine.close_position(position, self.broker.fill("SELL", quote), reason, now))
        signal = self.latest.get(symbol)
        if not signal:
            return
        day = await store.day_summary(self.db, now)
        if engine.entry_decision(signal, day, now, self.settings, killed) is not None:
            return
        quote = _quote(inputs, signal["strike"]["strike"], signal["direction"])
        if quote is None:
            return
        try:
            fill = self.broker.fill("BUY", quote)
            realised, open_cost = await store.account_totals(self.db)
            acct = engine.account(self.settings.start_capital, realised, open_cost)
            if not engine.can_afford(self.settings.start_capital, acct["available"], fill, self.settings.quantity(symbol)):
                return  # not enough free practice cash for this trade
        except BrokerNotVerified as exc:
            await store.set_killed(self.db, True, str(exc))  # fail safe: stop trading rather than guess
            logger.error("AUTO_TRADER_HALTED %s", exc)
            return
        await store.save_trade(self.db, engine.open_position(signal, fill, now, self.settings, self.broker.name))

    async def run(self) -> None:
        while True:
            for symbol in SYMBOLS:
                try:
                    await self.step(symbol)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001  never disturb the feed
                    logger.warning("AUTO_TRADER_ERROR symbol=%s kind=%s", symbol, type(exc).__name__)
            await asyncio.sleep(INTERVAL_SECONDS)
