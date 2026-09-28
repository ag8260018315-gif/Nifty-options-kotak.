"""Kotak Neo market feed on the official SFeed client (kotakneoapi >= 3.0.1).

Read-only by construction: only the SFeed WebSocket classes are imported from the SDK.
`NeoAPI` is never constructed, the SDK never logs in, and there is no order/position code.
Authentication stays with lib.kotak_client (server-side TOTP + MPIN). The SDK feed is
handed the UCC and the `sid` of that session, as documented for SFeedWebSocket(user, auth).

The public surface used by the workers is unchanged: FeedAuthError, KotakSFeed.run_once(),
KotakSFeed.replace_option_tokens(), and the on_message dicts ("auth", "ready", "tick").
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, time as dtime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from neo_api_client.websocket.feed import SFeedIndex, SFeedScrip, SFeedWebSocket, WsToken
from neo_api_client.websocket.feed.exceptions import AuthenticationError as SDKAuthenticationError

from lib.kotak_client import KotakSession
from lib.settings import settings


logger = logging.getLogger(__name__)
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]

IST = ZoneInfo("Asia/Kolkata")
MAX_SUBSCRIPTIONS = 3000
STALL_SECONDS = 45  # no SDK message at all for this long during market hours => force reconnect
WATCHDOG_INTERVAL = 10


class FeedAuthError(RuntimeError):
    pass


def _market_open_now() -> bool:
    local = datetime.now(timezone.utc).astimezone(IST)
    return local.weekday() < 5 and dtime(9, 15) <= local.time() < dtime(15, 30)


def _ws_token(value: str) -> WsToken:
    """'nse_fo|44498' or 'nse_cm|Nifty 50' -> WsToken(exchange_segment, token_or_name)."""
    segment, _, token = value.partition("|")
    if not segment or not token:
        raise ValueError(f"invalid SFeed instrument {value!r}; expected '<segment>|<token>'")
    return WsToken(segment, token)


def _first(message: Any, *names: str) -> Any:
    for name in names:
        value = getattr(message, name, None)
        if value is not None:
            return value
    return None


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


class KotakSFeed:
    def __init__(self, session: KotakSession, on_message: MessageHandler):
        self.session = session
        self.on_message = on_message
        self.authenticated = False
        self.last_tick_at: float | None = None
        self.index_token_count = 0
        # "nse_fo|<token>" strings that the SDK has actually subscribed (not merely requested)
        self.subscribed_option_tokens: set[str] = set()
        self.subscribed_index_tokens: set[str] = set()
        self.tick_counts: dict[str, int] = {"index": 0, "option": 0}
        self._desired_options: set[str] = set()
        self._wake = asyncio.Event()
        self._ws: Any | None = None
        self._last_oi: dict[str, int] = {}
        self._last_message_at = 0.0
        self._divider_reported = False
        self._handler_errors = 0

    # ------------------------------------------------------------------ public API
    async def run_once(self, index_tokens: list[str], option_tokens: list[str]) -> None:
        if len(index_tokens) + len(option_tokens) > MAX_SUBSCRIPTIONS:
            raise ValueError(f"Kotak SFeed limit is {MAX_SUBSCRIPTIONS} subscribed instruments")
        loop = asyncio.get_running_loop()
        self._desired_options = set(option_tokens)
        self.index_token_count = len(index_tokens)
        auth_value = self.session.token if settings.sfeed_auth_field == "token" else self.session.sid
        kwargs: dict[str, Any] = {
            "user": settings.ucc,
            "auth": auth_value,
            "reconnect_delay": 5,
            "max_reconnect_attempts": 5,
            "ping_interval": 20,
        }
        if settings.sfeed_url:  # otherwise the SDK's own default/resolved SFeed endpoint is used
            kwargs["url"] = settings.sfeed_url
        tasks: list[asyncio.Task] = []
        try:
            async with SFeedWebSocket(**kwargs) as ws:
                self._ws = ws
                self.authenticated = True
                self._last_message_at = loop.time()
                logger.info("SFEED_CONNECTED auth_field=%s custom_url=%s", settings.sfeed_auth_field, bool(settings.sfeed_url))
                await self.on_message({"type": "auth", "message_code": 1117, "dividers": {}})
                tasks = [
                    asyncio.create_task(self._reader(ws)),
                    asyncio.create_task(self._subscriber(ws, index_tokens)),
                    asyncio.create_task(self._watchdog()),
                ]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()  # re-raise the first failure, if any
                raise RuntimeError("Kotak SFeed stream ended")
        except SDKAuthenticationError as exc:
            raise FeedAuthError(f"Kotak SFeed authentication failed: {exc}") from exc
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.authenticated = False
            self._ws = None
            self.subscribed_option_tokens = set()
            self.subscribed_index_tokens = set()

    async def replace_option_tokens(self, tokens: list[str]) -> None:
        new_tokens = set(tokens)
        if len(new_tokens) + self.index_token_count > MAX_SUBSCRIPTIONS:
            raise ValueError("Kotak option subscription exceeds limit")
        self._desired_options = new_tokens
        self._wake.set()  # applied by _subscriber, outside the receive loop

    # ------------------------------------------------------------------ internal tasks
    async def _reader(self, ws: Any) -> None:
        loop = asyncio.get_running_loop()
        async for message in ws:
            self._last_message_at = loop.time()
            tick = self._to_tick(message)
            if tick is None:
                continue
            self.last_tick_at = self._last_message_at
            self.tick_counts[tick["kind"]] += 1
            if self.tick_counts[tick["kind"]] == 1:
                logger.info("SFEED_FIRST_TICK kind=%s token=%s ltp=%s", tick["kind"], tick["token"], tick.get("ltp"))
            try:
                if not self._divider_reported:
                    # The SDK already scaled prices with the per-exchange dividers from the auth response.
                    self._divider_reported = True
                    await self.on_message({"type": "auth", "message_code": 1119, "dividers": {"sdk_scaled": 1}})
                await self.on_message({"type": "tick", "tick": tick})
            except asyncio.CancelledError:
                raise
            except Exception:
                self._handler_errors += 1
                if self._handler_errors <= 5 or self._handler_errors % 100 == 0:
                    logger.exception("SFEED_HANDLER_ERROR count=%s", self._handler_errors)

    async def _subscriber(self, ws: Any, index_tokens: list[str]) -> None:
        if index_tokens:
            await ws.subscribe_index([_ws_token(value) for value in index_tokens])
            self.subscribed_index_tokens = set(index_tokens)
            logger.info("SFEED_SUBSCRIBED kind=index count=%s", len(index_tokens))
        while True:
            await self._apply_option_diff(ws)
            await self.on_message({"type": "ready", "subscriptions": len(self.subscribed_index_tokens) + len(self.subscribed_option_tokens)})
            await self._wake.wait()
            self._wake.clear()

    async def _apply_option_diff(self, ws: Any) -> None:
        while self._desired_options != self.subscribed_option_tokens:
            wanted = set(self._desired_options)
            remove = sorted(self.subscribed_option_tokens - wanted)
            add = sorted(wanted - self.subscribed_option_tokens)
            if remove:
                await ws.unsubscribe_scrips([_ws_token(value) for value in remove])
                self.subscribed_option_tokens -= set(remove)
            if add:
                await ws.subscribe_scrips([_ws_token(value) for value in add])
                self.subscribed_option_tokens |= set(add)
            logger.info("SFEED_SUBSCRIBED kind=option added=%s removed=%s total=%s", len(add), len(remove), len(self.subscribed_option_tokens))

    async def _watchdog(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            silent = loop.time() - self._last_message_at
            if silent > STALL_SECONDS and _market_open_now():
                raise RuntimeError(f"Kotak SFeed silent for {silent:.0f}s during market hours")

    # ------------------------------------------------------------------ SDK message -> worker tick
    def _to_tick(self, message: Any) -> dict[str, Any] | None:
        if isinstance(message, SFeedIndex):
            return self._index_tick(message)
        if isinstance(message, SFeedScrip):
            if getattr(message, "exchange_segment", None) == "nse_cm":
                return self._index_tick(message)  # an index subscribed as a plain scrip
            return self._option_tick(message)
        return None  # market status, lite messages, etc. are not used by the dashboard

    @staticmethod
    def _index_tick(message: Any) -> dict[str, Any] | None:
        ltp = _f(_first(message, "last_traded_price", "ltp"))
        if ltp is None or ltp <= 0:
            return None
        tick: dict[str, Any] = {
            "kind": "index",
            "exchange": str(getattr(message, "exchange_segment", "nse_cm")),
            "token": str(getattr(message, "instrument_token", "")),
            "name": str(_first(message, "name", "trading_symbol") or ""),
            "ltp": ltp,
        }
        for key, names in (("open", ("open_price", "open")), ("high", ("high_price", "high")), ("low", ("low_price", "low")), ("close", ("close_price", "close", "prev_close"))):
            value = _f(_first(message, *names))
            if value is not None:
                tick[key] = value
        change = _f(_first(message, "change", "net_change"))
        pct = _f(_first(message, "change_percent", "net_change_percent", "change_pct"))
        if "close" not in tick and change is not None:
            tick["close"] = round(ltp - change, 4)  # derived from the feed's own change value
        if pct is None and change is not None and ltp - change:
            pct = round(change / (ltp - change) * 100, 4)
        if pct is not None:
            tick["change_pct"] = pct
        return tick

    def _option_tick(self, message: Any) -> dict[str, Any] | None:
        ltp = _f(_first(message, "last_traded_price", "ltp"))
        token = str(getattr(message, "instrument_token", ""))
        if ltp is None or not token:
            return None
        oi_raw = _first(message, "open_interest", "oi")
        if oi_raw is not None:
            self._last_oi[token] = int(oi_raw)
        return {
            "kind": "option",
            "exchange": str(getattr(message, "exchange_segment", "nse_fo")),
            "token": token,
            "ltp": ltp,
            "change": _f(_first(message, "net_change", "change")) or 0.0,
            "change_pct": _f(_first(message, "net_change_percent", "change_percent")) or 0.0,
            "volume": int(_first(message, "volume_traded_today", "volume") or 0),
            "oi": self._last_oi.get(token, 0),  # last OI actually received for this token; 0 until one arrives
        }
