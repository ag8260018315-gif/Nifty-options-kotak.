"""Read-only AI analyst for the dashboard.

- The model only sees server-computed facts (lib.ai_facts). Every answer is checked before anyone sees it:
  numbers must match the data and advice wording is rejected. One rewrite is attempted, then a safe fallback.
- Answers to the built-in actions and suggested questions, and the insight cards, are shared by all users
  of an index for a few minutes (one generation serves everyone). Free-form questions are never shared.
- Per-user daily limits: AI_DAILY_LIMIT_TRIAL (default 10), AI_DAILY_LIMIT_MEMBER (default 30). Owner unlimited.
- A global cap AI_MAX_REQUESTS_PER_HOUR (default 60) still applies to fresh model calls.
"""
import asyncio
import json
import logging
import os
import random
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from zoneinfo import ZoneInfo

import httpx

try:  # Emergent's hosted LLM proxy; only present when running on Emergent
    from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
except ImportError:
    LlmChat = None
    StreamDone = None
    TextDelta = None
    UserMessage = None

from lib import access
from lib.ai_facts import CARD_TITLES, allowed_numbers, build_facts, card_data, check_text, compact_rows
from lib.candles import candle_store
from lib.db import db
from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from lib.market_read import build_market_read
from models.ai import AiAnalysisRequest
from models.dashboard import DashboardSnapshot


logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
CHAT_MAX_TOKENS = 450
CARDS_MAX_TOKENS = 1200
SHARED_TTL_SECONDS = 180
CARDS_KEEP_SECONDS = 600

SUGGESTED_QUESTIONS = [
    "What is happening around the ATM strike?",
    "Where is open interest concentrated?",
    "Explain today's PCR.",
    "What changed in the option chain?",
    "Summarize the current market structure.",
    "Which strikes carry the heaviest positioning?",
]

SYSTEM_MESSAGE = """You are the read-only AI analyst inside an Indian index options dashboard (NIFTY, BANKNIFTY, FINNIFTY).
You describe the data you are given. You never give advice.

Rules:
- Use only the numbers in the supplied facts and rows. Write numbers exactly as given; do not convert units or round
  differently. If something is not in the data, say it is not available.
- Never recommend or imply a trade. Do not use the words buy, sell, target, stop loss, entry, exit, go long or go short.
  Say "call writing" or "put writing" instead of "selling". Never predict future prices ("will rise", "will reach").
- pcr_lean, momentum and the 15 minute range are plain readings. Describe them; never turn them into a view on what to do or where price is going.
- iv, delta, gamma, theta and vega are Black-Scholes model estimates, not exchange figures.
- OI totals and PCR cover only the strikes in the dashboard's ATM window, not the full option chain.
- If feed_state is not LIVE, say the data may not be current and give data_time_ist.
- If data_source is DEMO, the data is simulated: start the DATA line with "DEMO ANALYSIS —".
- Plain text only, no markdown, no bullet symbols. Be concise and neutral."""

ANSWER_FORMAT = """Answer in exactly this format, plain text:
DATA: one to three short sentences stating what the facts show, with numbers copied from the facts.
INTERPRETATION: one to three short sentences on what this may mean for reading the market, descriptive only."""

CARD_SCHEMA_PART = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "At most 8 words, descriptive"},
        "shows": {"type": "string", "description": "One sentence on what the card's data shows"},
        "why": {"type": "string", "description": "One or two sentences on why it matters for reading the market"},
    },
    "required": ["headline", "shows", "why"],
    "additionalProperties": False,
}
CARDS_SCHEMA = {
    "type": "object",
    "properties": {key: CARD_SCHEMA_PART for key in CARD_TITLES},
    "required": list(CARD_TITLES),
    "additionalProperties": False,
}


class AiUserError(Exception):
    """A problem the user should see as-is (limits, missing data, unavailable)."""


# ------------------------------------------------------------------ configuration and limits
_recent_calls: deque[float] = deque()
_shared: dict[str, tuple[float, str]] = {}
_cards: dict[str, dict[str, Any]] = {}
_card_locks: dict[str, asyncio.Lock] = {}


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _provider() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("EMERGENT_LLM_KEY") and LlmChat is not None:
        return "emergent"
    return None


def ai_configured() -> bool:
    return _provider() is not None


def _take_rate_slot() -> None:
    now = time.monotonic()
    while _recent_calls and now - _recent_calls[0] > 3600:
        _recent_calls.popleft()
    if len(_recent_calls) >= max(1, _int_env("AI_MAX_REQUESTS_PER_HOUR", 60)):
        raise AiUserError("The AI analyst is busy right now. Try again in a few minutes.")
    _recent_calls.append(now)


