from typing import Literal

from pydantic import BaseModel, Field

from models.dashboard import IndexSymbol


AiAction = Literal["explain", "chat", "summary", "alert"]


class AiAnalysisRequest(BaseModel):
    action: AiAction
    symbol: IndexSymbol = "NIFTY"
    session_id: str = Field(min_length=8, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class AiStatus(BaseModel):
    configured: bool
    provider: Literal["anthropic"] = "anthropic"
    model: str
    capabilities: list[AiAction]