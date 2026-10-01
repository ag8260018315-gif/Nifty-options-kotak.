"""Background loop: evaluates each index on current data, stores actionable signals, resolves outcomes."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from live import store
from live.engine import generate
from live.inputs import LiveInputs
from live.outcomes import resolve
from shared.config import EngineConfig, load_config

logger = logging.getLogger(__name__)
SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
INTERVAL_SECONDS = 5

InputsProvider = Callable[[str], Awaitable[LiveInputs | None]]


class LiveSignalRunner:
    def __init__(self, live_db: Any, provider: InputsProvider) -> None:
        self.live_db, self.provider = live_db, provider
        self.latest: dict[str, dict[str, Any]] = {}

    async def evaluate(self, symbol: str, persist: bool = True) -> dict[str, Any]:
        cfg = load_config()  # re-read every cycle: a new config.json takes effect without a restart
        inputs = await self.provider(symbol)
        if inputs is None:
            return self._waiting(symbol, cfg)
        now = datetime.now(timezone.utc)
        live = inputs.source == "KOTAK_NEO"
        signal = generate(inputs, cfg, now=now, require_live=live)  # demo data computes but is flagged simulated and never stored
        if persist and live:
            await self._maintain(symbol, signal, inputs, cfg)
        self.latest[symbol] = signal
        return signal

    async def _maintain(self, symbol: str, signal: dict[str, Any], inputs: LiveInputs, cfg: EngineConfig) -> None:
        for open_signal in await store.open_signals(self.live_db, symbol):
            outcome = resolve(open_signal, inputs)
            if outcome:
                await store.save_outcome(self.live_db, outcome)
        if signal["action"] == "NO SIGNAL":
            return
        last = await store.last_signal_time(self.live_db, symbol)
        if last is not None:
            last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            if (inputs.as_of - last).total_seconds() < cfg.signal_cooldown_seconds:
                signal["reasons"].append(f"Cooldown: last signal was under {cfg.signal_cooldown_seconds}s ago; not stored again.")
                signal["cooldown"] = True
                return
        await store.save_signal(self.live_db, signal, inputs, cfg)

    @staticmethod
    def _waiting(symbol: str, cfg: EngineConfig) -> dict[str, Any]:
        from live.engine import _historical

        return {"label": "LIVE SIGNAL", "symbol": symbol, "action": "NO SIGNAL", "direction": None, "confidence": 0, "confidence_label": "Current signal confidence",
                "historical_validation": _historical(cfg), "strike": None, "risk": None, "components": {}, "alternatives": [],
                "reasons": ["Waiting for live data."], "data_status": {"feed_state": "WAITING", "ok": False, "violations": [], "candles_used": 0, "candles_required": cfg.warmup_candles},
                "simulated": False, "as_of": datetime.now(timezone.utc).isoformat()}

    async def run(self) -> None:
        while True:
            for symbol in SYMBOLS:
                try:
                    await self.evaluate(symbol)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001  a signal problem must never disturb the feed
                    logger.warning("LIVE_SIGNAL_ERROR symbol=%s kind=%s", symbol, type(exc).__name__)
            await asyncio.sleep(INTERVAL_SECONDS)