def _daily_limit(user: dict[str, Any] | None) -> int | None:
    if not user or not user.get("email") or not access.auth_required() or user.get("role") == "admin":
        return None
    if user.get("role") == "trial":
        return _int_env("AI_DAILY_LIMIT_TRIAL", 10)
    return _int_env("AI_DAILY_LIMIT_MEMBER", 30)


def _usage_key(email: str) -> str:
    return f"{email}:{datetime.now(timezone.utc).astimezone(IST).date().isoformat()}"


async def usage_for(user: dict[str, Any] | None) -> dict[str, Any]:
    limit = _daily_limit(user)
    if limit is None:
        return {"used": None, "limit": None, "remaining": None}
    doc = await db.ai_usage.find_one({"_id": _usage_key(user["email"])}) or {}
    used = int(doc.get("count", 0))
    return {"used": used, "limit": limit, "remaining": max(0, limit - used)}


async def _check_quota(user: dict[str, Any] | None) -> None:
    usage = await usage_for(user)
    if usage["limit"] is not None and usage["remaining"] <= 0:
        raise AiUserError(f"You've used today's {usage['limit']} AI questions. The limit resets at midnight IST.")


async def _count_use(user: dict[str, Any] | None) -> None:
    if _daily_limit(user) is None:
        return
    await db.ai_usage.update_one({"_id": _usage_key(user["email"])}, {"$inc": {"count": 1}, "$set": {"updated_at": time.time()}}, upsert=True)


# ------------------------------------------------------------------ market context
async def _snapshot(symbol: str) -> DashboardSnapshot:
    if settings.mode == "DEMO":
        return demo_snapshot(symbol)
    from lib.feed_worker import feed_worker  # the same in-memory snapshot the dashboard shows

    current = feed_worker.snapshot_for(symbol)
    if current is not None:
        snapshot = current.model_copy(deep=True)
        status = feed_worker.status()
        index_status = next((item for item in status.indices if item.symbol == symbol), None)
        snapshot.feed.state = index_status.state if index_status else status.state
        if index_status and index_status.last_tick:
            snapshot.feed.last_tick = index_status.last_tick
        return snapshot
    raw = await db.market_snapshots.find_one({"_id": symbol}, projection={"_id": 0})
    if not raw:
        raise AiUserError("There's no live option chain for this index yet, so there's nothing to analyze.")
    return DashboardSnapshot(**raw)


async def _context(symbol: str) -> tuple[DashboardSnapshot, dict[str, Any], list[list[float]], list[float]]:
    snapshot = await _snapshot(symbol)
    try:
        candles = (await candle_store.get(symbol, 1))["candles"]
    except Exception:  # noqa: BLE001
        candles = []
    read = build_market_read(snapshot, candles, snapshot.feed.state)
    facts = build_facts(snapshot, read)
    if "spot" not in facts or "pcr" not in facts:
        raise AiUserError("The option chain isn't complete yet, so there's nothing reliable to analyze.")
    rows = compact_rows(snapshot)
    return snapshot, facts, rows, allowed_numbers(facts, rows)


# ------------------------------------------------------------------ model calls
async def _anthropic(system: str, user_text: str, max_tokens: int, schema: dict[str, Any] | None = None) -> str:
    headers = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    body: dict[str, Any] = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user_text}]}
    if schema is not None:
        body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    delays = [1.0, 3.0]
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        for attempt in range(len(delays) + 1):
            response = await client.post(ANTHROPIC_URL, headers=headers, json=body)
            if response.status_code == 200:
                payload = response.json()
                stop = payload.get("stop_reason")
                if stop in {"max_tokens", "refusal"}:
                    logger.warning("AI_ERROR provider=anthropic stop_reason=%s", stop)
                    raise AiUserError("The AI analyst couldn't complete that answer. Try again.")
                return "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text").strip()
            try:
                error_type = response.json().get("error", {}).get("type", "unknown")
            except ValueError:
                error_type = "unknown"
            logger.warning("AI_ERROR provider=anthropic status=%s type=%s attempt=%s", response.status_code, error_type, attempt + 1)
            if response.status_code == 400 and schema is not None and "output_config" in body:
                body.pop("output_config")  # older API behaviour: fall back to asking for JSON in the prompt
                continue
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                if retry_after is None or attempt >= 1:
                    raise AiUserError("The AI analyst has reached its usage limit. Try again later.")
                await asyncio.sleep(min(10.0, float(retry_after)))
                continue
            if response.status_code in {500, 502, 503, 504, 529} and attempt < len(delays):
                await asyncio.sleep(delays[attempt] + random.random() * 0.5)
                continue
            raise AiUserError("The AI analyst is temporarily unavailable. Try again shortly.")
    raise AiUserError("The AI analyst is temporarily unavailable. Try again shortly.")


