"""Company announcements (results, board meetings, dividends, filings) for one stock from the NSE public site.

Best effort: NSE's website API is built for browsers, may change without notice and often refuses cloud servers. When it
does, the answer is `unavailable`, never an invented item. We keep only the title, category, date and the exchange's own
link; we do not copy document text. Cached 15 minutes (5 on failure). Run tools/probe_announcements.py to see what NSE
returns to YOUR server. BSE needs a scrip-code mapping and is not included yet."""
import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from premium import sentiment

PROVIDER = "NSE India"
HOME = "https://www.nseindia.com/"
URL = "https://www.nseindia.com/api/corporate-announcements"
OK_TTL, FAIL_TTL = 900.0, 300.0
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept": "application/json, text/plain, */*",
           "Accept-Language": "en-IN,en;q=0.9", "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"}
IST = ZoneInfo("Asia/Kolkata")
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _first(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _when(text: str) -> str | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def parse(payload: Any, limit: int = 12) -> list[dict[str, Any]]:
    """Items from NSE's response (a list, or {"data": [...]}). Unknown shapes give an empty list. Only https links are kept."""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    items: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        category = _first(row, "desc", "subject", "category")
        detail = _first(row, "attchmntText", "attachmentText", "details", "sm_name")
        link = _first(row, "attchmntFile", "attachmentFile", "link")
        title = (f"{category}: {detail}" if category and detail else category or detail)[:300]
        if not title:
            continue
        items.append({"title": title, "category": category or None, "published_at": _when(_first(row, "an_dt", "sort_date", "date")),
                      "link": link if link.lower().startswith("https://") else None, "sentiment": sentiment.read(title)})
        if len(items) >= limit:
            break
    return items


async def fetch(symbol: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    cached = _cache.get(symbol)
    if cached and time.monotonic() < cached[0]:
        return cached[1]
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        async with (httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) if client is None else _Reuse(client)) as c:
            await c.get(HOME)  # NSE hands out a session cookie on the home page and refuses API calls without it
            response = await c.get(URL, params={"index": "equities", "symbol": symbol})
            response.raise_for_status()
            items = parse(response.json())
        result = {"status": "ok", "provider": PROVIDER, "items": items, "summary": sentiment.summarize(items), "fetched_at": stamp}
        ttl = OK_TTL
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
        result = {"status": "unavailable", "provider": PROVIDER, "items": [], "summary": sentiment.summarize([]), "fetched_at": stamp}
        ttl = FAIL_TTL
    _cache[symbol] = (time.monotonic() + ttl, result)
    return result


class _Reuse:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self.client

    async def __aexit__(self, *exc: object) -> None:
        return None
