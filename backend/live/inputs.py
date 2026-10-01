"""Everything the live engine is allowed to know at signal time, as plain immutable data.

`as_of` is the decision timestamp. Every other timestamp must be <= as_of (enforced by live.guard).
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class Leg:
    ltp: float
    change: float
    oi: int
    oi_change: int
    iv: float
    delta: float
    volume: int | None = None


@dataclass(frozen=True)
class ChainRow:
    strike: int
    call: Leg
    put: Leg


@dataclass(frozen=True)
class LiveInputs:
    symbol: str
    as_of: datetime  # timezone-aware
    feed_state: str  # LIVE / DEMO / STALE ...
    source: str  # KOTAK_NEO or DEMO
    spot: float
    spot_time: datetime | None
    chain: tuple[ChainRow, ...]
    chain_time: datetime | None
    expiry: date | None
    candles: tuple[dict[str, Any], ...] = field(default_factory=tuple)  # 1-minute candles, oldest first
    interval_seconds: int = 60  # width of each input candle

    def to_doc(self) -> dict[str, Any]:
        """JSON-safe copy stored with the signal so it can be replayed exactly."""
        from dataclasses import asdict

        raw = asdict(self)
        for key in ("as_of", "spot_time", "chain_time"):
            raw[key] = raw[key].isoformat() if raw[key] else None
        raw["expiry"] = raw["expiry"].isoformat() if raw["expiry"] else None
        raw["candles"] = [dict(c) for c in self.candles]
        return raw

    @staticmethod
    def from_doc(doc: dict[str, Any]) -> "LiveInputs":
        def dt(v: str | None) -> datetime | None:
            return datetime.fromisoformat(v) if v else None

        return LiveInputs(
            symbol=doc["symbol"], as_of=datetime.fromisoformat(doc["as_of"]), feed_state=doc["feed_state"], source=doc["source"],
            spot=doc["spot"], spot_time=dt(doc["spot_time"]),
            chain=tuple(ChainRow(r["strike"], Leg(**r["call"]), Leg(**r["put"])) for r in doc["chain"]),
            chain_time=dt(doc["chain_time"]), expiry=date.fromisoformat(doc["expiry"]) if doc["expiry"] else None,
            candles=tuple(doc["candles"]), interval_seconds=doc.get("interval_seconds", 60),
        )


def from_snapshot(snapshot: Any, candles: list[dict[str, Any]], feed_state: str, as_of: datetime) -> LiveInputs:
    """Adapter from the app's DashboardSnapshot (duck-typed) to LiveInputs."""
    def leg(x: Any) -> Leg:
        return Leg(float(x.ltp), float(x.change), int(x.oi), int(x.oi_change), float(x.iv), float(x.delta), x.volume)

    expiry = None
    try:
        expiry = datetime.strptime(str(snapshot.expiry), "%d %b %Y").date() if snapshot.expiry else None
    except ValueError:
        try:
            expiry = date.fromisoformat(str(snapshot.expiry))
        except ValueError:
            expiry = None
    return LiveInputs(
        symbol=snapshot.symbol, as_of=as_of, feed_state=feed_state, source=snapshot.feed.source,
        spot=float(snapshot.spot.ltp), spot_time=snapshot.spot.timestamp,
        chain=tuple(ChainRow(r.strike, leg(r.call), leg(r.put)) for r in snapshot.option_chain),
        chain_time=snapshot.feed.last_tick, expiry=expiry, candles=tuple(candles),
    )