async def _emergent(system: str, user_text: str, max_tokens: int, session_id: str) -> str:
    chat = LlmChat(api_key=os.environ["EMERGENT_LLM_KEY"], session_id=f"options-{session_id}", system_message=system).with_model("anthropic", CLAUDE_MODEL).with_params(max_tokens=max_tokens)
    parts: list[str] = []
    async for event in chat.stream_message(UserMessage(text=user_text)):
        if isinstance(event, TextDelta):
            parts.append(event.content)
        elif isinstance(event, StreamDone):
            break
    return "".join(parts).strip()


async def _complete(system: str, user_text: str, max_tokens: int, schema: dict[str, Any] | None = None, session_id: str = "shared") -> str:
    provider = _provider()
    if provider is None:
        raise AiUserError("The AI analyst isn't configured on the server.")
    _take_rate_slot()
    if provider == "anthropic":
        return await _anthropic(system, user_text, max_tokens, schema)
    return await _emergent(system, user_text, max_tokens, session_id)


def _problems_note(problems: dict[str, list[str]]) -> str:
    notes = []
    if problems["numbers"]:
        notes.append(f"these numbers are not in the data: {', '.join(problems['numbers'][:8])}")
    if problems["advice"]:
        notes.append(f"these words are not allowed: {', '.join(problems['advice'])}")
    return "Your previous answer was rejected because " + "; ".join(notes) + ". Rewrite it using only the supplied numbers and descriptive wording."


# ------------------------------------------------------------------ answers
def _task(action: str, message: str | None) -> str:
    if action == "explain":
        return "Explain the current readings: what PCR says about open interest positioning, what the 5 and 15 minute moves and the 15 minute range say about recent price action, and where the readings point the same way or differ. Describe only."
    if action == "summary":
        return "Summarize the session so far: price action, open interest positioning, volatility, and the main uncertainty in the data."
    if action == "alert":
        return "Describe the single most notable change in the option chain right now. Start with a line 'HEADLINE:' of at most 8 descriptive words, then the DATA and INTERPRETATION lines."
    return f"Answer this question about the dashboard data: {message or 'Summarize the current market structure.'}"


def _shared_key(symbol: str, action: str, message: str | None) -> str | None:
    if action != "chat":
        return f"{symbol}:{action}"
    normalized = (message or "").strip().rstrip("?.! ").lower()
    for question in SUGGESTED_QUESTIONS:
        if normalized == question.rstrip("?.! ").lower():
            return f"{symbol}:q:{normalized}"
    return None


async def _grounded_answer(action: str, message: str | None, facts: dict[str, Any], rows: list[list[float]], allowed: list[float], history: list[dict[str, str]], session_id: str) -> str:
    prompt = {"facts": facts, "rows_atm_window": {"columns": ["strike", "call_oi", "call_oi_change", "put_oi", "put_oi_change"], "rows": rows}, "recent_conversation": history, "task": _task(action, message)}
    text = await _complete(SYSTEM_MESSAGE, json.dumps(prompt, separators=(",", ":")) + "\n\n" + ANSWER_FORMAT, CHAT_MAX_TOKENS, session_id=session_id)
    problems = check_text(text, allowed)
    if problems["numbers"] or problems["advice"]:
        logger.warning("AI_REWRITE numbers=%s advice=%s", len(problems["numbers"]), problems["advice"])
        text = await _complete(SYSTEM_MESSAGE, json.dumps(prompt, separators=(",", ":")) + "\n\n" + ANSWER_FORMAT + "\n\n" + _problems_note(problems), CHAT_MAX_TOKENS, session_id=session_id)
        problems = check_text(text, allowed)
        if problems["numbers"] or problems["advice"]:
            logger.warning("AI_WITHHELD numbers=%s advice=%s", problems["numbers"][:5], problems["advice"])
            return ("DATA: The answer didn't match the dashboard's figures exactly, so it was withheld.\n"
                    "INTERPRETATION: Try asking in a different way, or read the figures directly from the dashboard.")
    return text


