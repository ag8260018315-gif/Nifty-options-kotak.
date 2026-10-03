"""Recent headlines for a stock from Google News RSS (public feed, no key). Headline, source, time and a link only: we
do not copy article text, and we do not judge whether a story is true. Results are cached for 10 minutes per symbol.
Terms for commercial redistribution of headlines are the owner's to check; swap this provider if needed."""
import asyncio
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

PROVIDER = "Google News"
OK_TTL, FAIL_TTL = 600.0, 120.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def parse_rss(xml_text: str, limit: int = 4) -> list[dict[str, Any]]:
    """Items from an RSS document. Only http(s) links are kept; titles are plain text."""
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        source = (node.findtext("source") or "").strip()
        if not title or not link.lower().startswith(("http://", "https://")):
            continue
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        published = None
        raw = node.findtext("pubDate")
        if raw:
            try:
                published = parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                published = None
        items.append({"title": title[:240], "link": link, "source": source or None, "published_at": published})
        if len(items) >= limit:
            break
    return items


async def headlines(symbol: str, limit: int = 4, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    cached = _cache.get(symbol)
    if cached and time.monotonic() < cached[0]:
        return cached[1]
    query = quote_plus(f"{symbol} share NSE stock when:7d")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=5, headers={"User-Agent": "Mozilla/5.0 (compatible; NiftyOptionsDesk)"}) as c:
                response = await c.get(url)
        else:
            response = await client.get(url)
        response.raise_for_status()
        result = {"status": "ok", "provider": PROVIDER, "items": parse_rss(response.text, limit), "fetched_at": datetime.now(timezone.utc).isoformat()}
        ttl = OK_TTL
    except (httpx.HTTPError, ET.ParseError, asyncio.TimeoutError):
        result = {"status": "unavailable", "provider": PROVIDER, "items": [], "fetched_at": datetime.now(timezone.utc).isoformat()}
        ttl = FAIL_TTL
    _cache[symbol] = (time.monotonic() + ttl, result)
    return result
