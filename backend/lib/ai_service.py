import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

try:  # Emergent's hosted LLM proxy; only present when running on Emergent
    from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
except ImportError:
    LlmChat = None
    StreamDone = None
    TextDelta = None
    UserMessage = None

from lib.candles import candle_store
from lib.db import db
from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from lib.trade_plan import build_trade_plan
from models.ai import AiAnalysisRequest
from models.dashboard import DashboardSnapshot


logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 400
ATM_WINDOW = 5  # strikes on each side of the at-the-money strike sent to the model

SYSTEM_MESSAGE = """You are the read-only AI analyst inside a NIFTY options dashboard.
Use only the supplied normalized snapshot and conversation history. Never invent live prices,
never claim an order was placed, and never provide personalized financial advice. Be concise,
plain-spoken, and explicit about uncertainty. CE means call option and PE means put option.
The iv, delta, gamma, theta (per day) and vega (per IV point) values are model estimates computed by
the dashboard (Black-Scholes with a fixed 6.5% rate), not exchange data; say so when you use them.
A null Greek means it could not be estimated: say that instead of guessing. OI totals and PCR cover
only the strikes in atm_option_rows' subscribed window, not the full option chain. trade_plan holds the dashboard's rule-based signal: BUY CALLS only when PCR
is bullish and the index rose over both 5 and 15 minutes, BUY PUTS only when PCR is bearish and it
fell over both, otherwise WAIT. It also holds two stops for the ATM strike: an index stop (15-minute
low for CE, 15-minute high for PE) and a premium stop (a fixed percent below the current premium).
Use trade_plan as the signal; explain it as a rule, never as a prediction or a certainty, and quote
its stop levels exactly instead of inventing your own. If feed_state is not LIVE, say the data may be
stale and give its time.
Every response based on simulated data must begin with 'DEMO ANALYSIS —'. Use plain text,
no markdown symbols, and never exceed 140 words."""

# The backend URL is public, so cap how many paid model calls it will make per hour.
_recent_calls: deque[float] = deque()


def _max_calls_per_hour() -> int:
    try:
        return max(1, int(os.environ.get("AI_MAX_REQUESTS_PER_HOUR", "60")))
    except ValueError:
        return 60


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
    if len(_recent_calls) >= _max_calls_per_hour():
        raise RuntimeError("AI hourly request limit reached")
    _recent_calls.append(now)


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
        raw = await db.market_snapshots.find_one({"symbol": symbol}, sort=[("as_of", -1)], projection={"_id": 0})
    if not raw:
        raise RuntimeError("No normalized live Kotak snapshot is available for AI analysis")
    return DashboardSnapshot(**raw)


