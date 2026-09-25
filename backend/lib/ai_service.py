import json
import os
from datetime import datetime, timezone
from typing import Any, AsyncIterator

try:
    from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
except ImportError:
    LlmChat = None
    StreamDone = None
    TextDelta = None
    UserMessage = None
    
from lib.db import db
from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from models.ai import AiAnalysisRequest
from models.dashboard import DashboardSnapshot


CLAUDE_MODEL = "claude-haiku-4-5-20251001"
SYSTEM_MESSAGE = """You are the read-only AI analyst inside a NIFTY options dashboard.
Use only the supplied normalized snapshot and conversation history. Never invent live prices,
never claim an order was placed, and never provide personalized financial advice. Be concise,
plain-spoken, and explicit about uncertainty. CE means call option and PE means put option.
Every response based on simulated data must begin with 'DEMO ANALYSIS —'. Use plain text,
no markdown symbols, and never exceed 140 words."""


def ai_configured() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY"))


async def _snapshot(symbol: str) -> DashboardSnapshot:
    if settings.mode == "DEMO":
        return demo_snapshot(symbol)
    raw = await db.market_snapshots.find_one({"symbol": symbol}, sort=[("as_of", -1)], projection={"_id": 0})
    if not raw:
        raise RuntimeError("No normalized live Kotak snapshot is available for AI analysis")
    return DashboardSnapshot(**raw)


def _market_context(snapshot: DashboardSnapshot) -> dict[str, Any]:
    atm_rows = [row.model_dump(mode="json") for row in snapshot.option_chain if abs(row.strike - snapshot.structure.max_pain) <= 150]
    return {
        "mode": snapshot.feed.source,
        "symbol": snapshot.symbol,
        "as_of": snapshot.as_of.isoformat(),
        "spot": snapshot.spot.model_dump(mode="json"),
        "structure": snapshot.structure.model_dump(mode="json"),
        "signal": snapshot.signal.model_dump(mode="json"),
        "atm_option_rows": atm_rows,
    }


def _task(action: str, message: str | None) -> str:
    if action == "explain":
        return "Explain the current market structure and signal in 4 short bullets under 100 words. Mention PCR, max pain, OI, and the main risk."
    if action == "summary":
        return "Write a compact end-of-day style summary under 140 words with Structure, Options positioning, Signal, and Risk headings."
    if action == "alert":
        return "Create one read-only options alert under 80 words. Headline must identify CE WATCH, PE WATCH, or WAIT; keep the required DEMO ANALYSIS prefix when applicable. Then give at most 3 short reasons and one invalidation condition."
    return f"Answer this dashboard question in at most 90 words: {message or 'Explain the current setup.'}"


async def stream_analysis(request: AiAnalysisRequest) -> AsyncIterator[str]:
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise RuntimeError("Claude integration is not configured")

    snapshot = await _snapshot(request.symbol)
    history_docs = await db.ai_messages.find({"session_id": request.session_id}).sort("created_at", -1).limit(6).to_list(6)
    history = [
        {"role": item.get("role", "user"), "content": item.get("content", "")}
        for item in reversed(history_docs)
    ]
    prompt = json.dumps(
        {
            "market_context": _market_context(snapshot),
            "recent_conversation": history,
            "task": _task(request.action, request.message),
        },
        separators=(",", ":"),
    )

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

    chat = LlmChat(
        api_key=api_key,
        session_id=f"options-{request.session_id}",
        system_message=SYSTEM_MESSAGE,
    ).with_model("anthropic", CLAUDE_MODEL).with_params(max_tokens=350)

    parts: list[str] = []
    async for event in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(event, TextDelta):
            parts.append(event.content)
            yield event.content
        elif isinstance(event, StreamDone):
            break

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
