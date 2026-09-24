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
EXCHANGE_IDS = {1: "nse_cm", 2: "nse_fo", 3: "cde_fo", 4: "nse_com", 5: "bse_cm", 6: "bse_fo", 7: "bse_cd", 8: "bse_co", 9: "mcx_fo", 10: "ncd_co"}


class FeedAuthError(RuntimeError):
    pass


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


def _price(raw: int, divider: int) -> float:
    return round(raw / max(divider, 1), 4)


def _text(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def decode_packet(packet: bytes, dividers: dict[str, int]) -> dict[str, Any] | None:
    if len(packet) < 9:
        return None
    packet_length, message_code = struct.unpack_from("<HH", packet, 0)
    if packet_length != len(packet):
        return None
    exchange_id = struct.unpack_from("<b", packet, 4)[0]
    level = packet[5]
    exchange = EXCHANGE_IDS.get(exchange_id, "unknown")
    divider = int(dividers.get(exchange, 100))

    if message_code == 7207 and len(packet) >= 87:
        return {
            "kind": "index",
            "exchange": exchange,
            "level": level,
            "token": str(struct.unpack_from("<I", packet, 9)[0]),
            "open": _price(struct.unpack_from("<i", packet, 13)[0], divider),
            "close": _price(struct.unpack_from("<i", packet, 17)[0], divider),
            "high": _price(struct.unpack_from("<i", packet, 21)[0], divider),
            "low": _price(struct.unpack_from("<i", packet, 25)[0], divider),
            "ltp": _price(struct.unpack_from("<i", packet, 29)[0], divider),
            "last_trade_time_raw": struct.unpack_from("<Q", packet, 33)[0],
            "change_pct": round(struct.unpack_from("<i", packet, 49)[0] / 100, 4),
            "name": _text(packet[66:87]),
        }

    if message_code != 7208:
        return None
    if level == 1 and len(packet) >= 54:
        return {
            "kind": "option",
            "exchange": exchange,
            "level": level,
            "token": str(struct.unpack_from("<I", packet, 9)[0]),
            "last_trade_time_raw": struct.unpack_from("<q", packet, 13)[0],
            "ltp": _price(struct.unpack_from("<I", packet, 21)[0], divider),
            "ltq": struct.unpack_from("<q", packet, 25)[0],
            "close_raw": struct.unpack_from("<I", packet, 33)[0],
            "change_pct": round(struct.unpack_from("<i", packet, 37)[0] / 100, 4),
            "change": _price(struct.unpack_from("<i", packet, 41)[0], divider),
            "oi": 0,
        }
    if level not in {2, 4, 8} or len(packet) < 144:
        return None
    buy_count, sell_count = struct.unpack_from("<II", packet, 89)
    available_rows = max(0, (len(packet) - 144) // 16)
    if level == 4:
        buy_count, sell_count = 1, 1
    total_rows = min(int(buy_count + sell_count), available_rows)
    depth: list[dict[str, Any]] = []
    for index in range(total_rows):
        offset = 144 + index * 16
        depth.append(
            {
                "qty": struct.unpack_from("<q", packet, offset)[0],
                "price": _price(struct.unpack_from("<i", packet, offset + 8)[0], divider),
                "orders": struct.unpack_from("<i", packet, offset + 12)[0],
            }
        )
    return {
        "kind": "option",
        "exchange": exchange,
        "level": level,
        "token": str(struct.unpack_from("<I", packet, 9)[0]),
        "total_buy_qty": struct.unpack_from("<q", packet, 13)[0],
        "total_sell_qty": struct.unpack_from("<q", packet, 21)[0],
        "volume": struct.unpack_from("<q", packet, 29)[0],
        "last_trade_time_raw": struct.unpack_from("<q", packet, 37)[0],
        "open": _price(struct.unpack_from("<I", packet, 53)[0], divider),
        "close": _price(struct.unpack_from("<I", packet, 57)[0], divider),
        "high": _price(struct.unpack_from("<I", packet, 61)[0], divider),
        "low": _price(struct.unpack_from("<I", packet, 65)[0], divider),
        "ltp": _price(struct.unpack_from("<I", packet, 69)[0], divider),
        "ltq": struct.unpack_from("<q", packet, 73)[0],
        "average_price": _price(struct.unpack_from("<I", packet, 81)[0], divider),
        "change_pct": round(struct.unpack_from("<i", packet, 99)[0] / 100, 4),
        "oi": struct.unpack_from("<I", packet, 103)[0],
        "change": _price(struct.unpack_from("<i", packet, 115)[0], divider),
        "buy_depth": depth[: int(buy_count)],
        "sell_depth": depth[int(buy_count) : int(buy_count + sell_count)],
    }


class KotakSFeed:
    """Current native_batch SFeed client; it never uses the deprecated HS socket."""

    def __init__(self, session: KotakSession, on_message: MessageHandler):
        self.session = session
        self.on_message = on_message
        self.dividers: dict[str, int] = {}
        self.symbols: dict[str, str] = {}
        self.last_tick_at: float | None = None
        self.authenticated = False
        self.option_tokens: set[str] = set()
        self.socket: Any | None = None

    async def run_once(self, index_tokens: list[str], option_tokens: list[str]) -> None:
        if not self.session.feed_url:
            raise RuntimeError("tradeApiValidate did not return feedUrl")
        if len(index_tokens) + len(option_tokens) > 3000:
            raise ValueError("Kotak SFeed limit is 3000 subscribed instruments")
        async with websockets.connect(websocket_url(self.session.feed_url), ping_interval=20, ping_timeout=10) as socket:
            self.socket = socket
            await socket.send(json.dumps({
                "user": settings.ucc,
                "auth": self.session.token,
                "format": "native_batch",
                "source": "NEOTRADEAPI",
                "sdk version": 1.1,
                "sdk_date": "",
            }))
            subscribed = False
            try:
                async for message in socket:
                    if isinstance(message, str):
                        authenticated = await self._handle_control(json.loads(message))
                        if authenticated and not subscribed:
                            if index_tokens:
                                await socket.send(json.dumps({"event": "subscribeIndices", "inputtoken": ",".join(index_tokens)}))
                            self.option_tokens = set(option_tokens)
                            if option_tokens:
                                await socket.send(json.dumps({"event": "subscribeScrips", "inputtoken": ",".join(option_tokens), "ack_symbol": True}))
                            subscribed = True
                            await self.on_message({"type": "ready", "subscriptions": len(index_tokens) + len(option_tokens)})
                    else:
                        for packet in packet_frames(bytes(message)):
                            decoded = decode_packet(packet, self.dividers)
                            if decoded:
                                await self.on_message({"type": "tick", "tick": decoded})
                                self.last_tick_at = asyncio.get_running_loop().time()
            finally:
                self.authenticated = False
                self.socket = None

    async def replace_option_tokens(self, tokens: list[str]) -> None:
        new_tokens = set(tokens)
        if len(new_tokens) > 2999:
            raise ValueError("Kotak option subscription exceeds limit")
        if not self.socket or not self.authenticated or new_tokens == self.option_tokens:
            self.option_tokens = new_tokens
            return
        old_tokens = self.option_tokens
        if old_tokens:
            await self.socket.send(json.dumps({"event": "unsubscribeScrips", "inputtoken": ",".join(sorted(old_tokens))}))
        if new_tokens:
            await self.socket.send(json.dumps({"event": "subscribeScrips", "inputtoken": ",".join(sorted(new_tokens)), "ack_symbol": True}))
        self.option_tokens = new_tokens
        await self.on_message({"type": "ready", "subscriptions": 1 + len(new_tokens)})

    async def _handle_control(self, message: dict[str, Any]) -> bool:
        code = message.get("message_code")
        if code in (1117, 1119):
            exchanges = message.get("exchanges", {})
            if isinstance(exchanges, dict):
                self.dividers = {name: int(value.get("divider", 100)) for name, value in exchanges.items() if isinstance(value, dict)}
            await self.on_message({"type": "auth", "message_code": code, "dividers": self.dividers})
            if code == 1117:
                self.authenticated = True
                return True
            return False
        elif code == 1120:
            raise FeedAuthError("Kotak SFeed authentication failed")
        elif message.get("format") == "native_fallback":
            raise RuntimeError("Kotak SFeed returned native_fallback instead of native_batch")
        elif code == 1109:
            data = message.get("data", {})
            if isinstance(data, dict):
                for token, details in data.items():
                    if isinstance(details, dict) and details.get("trading_symbols"):
                        self.symbols[token] = str(details["trading_symbols"])
            await self.on_message({"type": "subscription", "message_code": code, "symbols": self.symbols})
        return False