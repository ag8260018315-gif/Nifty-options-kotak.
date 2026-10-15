"""Upstox historical candles -> research storage. READ-ONLY market data: no order code, and the access token is only ever
read from the environment (UPSTOX_ACCESS_TOKEN) and sent to api.upstox.com.

Endpoint (from Upstox's documentation page): GET /v2/historical-candle/{instrument_key}/{interval}/{to_date}[/{from_date}]
with `Authorization: Bearer <token>` and instrument keys like 'NSE_EQ|INE848E01016'. The response layout used here is
data.candles = [[timestamp, open, high, low, close, volume, oi], ...]; `--probe` prints what the API really returns so this
can be checked before any bulk download.
"""
import asyncio
import codecs
import gzip
import json
import urllib.parse
import zlib
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.upstox.com/v2"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
IST = ZoneInfo("Asia/Kolkata")
OPEN_T, CLOSE_T = time(9, 15), time(15, 30)


class UpstoxError(RuntimeError):
    pass


def parse_candles(payload: dict[str, Any], session_only: bool = True) -> list[dict[str, Any]]:
    """Bars (oldest first) from an Upstox response. With session_only (intraday candles) bars outside the NSE session and on weekends
    are dropped; daily candles (session_only=False) keep their midnight timestamp. Rows with missing prices are skipped."""
    rows = ((payload or {}).get("data") or {}).get("candles") or []
    bars: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            stamp = datetime.fromisoformat(str(row[0])).astimezone(IST)
            o, h, l, c = (float(row[i]) for i in range(1, 5))
            v = int(float(row[5])) if len(row) > 5 and row[5] is not None else 0
        except (TypeError, ValueError, IndexError):
            continue
        if min(o, h, l, c) <= 0 or (session_only and (stamp.weekday() >= 5 or not (OPEN_T <= stamp.time() < CLOSE_T))):
            continue
        bars[int(stamp.timestamp())] = {"time": int(stamp.timestamp()), "open": o, "high": h, "low": l, "close": c, "volume": v}
    return [bars[k] for k in sorted(bars)]


def symbol_keys(instruments: list[dict[str, Any]], wanted: list[str]) -> dict[str, str]:
    """symbol -> instrument_key for NSE cash-market equities, from Upstox's public instrument master."""
    wanted_set, found = set(wanted), {}
    for row in instruments:
        symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or "").upper()
        if symbol not in wanted_set or symbol in found:
            continue
        if str(row.get("segment", "NSE_EQ")) != "NSE_EQ" or str(row.get("instrument_type", "EQ")) not in {"EQ", ""}:
            continue
        if row.get("instrument_key"):
            found[symbol] = str(row["instrument_key"])
    return found


def directory_item(row: dict[str, Any]) -> dict[str, str] | None:
    """{symbol, name, key} when `row` is an NSE cash-market company share, else None. ETFs, bonds and other instruments are left out:
    with an ISIN given, only company shares (ISIN starting INE) are kept."""
    symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or "").strip().upper()
    if not symbol or not row.get("instrument_key"):
        return None
    if str(row.get("segment", "NSE_EQ")) != "NSE_EQ" or str(row.get("instrument_type", "EQ")) not in {"EQ", ""}:
        return None
    isin = str(row.get("isin") or "")
    if isin and not isin.startswith("INE"):
        return None
    return {"symbol": symbol, "name": str(row.get("name") or row.get("short_name") or symbol), "key": str(row["instrument_key"])}


def directory_items(instruments: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """One entry per symbol for every company share in Upstox's public instrument master (the first row of a symbol wins)."""
    items: dict[str, dict[str, str]] = {}
    for row in instruments:
        item = directory_item(row)
        if item and item["symbol"] not in items:
            items[item["symbol"]] = item
    return list(items.values())


def iter_json_array(chunks: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Objects of a top-level JSON array, one at a time, from text chunks of any size. Memory stays small however long the array is
    (the NSE instrument file has ~100,000 rows and is far too big to load whole on a small server)."""
    decoder, buffer = json.JSONDecoder(), ""
    for chunk in chunks:
        buffer += chunk
        pos = 0
        while True:
            while pos < len(buffer) and buffer[pos] in " \r\n\t,[":
                pos += 1
            if pos >= len(buffer) or buffer[pos] == "]":
                break
            try:
                row, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                break  # the object is cut off at the end of this chunk; wait for more text
            if isinstance(row, dict):
                yield row
            pos = end
        buffer = buffer[pos:]


def _text_chunks(raw: bytes, size: int = 1 << 16) -> Iterator[str]:
    """Decoded text of a gzip (or plain) response, a slice at a time."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    if raw[:2] == b"\x1f\x8b":
        inflater = zlib.decompressobj(zlib.MAX_WBITS | 16)
        for i in range(0, len(raw), size):
            yield decoder.decode(inflater.decompress(raw[i:i + size]))
        yield decoder.decode(inflater.flush(), final=True)
    else:
        for i in range(0, len(raw), size):
            yield decoder.decode(raw[i:i + size])
        yield decoder.decode(b"", final=True)


async def stream_directory(client: httpx.AsyncClient, url: str = INSTRUMENTS_URL) -> list[dict[str, str]]:
    """Every NSE company share from Upstox's public list, parsed in a stream so memory stays small."""
    response = await client.get(url, timeout=90)
    response.raise_for_status()
    return directory_items(iter_json_array(_text_chunks(response.content)))


def windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """[start, end] split into consecutive chunks of at most `days` days (inclusive)."""
    out, cursor = [], start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=days - 1))
        out.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return out


async def load_instruments(client: httpx.AsyncClient, url: str = INSTRUMENTS_URL) -> list[dict[str, Any]]:
    response = await client.get(url, timeout=60)
    response.raise_for_status()
    raw = response.content
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass  # already plain JSON
    return json.loads(raw)


async def fetch_range(client: httpx.AsyncClient, token: str, key: str, start: date, end: date, interval: str = "1minute", retries: int = 3) -> dict[str, Any]:
    """Raw response JSON for one window. 401 means the access token is missing or expired; 429/5xx are retried with a pause."""
    url = f"{BASE}/historical-candle/{urllib.parse.quote(key, safe='')}/{interval}/{end.isoformat()}/{start.isoformat()}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    for attempt in range(retries + 1):
        response = await client.get(url, headers=headers, timeout=30)
        if response.status_code == 401:
            raise UpstoxError("Upstox rejected the access token (401). It is missing or has expired; get a new one.")
        if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            await asyncio.sleep(2 * (attempt + 1))
            continue
        if response.status_code >= 400:
            raise UpstoxError(f"Upstox returned {response.status_code} for {key}: {response.text[:200]}")
        return response.json()
    raise UpstoxError("unreachable")
