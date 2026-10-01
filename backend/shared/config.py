"""The ONLY channel from the research engine to the live engine: a validated config.json.

Research writes it (`save_config`); the live engine only reads it (`load_config`). The file holds parameters
and aggregate validation statistics, never candles, labels, outcomes or training data (`extra="forbid"`
rejects any other key, so nothing else can ride along).
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_PATH = Path(os.environ.get("ENGINE_CONFIG_PATH", Path(__file__).resolve().parent.parent / "config.json"))


class Validation(BaseModel):
    """Aggregate, out-of-sample statistics produced by research. Display-only: the live engine never
    uses it to compute a signal or a confidence."""

    model_config = ConfigDict(extra="forbid")
    method: str = "walk_forward_out_of_sample"
    accuracy_pct: float = Field(ge=0, le=100)
    signals: int = Field(ge=0)
    period_start: str
    period_end: str
    horizon_bars: int = Field(ge=1)
    measured_on: str = "index direction (spot), not option P&L"


class CalibrationBand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    band: str
    signals: int = Field(ge=0)
    hit_rate_pct: float | None = Field(default=None, ge=0, le=100)


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    generated_at: datetime | None = None
    generated_by: str = "defaults"  # "defaults" or "research:<run_id>"

    # Signal model
    candle_minutes: int = Field(default=1, ge=1, le=15)
    ema_fast: int = Field(default=9, ge=2, le=100)
    ema_slow: int = Field(default=20, ge=3, le=200)
    rsi_period: int = Field(default=14, ge=2, le=50)
    ema_weight: float = Field(default=0.39, ge=0, le=1)
    rsi_weight: float = Field(default=0.39, ge=0, le=1)
    oi_weight: float = Field(default=0.22, ge=0, le=1)
    minimum_confidence: int = Field(default=78, ge=1, le=100)
    ema_spread_scale_pct: float = Field(default=0.10, gt=0)  # EMA gap (% of price) that counts as a full-strength trend
    rsi_scale: float = Field(default=20.0, gt=0)  # RSI distance from 50 that counts as full-strength momentum
    pcr_scale: float = Field(default=0.30, gt=0)  # PCR distance from 1.0 that counts as full-strength OI lean

    # Strike scoring
    strike_window: int = Field(default=3, ge=0, le=10)  # strikes either side of ATM that are considered
    target_delta: float = Field(default=0.50, gt=0, lt=1)
    min_strike_oi: int = Field(default=0, ge=0)
    min_premium: float = Field(default=5.0, ge=0)

    # Risk management
    premium_stop_pct: float = Field(default=25.0, ge=5, le=80)
    premium_target_pct: float = Field(default=40.0, ge=5, le=300)
    min_reward_risk: float = Field(default=1.2, ge=0)
    no_entry_before: str = Field(default="09:30", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    no_entry_after: str = Field(default="15:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    signal_cooldown_seconds: int = Field(default=300, ge=0, le=7200)
    index_stop_window_candles: int = Field(default=15, ge=3, le=60)

    # Data quality
    max_data_age_seconds: int = Field(default=5, ge=1, le=60)

    # Research output shown next to (never mixed into) live confidence
    validation: Validation | None = None
    calibration: list[CalibrationBand] = Field(default_factory=list)

    @field_validator("ema_slow")
    @classmethod
    def _slow_above_fast(cls, value: int, info: Any) -> int:
        fast = info.data.get("ema_fast")
        if fast is not None and value <= fast:
            raise ValueError("ema_slow must be greater than ema_fast")
        return value

    @model_validator(mode="after")
    def _weights(self) -> "EngineConfig":
        if self.ema_weight + self.rsi_weight + self.oi_weight <= 0:
            raise ValueError("at least one weight must be positive")
        return self

    @property
    def warmup_candles(self) -> int:
        """Closed candles needed before the indicators mean anything."""
        return max(self.ema_slow * 2, self.rsi_period * 2 + 1)

    def signal_params(self) -> dict[str, Any]:
        """The fields that influence a signal's value (validation/calibration/metadata deliberately excluded)."""
        return self.model_dump(mode="json", exclude={"validation", "calibration", "generated_at", "generated_by"})

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.signal_params(), sort_keys=True).encode()).hexdigest()[:16]


def load_config(path: Path | str | None = None) -> EngineConfig:
    """Read config.json. A missing file means built-in defaults; an invalid file raises (never silently ignored)."""
    target = Path(path) if path else CONFIG_PATH
    if not target.exists():
        return EngineConfig()
    return EngineConfig.model_validate(json.loads(target.read_text()))


def save_config(config: EngineConfig, path: Path | str | None = None) -> Path:
    """Atomic write so the live engine never reads a half-written file. Called by research tooling only."""
    target = Path(path) if path else CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config.model_dump(mode="json"), indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return target