async def stream_analysis(request: AiAnalysisRequest, user: dict[str, Any] | None = None) -> AsyncIterator[str]:
    if _provider() is None:
        raise AiUserError("The AI analyst isn't configured on the server.")
    key = _shared_key(request.symbol, request.action, request.message)
    cached = _shared.get(key) if key else None
    if cached and time.time() - cached[0] < SHARED_TTL_SECONDS:
        text = cached[1]
    else:
        await _check_quota(user)
        snapshot, facts, rows, allowed = await _context(request.symbol)
        history: list[dict[str, str]] = []
        if key is None:
            docs = await db.ai_messages.find({"session_id": request.session_id}).sort("created_at", -1).limit(6).to_list(6)
            history = [{"role": item.get("role", "user"), "content": item.get("content", "")} for item in reversed(docs)]
        text = await _grounded_answer(request.action, request.message, facts, rows, allowed, history, request.session_id)
        if key:
            _shared[key] = (time.time(), text)
        await _count_use(user)
        await db.ai_messages.insert_many([
            {"session_id": request.session_id, "role": "user", "action": request.action, "content": request.message or request.action, "symbol": request.symbol, "created_at": datetime.now(timezone.utc)},
            {"session_id": request.session_id, "role": "assistant", "action": request.action, "content": text, "symbol": request.symbol, "source": snapshot.feed.source, "created_at": datetime.now(timezone.utc)},
        ])
    # Deliver the checked answer in small pieces so it types out on screen.
    for start in range(0, len(text), 18):
        yield text[start:start + 18]
        await asyncio.sleep(0.012)


# ------------------------------------------------------------------ insight cards
def cached_cards(symbol: str) -> dict[str, Any] | None:
    entry = _cards.get(symbol)
    if entry and time.time() - entry["_created"] < CARDS_KEEP_SECONDS:
        return {key: value for key, value in entry.items() if not key.startswith("_")}
    return None


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return json.loads(cleaned[start:end + 1] if start >= 0 and end > start else cleaned)


async def generate_cards(symbol: str) -> dict[str, Any]:
    lock = _card_locks.setdefault(symbol, asyncio.Lock())
    async with lock:  # one generation per index at a time; everyone else gets the result
        entry = _cards.get(symbol)
        if entry and time.time() - entry["_created"] < SHARED_TTL_SECONDS:
            return cached_cards(symbol) or {}
        snapshot, facts, rows, allowed = await _context(symbol)
        data = card_data(facts)
        instructions = (
            "Write five insight cards: oi, pcr, volatility, greeks, structure. For each: headline (at most 8 descriptive words), "
            "shows (one sentence on what that card's data shows), why (one or two sentences on why it matters for reading the market). "
            "Descriptive only. Numbers only from the facts. Return JSON matching the schema, nothing else."
        )
        prompt = json.dumps({"facts": facts, "card_data": data, "rows_atm_window": rows}, separators=(",", ":"))
        texts: dict[str, Any] = {}
        ai_note: str | None = None
        try:
            for attempt in range(2):
                raw = await _complete(SYSTEM_MESSAGE, prompt + "\n\n" + instructions, CARDS_MAX_TOKENS, schema=CARDS_SCHEMA)
                try:
                    parsed = _parse_json(raw)
                except (ValueError, json.JSONDecodeError):
                    logger.warning("AI_CARDS_BAD_JSON attempt=%s", attempt + 1)
                    continue
                texts = parsed
                failing = [key for key in CARD_TITLES if not isinstance(parsed.get(key), dict) or any(check_text(" ".join(str(parsed[key].get(field, "")) for field in ("headline", "shows", "why")), allowed).values())]
                if not failing:
                    break
                logger.warning("AI_CARDS_REWRITE failing=%s", failing)
                instructions += f" Previous attempt broke the rules on: {', '.join(failing)}. Use only supplied numbers and no advice wording."
        except AiUserError as exc:  # the numbers on the cards come from the server, so they still show
            ai_note = str(exc)
            texts = {}
        cards = []
        for key, title in CARD_TITLES.items():
            part = texts.get(key) if isinstance(texts.get(key), dict) else None
            ok = bool(part) and not any(check_text(" ".join(str(part.get(field, "")) for field in ("headline", "shows", "why")), allowed).values())
            cards.append({
                "id": key,
                "title": title,
                "data": data[key],
                "headline": part.get("headline") if ok and part else None,
                "shows": part.get("shows") if ok and part else None,
                "why": part.get("why") if ok and part else None,
                "withheld": not ok,
            })
        now = datetime.now(timezone.utc)
        result = {
            "symbol": symbol,
            "generated_at": now.isoformat(),
            "data_as_of": (snapshot.feed.last_tick or snapshot.as_of).isoformat() if (snapshot.feed.last_tick or snapshot.as_of) else None,
            "feed_state": snapshot.feed.state,
            "note": ai_note,
            "cards": cards,
        }
        if ai_note is None:  # a failed attempt is not kept, so the next click can try again
            _cards[symbol] = {**result, "_created": time.time()}
            await db.ai_summaries.insert_one({"symbol": symbol, "action": "cards", "content": json.dumps(result), "created_at": now})
        return result
