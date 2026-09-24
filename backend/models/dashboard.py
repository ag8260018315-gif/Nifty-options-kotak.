from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


IndexSymbol = Literal["NIFTY", "BANKNIFTY", "FINNIFTY"]
MarketState = Literal["LIVE", "STALE", "EXPIRED", "MARKET_CLOSED", "DEMO"]
FeedAlertType = Literal["ATM_SHIFT", "EXPIRY_DAY", "NEAR_CLOSE", "ROLL_REQUIRED", "OPENING_REPORT", "EXPORT_READY"]


class FeedAlert(BaseModel):
    id: str
    type: FeedAlertType
    title: str
    message: str
    created_at: datetime
    symbol: IndexSymbol | None = None


class AlertSettings(BaseModel):
    atm_shift_steps: int = Field(default=1, ge=1, le=5)
    cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    quiet_start: str = Field(default="15:30", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    quiet_end: str = Field(default="09:15", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class IndexFeedStatus(BaseModel):
    symbol: IndexSymbol
    state: MarketState
    last_tick: datetime | None
    atm_strike: int | None
    expiry: str | None
    option_subscriptions: int
    paired_strikes: int
    expected_pairs: int


class OpeningIndexHealth(BaseModel):
    symbol: IndexSymbol
    fresh_spot: bool
    divider_verified: bool
    option_window_complete: bool
    paired_ce_pe_complete: bool
    socket_connected: bool
    option_subscriptions: int
    paired_strikes: int


class OpeningReport(BaseModel):
    session_date: str
    generated_at: datetime
    status: Literal["PASS", "WARN"]
    indices: list[OpeningIndexHealth]


class ExportArchiveItem(BaseModel):
    symbol: IndexSymbol
    available: bool
    snapshot_count: int
    row_count: int
    first_capture: datetime | None
    last_capture: datetime | None
    filename: str | None


class ExportArchiveResponse(BaseModel):
    trading_day: str
    prepared_at: datetime | None
    items: list[ExportArchiveItem]


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
    indices: list[IndexFeedStatus]
    opening_report: OpeningReport | None
    alert_settings: AlertSettings


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