import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from lib.access import require_user
from lib.ai_service import CLAUDE_MODEL, AiUserError, ai_configured, cached_cards, generate_cards, stream_analysis, usage_for
from models.ai import AiAnalysisRequest, AiStatus
from models.dashboard import IndexSymbol


router = APIRouter(prefix="/ai", tags=["ai"])


class CardsRequest(BaseModel):
    symbol: IndexSymbol = "NIFTY"


@router.get("/status", response_model=AiStatus)
async def get_ai_status() -> AiStatus:
    return AiStatus(
        configured=ai_configured(),
        model=CLAUDE_MODEL,
        capabilities=["explain", "chat", "summary", "alert"],
    )


@router.get("/usage")
async def get_ai_usage(user: dict[str, Any] = Depends(require_user)) -> dict:
    return await usage_for(user)


@router.post("/stream")
async def stream_ai_analysis(request: AiAnalysisRequest, user: dict[str, Any] = Depends(require_user)) -> StreamingResponse:
    if not ai_configured():
        raise HTTPException(status_code=503, detail="Claude integration is not configured")

    async def events():
        try:
            async for delta in stream_analysis(request, user):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except AiUserError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'error': 'The AI analyst is temporarily unavailable. Try again shortly.'})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/cards")
async def get_cards(symbol: IndexSymbol = Query(default="NIFTY")) -> dict:
    """Cards already generated for this index (shared by everyone). Never triggers a paid call."""
    return {"symbol": symbol, "result": cached_cards(symbol)}


@router.post("/cards")
async def post_cards(body: CardsRequest) -> dict:
    if not ai_configured():
        raise HTTPException(status_code=503, detail="The AI analyst isn't configured on the server.")
    try:
        return {"symbol": body.symbol, "result": await generate_cards(body.symbol)}
    except AiUserError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
