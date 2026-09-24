from datetime import datetime
from typing import Literal

from pydantic import BaseModel


IndexSymbol = Literal["NIFTY", "BANKNIFTY", "FINNIFTY"]
MarketState = Literal["LIVE", "STALE", "EXPIRED", "MARKET_CLOSED", "DEMO"]
FeedAlertType = Literal["ATM_SHIFT", "EXPIRY_DAY", "NEAR_CLOSE", "ROLL_REQUIRED"]


class FeedAlert(BaseModel):
    id: str
    type: FeedAlertType
    title: str
    message: str
    created_at: datetime


class FeedStatus(BaseModel):
    state: MarketState
    connected: bool
    authenticated: bool
    last_tick: datetime | None
    subscriptions: int
    divider_verified: bool
    atm_strike: int | None
    expiry: str | None
    message: str
    alerts: list[FeedAlert]


class SpotSnapshot(BaseModel):
    symbol: IndexSymbol
    ltp: float
    change: float
    pct_change: float
    high: float
    low: float
    timestamp: datetime | None


class OptionLeg(BaseModel):
    ltp: float
    change: float
    oi: int
    oi_change: int
    iv: float
    delta: float


class OptionRow(BaseModel):
    strike: int
    call: OptionLeg
    put: OptionLeg
    is_atm: bool


class MarketStructure(BaseModel):
    pcr: float
    max_pain: int
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    oi_buildup: str


class SignalSnapshot(BaseModel):
    recommendation: Literal["BUY CALLS", "BUY PUTS", "WAIT"]
    confidence: int
    reasons: list[str]
    timestamp: datetime | None


class FeedHealth(BaseModel):
    state: MarketState
    source: Literal["KOTAK_NEO", "DEMO"]
    last_tick: datetime | None
    heartbeat_ms: int
    subscriptions: int
    divider_status: Literal["VERIFIED", "PENDING"]


class DashboardSnapshot(BaseModel):
    symbol: IndexSymbol
    expiry: str
    spot: SpotSnapshot
    option_chain: list[OptionRow]
    structure: MarketStructure
    signal: SignalSnapshot
    feed: FeedHealth
    as_of: datetime