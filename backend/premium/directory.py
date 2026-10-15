"""Every NSE cash-market stock the app knows by name, not only the ~129 on the live feed.

Stored as ONE document (`stock_directory`, id `nse_eq`) with parallel arrays, so a few thousand stocks take about 150 KB. It is filled by
tools/import_upstox_all_stocks.py from Upstox's public instrument list. Until that has run the directory falls back to the live list, so
search never comes back empty and nothing is invented. A stock in the directory but off the live feed gets end-of-day data only."""
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from premium.stockinfo import INFO

COLLECTION = "stock_directory"
DOC_ID = "nse_eq"
TTL = 600.0
EMPTY_TTL = 30.0  # an empty directory is re-read soon, so a fresh import shows up quickly
SYMBOL_OK = re.compile(r"^[A-Z0-9&\-]{1,20}$")


@dataclass
class Directory:
    symbols: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    loaded: bool = False  # True when it came from the imported list, False for the live-list fallback
    updated_at: str | None = None
    source: str | None = None
    _index: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._index = {s: i for i, s in enumerate(self.symbols)}

    def __len__(self) -> int:
        return len(self.symbols)

    def get(self, symbol: str) -> dict[str, str] | None:
        i = self._index.get(symbol)
        return None if i is None else {"symbol": symbol, "name": self.names[i]}


def clean(items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(symbols, names) sorted by symbol: valid symbols only, one entry per symbol, a missing name falls back to the symbol."""
    seen: dict[str, str] = {}
    for item in items:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not SYMBOL_OK.match(symbol) or symbol in seen:
            continue
        seen[symbol] = " ".join(str(item.get("name") or "").split())[:80] or symbol
    ordered = sorted(seen)
    return ordered, [seen[s] for s in ordered]


def fallback() -> Directory:
    symbols = sorted(INFO)
    return Directory(symbols=symbols, names=[INFO[s][0] for s in symbols])


def pack(items: list[dict[str, Any]], source: str) -> dict[str, Any]:
    symbols, names = clean(items)
    return {"_id": DOC_ID, "n": len(symbols), "source": source, "updated_at": datetime.now(timezone.utc).isoformat(), "symbols": symbols, "names": names}


def unpack(doc: dict[str, Any] | None) -> Directory:
    if not doc or not doc.get("symbols") or len(doc["symbols"]) != len(doc.get("names", [])):
        return fallback()
    return Directory(symbols=list(doc["symbols"]), names=list(doc["names"]), loaded=True, updated_at=doc.get("updated_at"), source=doc.get("source"))


async def save(db: Any, items: list[dict[str, Any]], source: str) -> int:
    doc = pack(items, source)
    await db[COLLECTION].replace_one({"_id": DOC_ID}, doc, upsert=True)
    _cache.clear()
    return doc["n"]


_cache: dict[str, tuple[float, Directory]] = {}


async def load(db: Any) -> Directory:
    cached = _cache.get(DOC_ID)
    if cached and time.monotonic() - cached[0] < (TTL if cached[1].loaded else EMPTY_TTL):
        return cached[1]
    try:
        directory = unpack(await db[COLLECTION].find_one({"_id": DOC_ID}))
    except Exception:  # noqa: BLE001  a storage problem must not break the stock list
        directory = fallback()
    _cache[DOC_ID] = (time.monotonic(), directory)
    return directory


def search(directory: Directory, query: str, limit: int = 20) -> list[dict[str, str]]:
    """Best matches first: exact symbol, symbol prefix, a name word starting with the text, symbol contains, name contains. With no
    text, the first `limit` symbols alphabetically."""
    q = " ".join(query.upper().split())
    if not q:
        return [{"symbol": s, "name": n} for s, n in zip(directory.symbols[:limit], directory.names[:limit])]
    ranked: list[tuple[int, str, str]] = []
    for symbol, name in zip(directory.symbols, directory.names):
        upper = name.upper()
        if symbol == q:
            rank = 0
        elif symbol.startswith(q):
            rank = 1
        elif any(word.startswith(q) for word in re.split(r"[\s\-&.,()]+", upper) if word) or upper.startswith(q):
            rank = 2
        elif q in symbol:
            rank = 3
        elif q in upper:
            rank = 4
        else:
            continue
        ranked.append((rank, symbol, name))
    ranked.sort(key=lambda r: (r[0], len(r[1]), r[1]))
    return [{"symbol": s, "name": n} for _, s, n in ranked[:limit]]
