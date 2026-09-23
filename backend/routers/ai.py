import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from lib.ai_service import CLAUDE_MODEL, ai_configured, stream_analysis
from models.ai import AiAnalysisRequest, AiStatus


router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status", response_model=AiStatus)
async def get_ai_status() -> AiStatus:
    return AiStatus(
        configured=ai_configured(),
        model=CLAUDE_MODEL,
        capabilities=["explain", "chat", "summary", "alert"],
    )


@router.post("/stream")
async def stream_ai_analysis(request: AiAnalysisRequest) -> StreamingResponse:
    if not ai_configured():
        raise HTTPException(status_code=503, detail="Claude integration is not configured")

    async def events():
        try:
            async for delta in stream_analysis(request):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'error': 'Claude analysis is temporarily unavailable'})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )