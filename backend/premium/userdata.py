"""Per-user premium data: watchlists and saved chart layouts. One document per user, keyed by email. Server-side, so they follow the
user across devices. Inputs are validated and bounded; a user can only ever read and write their own document."""
import re
import time
from typing import Any

from fastapi import HTTPException

WATCHLISTS, LAYOUTS = "premium_watchlists", "premium_layouts"
MAX_LISTS, MAX_LAYOUTS, MAX_NAME = 10, 10, 30
NAME_RE = re.compile(r"^[\w &\-]{1,30}$")  # no "." or "/": names are stored as keys and travel inside a URL path
PANES = {"rsi", "macd", "none"}
INTERVALS = {1, 5, 15, 30, 60, 240, 1440, 10080, 43200}
FLAGS = ("ema", "bb", "vwap", "levels", "patterns", "setup")


def owner_key(user: dict[str, Any]) -> str:
    return (user.get("email") or "owner@local").lower()


def clean_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name) or not any(ch.isalnum() for ch in name):
        raise HTTPException(status_code=422, detail="Names need a letter or number and can use spaces and & - _ (up to 30 characters).")
    return name


async def get_lists(db: Any, key: str) -> dict[str, list[str]]:
    doc = await db[WATCHLISTS].find_one({"_id": key})
    return dict((doc or {}).get("lists", {}))


async def put_list(db: Any, key: str, name: str, symbols: list[str], universe: set[str]) -> dict[str, list[str]]:
    name = clean_name(name)
    seen: list[str] = []
    for s in symbols:
        s = str(s).upper().strip()
        if s not in universe:
            raise HTTPException(status_code=422, detail=f"{s} is not a supported stock.")
        if s not in seen:
            seen.append(s)
    lists = await get_lists(db, key)
    if name not in lists and len(lists) >= MAX_LISTS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_LISTS} watchlists.")
    lists[name] = seen
    await db[WATCHLISTS].replace_one({"_id": key}, {"_id": key, "lists": lists, "updated_at": time.time()}, upsert=True)
    return lists


async def patch_list(db: Any, key: str, name: str, add: list[str], remove: list[str], universe: set[str]) -> dict[str, list[str]]:
    """Add and/or remove symbols on the list as it is now on the server (creating it if needed). Unlike put_list this can never wipe
    out symbols the caller did not know about, e.g. when the same account is open on two devices."""
    name = clean_name(name)
    wanted_add = [str(s).upper().strip() for s in add]
    for s in wanted_add:
        if s not in universe:
            raise HTTPException(status_code=422, detail=f"{s} is not a supported stock.")
    drop = {str(s).upper().strip() for s in remove}
    lists = await get_lists(db, key)
    if name not in lists and len(lists) >= MAX_LISTS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_LISTS} watchlists.")
    current = [s for s in lists.get(name, []) if s not in drop]
    for s in wanted_add:
        if s not in current:
            current.append(s)
    lists[name] = current
    await db[WATCHLISTS].replace_one({"_id": key}, {"_id": key, "lists": lists, "updated_at": time.time()}, upsert=True)
    return lists


async def delete_list(db: Any, key: str, name: str) -> dict[str, list[str]]:
    lists = await get_lists(db, key)
    lists.pop(name, None)
    await db[WATCHLISTS].replace_one({"_id": key}, {"_id": key, "lists": lists, "updated_at": time.time()}, upsert=True)
    return lists


def clean_layout(raw: dict[str, Any]) -> dict[str, Any]:
    """Only known, typed fields are kept: a layout can never carry arbitrary data."""
    try:
        fast, slow = int(raw.get("ema_fast", 9)), int(raw.get("ema_slow", 20))
        interval = int(raw.get("interval", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid layout.") from None
    if not (2 <= fast < slow <= 300) or fast > 100 or interval not in INTERVALS or raw.get("pane", "rsi") not in PANES:
        raise HTTPException(status_code=422, detail="Invalid layout.")
    return {"ema_fast": fast, "ema_slow": slow, "interval": interval, "pane": raw.get("pane", "rsi"), **{f: bool(raw.get(f, True)) for f in FLAGS}}


async def get_layouts(db: Any, key: str) -> dict[str, dict[str, Any]]:
    doc = await db[LAYOUTS].find_one({"_id": key})
    return dict((doc or {}).get("layouts", {}))


async def put_layout(db: Any, key: str, name: str, raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    name = clean_name(name)
    layout = clean_layout(raw)
    layouts = await get_layouts(db, key)
    if name not in layouts and len(layouts) >= MAX_LAYOUTS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_LAYOUTS} chart layouts.")
    layouts[name] = layout
    await db[LAYOUTS].replace_one({"_id": key}, {"_id": key, "layouts": layouts, "updated_at": time.time()}, upsert=True)
    return layouts


async def delete_layout(db: Any, key: str, name: str) -> dict[str, dict[str, Any]]:
    layouts = await get_layouts(db, key)
    layouts.pop(name, None)
    await db[LAYOUTS].replace_one({"_id": key}, {"_id": key, "layouts": layouts, "updated_at": time.time()}, upsert=True)
    return layouts
