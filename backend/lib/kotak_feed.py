import asyncio
import json
import logging
import struct
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from lib.kotak_client import KotakSession
from lib.settings import settings


logger = logging.getLogger(__name__)
MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


def websocket_url(feed_url: str) -> str:
    return feed_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)


def packet_frames(frame: bytes) -> list[bytes]:
    packets: list[bytes] = []
    offset = 0
    while offset + 2 <= len(frame):
        packet_length = struct.unpack_from("<H", frame, offset)[0]
        if packet_length < 9 or offset + packet_length > len(frame):
            break
        packets.append(frame[offset : offset + packet_length])
        offset += packet_length
    return packets


class KotakSFeed:
    """Current native_batch SFeed client; it never uses the deprecated HS socket."""

    def __init__(self, session: KotakSession, on_message: MessageHandler):
        self.session = session
        self.on_message = on_message
        self.dividers: dict[str, int] = {}
        self.symbols: dict[str, str] = {}
        self.last_tick_at: float | None = None

    async def run(self, tokens: list[str]) -> None:
        if not self.session.feed_url:
            raise RuntimeError("tradeApiValidate did not return feedUrl")
        if len(tokens) > 3000:
            raise ValueError("Kotak SFeed limit is 3000 subscribed instruments")
        delay = 1
        while True:
            try:
                await self._run_once(tokens)
                delay = 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Kotak SFeed disconnected; retrying with backoff")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _run_once(self, tokens: list[str]) -> None:
        async with websockets.connect(websocket_url(self.session.feed_url), ping_interval=20, ping_timeout=10) as socket:
            await socket.send(json.dumps({
                "user": settings.ucc,
                "auth": self.session.token,
                "format": "native_batch",
                "source": "NEOTRADEAPI",
                "sdk version": 1.1,
                "sdk_date": "",
            }))
            subscribed = False
            async for message in socket:
                if isinstance(message, str):
                    authenticated = await self._handle_control(json.loads(message))
                    if authenticated and not subscribed:
                        await socket.send(json.dumps({
                            "event": "subscribeScrips",
                            "inputtoken": ",".join(tokens),
                            "ack_symbol": True,
                        }))
                        subscribed = True
                else:
                    for packet in packet_frames(bytes(message)):
                        await self.on_message({"type": "binary_packet", "packet": packet})
                        self.last_tick_at = asyncio.get_running_loop().time()

    async def _handle_control(self, message: dict[str, Any]) -> bool:
        code = message.get("message_code")
        if code in (1117, 1119):
            exchanges = message.get("exchanges", {})
            if isinstance(exchanges, dict):
                self.dividers = {name: int(value.get("divider", 100)) for name, value in exchanges.items() if isinstance(value, dict)}
            await self.on_message({"type": "auth", "message_code": code, "dividers": self.dividers})
            return True
        elif code == 1120:
            raise RuntimeError("Kotak SFeed authentication failed")
        elif code == 1109:
            data = message.get("data", {})
            if isinstance(data, dict):
                for token, details in data.items():
                    if isinstance(details, dict) and details.get("trading_symbols"):
                        self.symbols[token] = str(details["trading_symbols"])
            await self.on_message({"type": "subscription", "message_code": code, "symbols": self.symbols})
        return False