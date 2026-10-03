"""Upstox historical candles -> research storage. READ-ONLY market data: no order code, and the access token is only ever
read from the environment (UPSTOX_ACCESS_TOKEN) and sent to api.upstox.com.

Endpoint (from Upstox's documentation page): GET /v2/historical-candle/{instrument_key}/{interval}/{to_date}[/{from_date}]
with `Authorization: Bearer <token>` and instrument keys like 'NSE_EQ|INE848E01016'. The response layout used here is
data.candles = [[timestamp, open, high, low, close, volume, oi], ...]; `--probe` prints what the API really returns so this
can be checked before any bulk download.
"""
import asyncio
import gzip
import json
import urllib.parse
from datetime import date, datetime, time, timedelta
from typing import Any
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
