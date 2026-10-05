"""Per-user price and signal alerts for the premium stocks. Rules live in `premium_alerts`, notifications in `premium_alert_events`.

A background loop checks the active rules every few seconds, but ONLY against fresh live prices (market open and ticks recent): it
never alerts from stale or closed-market data. An alert is informational and may arrive a little late or, if the server is
restarting or the feed is down, not at all. Nothing here places an order."""
import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)
RULES, EVENTS = "premium_alerts", "premium_alert_events"
MAX_RULES, MAX_EVENTS, COOLDOWN = 30, 100, 1800
CHECK_SECONDS = 10
KINDS = {
    "price_above": "price rises to or above", "price_below": "price falls to or below",
    "change_pct_above": "day change rises to or above (%)", "change_pct_below": "day change falls to or below (%)",
    "volume_spike": "relative volume reaches (times average)", "bias_bullish": "signal turns Bullish", "bias_bearish": "signal turns Bearish",
}
NO_VALUE = {"bias_bullish", "bias_bearish"}


def clean_rule(raw: dict[str, Any], universe: set[str]) -> dict[str, Any]:
    symbol = str(raw.get("symbol", "")).upper().strip()
    kind = raw.get("kind")
    if symbol not in universe:
        raise HTTPException(status_code=422, detail=f"{symbol or 'That'} is not a supported stock.")
    if kind not in KINDS:
        raise HTTPException(status_code=422, detail="Unknown alert type.")
    value = None
    if kind not in NO_VALUE:
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Enter a number for the alert level.") from None
        if not (value == value) or abs(value) > 1e7 or (kind.startswith("price") and value <= 0) or (kind == "volume_spike" and not 1 <= value <= 100):
            raise HTTPException(status_code=422, detail="That alert level is out of range.")
    return {"symbol": symbol, "kind": kind, "value": value, "once": bool(raw.get("once", True)), "email": bool(raw.get("email", False))}


def triggered(rule: dict[str, Any], quote: dict[str, Any] | None, quick: dict[str, Any] | None) -> str | None:
    """A sentence if the rule's condition holds right now, else None. Pure."""
    kind, v = rule["kind"], rule.get("value")
    if kind.startswith("bias_"):
        want = "BUY" if kind == "bias_bullish" else "SELL"
        return f"{rule['symbol']}: the signal turned {'Bullish' if want == 'BUY' else 'Bearish'}" if quick and quick.get("action") == want else None
    if kind == "volume_spike":
        rv = (quick or {}).get("relative_volume")
        return f"{rule['symbol']}: relative volume is {rv}x the recent average" if rv is not None and v is not None and rv >= v else None
    if not quote:
        return None
    ltp, pct = quote.get("ltp"), quote.get("change_pct")
    if kind == "price_above" and ltp is not None and v is not None and ltp >= v:
        return f"{rule['symbol']}: price {ltp} is at or above {v}"
    if kind == "price_below" and ltp is not None and v is not None and ltp <= v:
        return f"{rule['symbol']}: price {ltp} is at or below {v}"
    if kind == "change_pct_above" and pct is not None and v is not None and pct >= v:
        return f"{rule['symbol']}: up {pct}% today (alert level {v}%)"
    if kind == "change_pct_below" and pct is not None and v is not None and pct <= v:
        return f"{rule['symbol']}: down {pct}% today (alert level {v}%)"
    return None


async def add_rule(db: Any, owner: str, raw: dict[str, Any], universe: set[str]) -> dict[str, Any]:
    rule = clean_rule(raw, universe)
    if await db[RULES].count_documents({"owner": owner}) >= MAX_RULES:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_RULES} alerts.")
    doc = {"_id": uuid.uuid4().hex, "owner": owner, **rule, "active": True, "created_at": time.time(), "last_fired_at": None, "fired": 0, "armed": True}
    await db[RULES].insert_one(doc)
    return doc


async def list_rules(db: Any, owner: str) -> list[dict[str, Any]]:
    return [{**{k: v for k, v in d.items() if k not in ("_id", "owner")}, "id": d["_id"]} for d in await db[RULES].find({"owner": owner}).sort("created_at", -1).to_list(100)]


async def set_active(db: Any, owner: str, rule_id: str, active: bool) -> None:
    res = await db[RULES].update_one({"_id": rule_id, "owner": owner}, {"$set": {"active": bool(active), "armed": True}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="No such alert.")


async def delete_rule(db: Any, owner: str, rule_id: str) -> None:
    await db[RULES].delete_one({"_id": rule_id, "owner": owner})


async def list_events(db: Any, owner: str) -> dict[str, Any]:
    docs = await db[EVENTS].find({"owner": owner}).sort("at", -1).to_list(MAX_EVENTS)
    return {"events": [{"message": d["message"], "symbol": d["symbol"], "at": d["at"], "read": d.get("read", False)} for d in docs], "unread": sum(1 for d in docs if not d.get("read"))}


async def mark_read(db: Any, owner: str) -> None:
    await db[EVENTS].update_many({"owner": owner, "read": {"$ne": True}}, {"$set": {"read": True}})


async def evaluate(db: Any, quote_of: Callable[[str], dict[str, Any] | None], quick_of: Callable[[str], Awaitable[dict[str, Any]]], is_live: Callable[[str], bool],
                   send_mail: Callable[[str, str, str], Awaitable[bool]] | None = None, now: float | None = None) -> int:
    """One pass over the active rules. Returns how many fired. Skips a symbol whose price is not fresh and live."""
    now = now or time.time()
    fired = 0
    for rule in await db[RULES].find({"active": True}).to_list(2000):
        symbol = rule["symbol"]
        if not is_live(symbol):
            continue
        quick = await quick_of(symbol) if rule["kind"].startswith(("bias_", "volume")) else None
        message = triggered(rule, quote_of(symbol), quick)
        if message is None:
            if not rule.get("armed", True):
                await db[RULES].update_one({"_id": rule["_id"]}, {"$set": {"armed": True}})  # condition cleared: can fire again
            continue
        if not rule.get("armed", True) or (rule.get("last_fired_at") and now - rule["last_fired_at"] < COOLDOWN):
            continue
        fired += 1
        update: dict[str, Any] = {"last_fired_at": now, "armed": False}
        if rule.get("once", True):
            update["active"] = False
        await db[RULES].update_one({"_id": rule["_id"]}, {"$set": update, "$inc": {"fired": 1}})
        await db[EVENTS].insert_one({"owner": rule["owner"], "symbol": symbol, "message": message, "at": now, "read": False})
        old = await db[EVENTS].find({"owner": rule["owner"]}).sort("at", -1).skip(MAX_EVENTS).to_list(50)
        if old:
            await db[EVENTS].delete_many({"_id": {"$in": [d["_id"] for d in old]}})
        if rule.get("email") and send_mail and "@" in rule["owner"] and not rule["owner"].endswith("@local"):
            await send_mail(rule["owner"], f"EdgeDesk alert: {message}", f"{message}\n\nThis alert came from live prices and may be slightly delayed. It is information, not advice, and no order was placed.\n")
    return fired


async def run_forever(db_getter: Callable[[], Any], quote_of: Callable[[str], dict[str, Any] | None], quick_of: Callable[[str], Awaitable[dict[str, Any]]],
                      is_live: Callable[[str], bool], send_mail: Callable[[str, str, str], Awaitable[bool]]) -> None:
    while True:
        try:
            await evaluate(db_getter(), quote_of, quick_of, is_live, send_mail)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  alerts must never disturb the app
            logger.warning("ALERTS_ERROR kind=%s", type(exc).__name__)
        await asyncio.sleep(CHECK_SECONDS)
