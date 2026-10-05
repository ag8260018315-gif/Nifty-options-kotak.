"""A short plain-language recap of the market built ONLY from the app's own numbers.

Facts first (sector moves, advancers and decliners, top movers, volume spikes, signal counts, how fresh the data is), then either
  * an AI paragraph written from exactly those facts, accepted only if every number in it appears in the facts and it contains
    no advice wording (the dashboard AI's existing checker; one rewrite is tried), or
  * a rules-written paragraph when the AI is off, busy or fails the check. The page says which one it is.
Never a prediction or advice. One summary serves all users and is cached (15 minutes while the market is open, otherwise once per
session day) so cost stays small."""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from lib.ai_facts import check_text

logger = logging.getLogger(__name__)
NOTE = "Written from the app's own numbers. A recap of what happened, not a forecast or advice."
SYSTEM = ("You write a short factual recap of the Indian stock market for traders, using ONLY the facts JSON you are given. "
          "Rules: 90 to 150 words, plain sentences, no bullet lists. Use every number exactly as it appears in the facts and never invent one. "
          "Say whether the data is live, from the last session, delayed or unavailable. Do not give advice, recommendations or predictions, "
          "and do not use words like buy, sell, should, target or expect.")
OPEN_TTL = 900.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = asyncio.Lock()


def build_facts(sectors: list[dict[str, Any]], rows: list[dict[str, Any]], market: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Pure: every figure in the summary comes from here."""
    now = now or datetime.now(timezone.utc)
    priced = [r for r in rows if r.get("quote") and r["quote"].get("change_pct") is not None]
    ranked = sorted(priced, key=lambda r: r["quote"]["change_pct"], reverse=True)
    spikes = sorted((r for r in priced if (r.get("signal") or {}).get("relative_volume") is not None and r["signal"]["relative_volume"] >= 2), key=lambda r: -r["signal"]["relative_volume"])
    acts = [(r.get("signal") or {}).get("action") for r in priced]
    state = (market or {}).get("state", "NO_FEED")
    label = {"OPEN": "live", "CLOSED": "from the last session (market closed)", "DELAYED": "delayed", "NO_FEED": "unavailable"}.get(state, "unavailable")
    return {
        "as_of": now.isoformat(), "data": label, "stocks_with_prices": len(priced), "advancers": sum(1 for r in priced if r["quote"]["change_pct"] > 0),
        "decliners": sum(1 for r in priced if r["quote"]["change_pct"] < 0), "signals_bullish": acts.count("BUY"), "signals_bearish": acts.count("SELL"),
        "best_sectors": [{"sector": s["sector"], "avg_change_pct": s["avg_change_pct"]} for s in sectors if s["avg_change_pct"] is not None][:3],
        "weakest_sectors": [{"sector": s["sector"], "avg_change_pct": s["avg_change_pct"]} for s in sectors if s["avg_change_pct"] is not None][::-1][:3],
        "top_gainers": [{"symbol": r["symbol"], "change_pct": r["quote"]["change_pct"]} for r in ranked[:5]],
        "top_losers": [{"symbol": r["symbol"], "change_pct": r["quote"]["change_pct"]} for r in ranked[::-1][:5]],
        "volume_spikes": [{"symbol": r["symbol"], "relative_volume": r["signal"]["relative_volume"]} for r in spikes[:5]],
    }


def allowed_numbers(facts: dict[str, Any]) -> list[float]:
    found: list[float] = []

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            found.extend([float(value), abs(float(value))])
        elif isinstance(value, dict):
            for k, v in value.items():
                if k != "as_of":
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(facts)
    return found


def rules_text(facts: dict[str, Any]) -> str:
    if not facts["stocks_with_prices"]:
        return f"No stock prices are available right now (data {facts['data']}), so there is nothing to summarise yet."
    best = ", ".join(f"{s['sector']} ({s['avg_change_pct']}%)" for s in facts["best_sectors"])
    worst = ", ".join(f"{s['sector']} ({s['avg_change_pct']}%)" for s in facts["weakest_sectors"])
    up = ", ".join(f"{g['symbol']} ({g['change_pct']}%)" for g in facts["top_gainers"][:3])
    down = ", ".join(f"{g['symbol']} ({g['change_pct']}%)" for g in facts["top_losers"][:3])
    text = (f"Data is {facts['data']}. Of {facts['stocks_with_prices']} stocks with prices, {facts['advancers']} are up and {facts['decliners']} are down. "
            f"The strongest sectors by average change are {best}; the weakest are {worst}. Top movers up: {up}. Top movers down: {down}.")
    if facts["volume_spikes"]:
        text += " Unusual volume: " + ", ".join(f"{v['symbol']} ({v['relative_volume']}x)" for v in facts["volume_spikes"][:3]) + "."
    return text + f" The signal engine currently reads {facts['signals_bullish']} stocks as bullish and {facts['signals_bearish']} as bearish."


async def compose(facts: dict[str, Any], complete: Callable[[str, str, int], Awaitable[str]] | None) -> dict[str, Any]:
    base = {"facts": facts, "note": NOTE, "generated_at": datetime.now(timezone.utc).isoformat()}
    if complete is not None and facts["stocks_with_prices"]:
        prompt = json.dumps(facts, separators=(",", ":"))
        allowed = allowed_numbers(facts)
        try:
            text = await complete(SYSTEM, prompt, 500)
            problems = check_text(text, allowed)
            if problems["numbers"] or problems["advice"]:
                text = await complete(SYSTEM, prompt + f"\n\nYour last attempt used numbers not in the facts {problems['numbers'][:5]} or advice wording {problems['advice']}. Rewrite using only the facts.", 500)
                problems = check_text(text, allowed)
            if not problems["numbers"] and not problems["advice"] and text.strip():
                return {**base, "source": "AI", "text": text.strip()}
        except Exception as exc:  # noqa: BLE001  the AI being off or busy must not break the page
            logger.warning("SUMMARY_AI_ERROR kind=%s", type(exc).__name__)
    return {**base, "source": "RULES", "text": rules_text(facts)}


async def get(builder: Callable[[], Awaitable[dict[str, Any]]], complete: Callable[[str, str, int], Awaitable[str]] | None, day: str, state: str) -> dict[str, Any]:
    """Cached summary shared by all users. Market open: refreshed every 15 minutes. Otherwise one per day and state (closed, delayed...)."""
    key = f"{day}:{state}"
    async with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < (OPEN_TTL if state == "OPEN" else 6 * 3600):
            return hit[1]
        result = await compose(await builder(), complete)
        _cache[key] = (time.monotonic(), result)
        return result