def _market_context(snapshot: DashboardSnapshot, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    chain = sorted(snapshot.option_chain, key=lambda row: row.strike)
    atm_index = next((i for i, row in enumerate(chain) if row.is_atm), None)
    if atm_index is None and chain and snapshot.spot.ltp:
        atm_index = min(range(len(chain)), key=lambda i: abs(chain[i].strike - snapshot.spot.ltp))
    if atm_index is None:
        rows = chain
    else:
        rows = chain[max(0, atm_index - ATM_WINDOW): atm_index + ATM_WINDOW + 1]
    return {
        "mode": snapshot.feed.source,
        "feed_state": snapshot.feed.state,
        "last_tick": snapshot.feed.last_tick.isoformat() if snapshot.feed.last_tick else None,
        "symbol": snapshot.symbol,
        "expiry": snapshot.expiry,
        "as_of": snapshot.as_of.isoformat(),
        "spot": snapshot.spot.model_dump(mode="json"),
        "structure": snapshot.structure.model_dump(mode="json"),
        "signal": snapshot.signal.model_dump(mode="json"),
        "atm_option_rows": [row.model_dump(mode="json") for row in rows],
        "trade_plan": plan,
    }


def _task(action: str, message: str | None) -> str:
    if action == "explain":
        return "Explain the trade_plan signal in 4 short points under 110 words: why the rule says what it says (PCR and 5/15 minute momentum), both stop levels for the relevant side, and the main risk."
    if action == "summary":
        return "Write a compact end-of-day style summary under 140 words with Structure, Options positioning, Signal, and Risk headings."
    if action == "alert":
        return "Create one read-only options alert under 90 words. Headline is CE WATCH if trade_plan.signal is BUY CALLS, PE WATCH if BUY PUTS, otherwise WAIT; keep the required DEMO ANALYSIS prefix when applicable. Then give at most 3 short reasons, the index stop and premium stop from trade_plan for that side, and one invalidation condition."
    return f"Answer this dashboard question in at most 90 words: {message or 'Explain the current setup.'}"


async def _stream_anthropic(prompt: str) -> AsyncIterator[str]:
    headers = {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_MESSAGE,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", ANTHROPIC_URL, headers=headers, json=body) as response:
            if response.status_code != 200:
                raw = (await response.aread()).decode("utf-8", "replace")
                try:
                    error_type = json.loads(raw).get("error", {}).get("type", "unknown")
                except (ValueError, AttributeError):
                    error_type = "unknown"
                logger.warning("AI_ERROR provider=anthropic status=%s type=%s", response.status_code, error_type)
                raise RuntimeError(f"Anthropic API returned {response.status_code} ({error_type})")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield delta["text"]
                elif kind == "error":
                    error_type = event.get("error", {}).get("type", "unknown")
                    logger.warning("AI_ERROR provider=anthropic stream_error type=%s", error_type)
                    raise RuntimeError(f"Anthropic stream error ({error_type})")
                elif kind == "message_stop":
                    break


async def _stream_emergent(prompt: str, session_id: str) -> AsyncIterator[str]:
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"options-{session_id}",
        system_message=SYSTEM_MESSAGE,
    ).with_model("anthropic", CLAUDE_MODEL).with_params(max_tokens=MAX_TOKENS)
    async for event in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(event, TextDelta):
            yield event.content
        elif isinstance(event, StreamDone):
            break


async def stream_analysis(request: AiAnalysisRequest) -> AsyncIterator[str]:
    provider = _provider()
    if provider is None:
        raise RuntimeError("Claude integration is not configured")

    snapshot = await _snapshot(request.symbol)
    try:
        candles = (await candle_store.get(request.symbol, 1))["candles"]
    except Exception:  # noqa: BLE001
        candles = []
    plan = build_trade_plan(snapshot, candles, snapshot.feed.state)
    history_docs = await db.ai_messages.find({"session_id": request.session_id}).sort("created_at", -1).limit(6).to_list(6)
    history = [
        {"role": item.get("role", "user"), "content": item.get("content", "")}
        for item in reversed(history_docs)
    ]
    prompt = json.dumps(
        {
            "market_context": _market_context(snapshot, plan),
            "recent_conversation": history,
            "task": _task(request.action, request.message),
        },
        separators=(",", ":"),
    )
    _take_rate_slot()

    created_at = datetime.now(timezone.utc)
    if request.action == "chat" and request.message:
        await db.ai_messages.insert_one(
            {
                "session_id": request.session_id,
                "role": "user",
                "content": request.message,
                "symbol": request.symbol,
                "created_at": created_at,
            }
        )

    stream = _stream_anthropic(prompt) if provider == "anthropic" else _stream_emergent(prompt, request.session_id)
    parts: list[str] = []
    async for piece in stream:
        parts.append(piece)
        yield piece

    content = "".join(parts).strip()
    collection = "ai_alerts" if request.action == "alert" else "ai_summaries" if request.action == "summary" else "ai_messages"
    await db[collection].insert_one(
        {
            "session_id": request.session_id,
            "role": "assistant",
            "action": request.action,
            "content": content,
            "symbol": request.symbol,
            "source": snapshot.feed.source,
            "created_at": datetime.now(timezone.utc),
        }
    )
