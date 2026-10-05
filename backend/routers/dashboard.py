import csv
import io
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from lib.access import require_admin
from lib.candles import candle_store
from lib.db import db
from lib.feed_worker import feed_worker
from lib.kotak_adapter import demo_snapshot
from lib.settings import settings
from lib.market_read import build_market_read, neutral_label
from models.dashboard import (
    AlertSettings,
    DashboardSnapshot,
    FeedHealth,
    FeedStatus,
    ExportArchiveItem,
    ExportArchiveResponse,
    IndexSymbol,
    MarketStructure,
    OpeningReport,
    SignalSnapshot,
    SpotSnapshot,
)


router = APIRouter(prefix="/market-data", tags=["market-data"])
IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_BATCH = 50
CSV_COLUMNS = [
    "captured_at", "trading_day", "index", "source", "feed_state", "expiry",
    "spot_ltp", "spot_change", "spot_change_pct", "spot_high", "spot_low",
    "pcr", "max_pain", "pcr_lean", "strike", "is_atm",
    "call_ltp", "call_change", "call_oi", "call_oi_change", "call_iv", "call_delta",
    "put_ltp", "put_change", "put_oi", "put_oi_change", "put_iv", "put_delta",
]


def _safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _verified_document(document: dict, symbol: str, trading_day: str) -> bool:
    snapshot = document.get("snapshot", {})
    feed = snapshot.get("feed", {}) if isinstance(snapshot, dict) else {}
    spot = snapshot.get("spot", {}) if isinstance(snapshot, dict) else {}
    chain = snapshot.get("option_chain", []) if isinstance(snapshot, dict) else []
    return bool(
        document.get("symbol") == symbol
        and document.get("trading_day") == trading_day
        and document.get("source") == "KOTAK_NEO"
        and document.get("verified") is True
        and feed.get("source") == "KOTAK_NEO"
        and feed.get("last_tick")
        and float(spot.get("ltp", 0)) > 0
        and len(chain) >= 21
    )


def _history_rows(document: dict) -> list[list[object]]:
    snapshot = document["snapshot"]
    spot = snapshot["spot"]
    structure = snapshot["structure"]
    signal = snapshot["signal"]
    common: list[object] = [
        document["captured_at"].isoformat() if isinstance(document["captured_at"], datetime) else document["captured_at"],
        document["trading_day"],
        document["symbol"],
        "KOTAK_NEO",
        document.get("feed_state", snapshot["feed"]["state"]),
        snapshot["expiry"],
        spot["ltp"], spot["change"], spot["pct_change"], spot["high"], spot["low"],
        structure["pcr"], structure["max_pain"],
        neutral_label(signal["recommendation"]),
    ]
    rows: list[list[object]] = []
    for option in snapshot["option_chain"]:
        call, put = option["call"], option["put"]
        rows.append(common + [
            option["strike"], option["is_atm"],
            call["ltp"], call["change"], call["oi"], call["oi_change"], call["iv"], call["delta"],
            put["ltp"], put["change"], put["oi"], put["oi_change"], put["iv"], put["delta"],
        ])
    return rows


def _verified_filter(symbol: str, trading_day: str) -> dict:
    """The database-side version of _verified_document(): what counts as a verified Kotak snapshot."""
    return {
        "symbol": symbol,
        "trading_day": trading_day,
        "source": "KOTAK_NEO",
        "verified": True,
        "snapshot.feed.source": "KOTAK_NEO",
        "snapshot.feed.last_tick": {"$nin": [None, ""]},
        "snapshot.spot.ltp": {"$gt": 0},
        "snapshot.option_chain.20": {"$exists": True},  # at least 21 strikes
    }


async def _archive_stats(symbol: str, trading_day: str) -> dict:
    """Snapshot count, row count and first/last capture without loading the snapshots themselves."""
    pipeline = [
        {"$match": _verified_filter(symbol, trading_day)},
        {"$group": {"_id": None, "snapshots": {"$sum": 1}, "rows": {"$sum": {"$size": "$snapshot.option_chain"}}, "first": {"$min": "$captured_at"}, "last": {"$max": "$captured_at"}}},
    ]
    result = await db.market_snapshot_history.aggregate(pipeline).to_list(1)
    if result:
        return {"snapshots": int(result[0]["snapshots"]), "rows": int(result[0]["rows"]), "first": result[0]["first"], "last": result[0]["last"]}
    documents = await _verified_export_documents(symbol, trading_day)  # no history yet: at most the one latest snapshot
    captures = [document.get("captured_at") for document in documents if isinstance(document.get("captured_at"), datetime)]
    return {
        "snapshots": len(documents),
        "rows": sum(len(document.get("snapshot", {}).get("option_chain", [])) for document in documents),
        "first": min(captures) if captures else None,
        "last": max(captures) if captures else None,
    }


async def _verified_export_documents(symbol: str, trading_day: str) -> list[dict]:
    documents = await db.market_snapshot_history.find(
        {"symbol": symbol, "trading_day": trading_day, "source": "KOTAK_NEO", "verified": True},
        {"_id": 0},
    ).sort("captured_at", 1).limit(5000).to_list(5000)
    documents = [document for document in documents if _verified_document(document, symbol, trading_day)]
    if documents:
        return documents
    latest = await db.market_snapshots.find_one({"_id": symbol}, {"_id": 0})
    if not latest:
        return []
    last_tick = latest.get("feed", {}).get("last_tick")
    aware_tick = last_tick.replace(tzinfo=timezone.utc) if isinstance(last_tick, datetime) and last_tick.tzinfo is None else last_tick
    fallback = {
        "symbol": symbol,
        "trading_day": aware_tick.astimezone(IST).date().isoformat() if isinstance(aware_tick, datetime) else "",
        "captured_at": aware_tick,
        "source": "KOTAK_NEO",
        "verified": True,
        "feed_state": latest.get("feed", {}).get("state"),
        "snapshot": latest,
    }
    return [fallback] if _verified_document(fallback, symbol, trading_day) else []


def waiting_live_snapshot(symbol: IndexSymbol, status: FeedStatus) -> DashboardSnapshot:
    now = datetime.now(timezone.utc)
    index_status = next((item for item in status.indices if item.symbol == symbol), None)
    state = index_status.state if index_status else status.state
    expiry = index_status.expiry if index_status else None
    atm_strike = index_status.atm_strike if index_status else None
    subscriptions = (index_status.option_subscriptions + 1) if index_status else 0
    return DashboardSnapshot(
        symbol=symbol,
        expiry=expiry or "Pending live contract",
        spot=SpotSnapshot(symbol=symbol, ltp=0, change=0, pct_change=0, high=0, low=0, timestamp=None),
        option_chain=[],
        structure=MarketStructure(pcr=0, max_pain=atm_strike or 0, bias="NEUTRAL", oi_buildup=status.message),
        signal=SignalSnapshot(recommendation="UNAVAILABLE", confidence=0, reasons=[status.message], timestamp=None),
        feed=FeedHealth(
            state=state,
            source="KOTAK_NEO",
            last_tick=None,
            heartbeat_ms=0,
            subscriptions=subscriptions,
            divider_status="VERIFIED" if status.divider_verified else "PENDING",
        ),
        as_of=now,
    )


@router.get("/dashboard", response_model=DashboardSnapshot)
async def get_dashboard(symbol: IndexSymbol = Query(default="NIFTY")) -> DashboardSnapshot:
    if settings.mode == "LIVE":
        if symbol not in {"NIFTY", "BANKNIFTY", "FINNIFTY"}:
            raise HTTPException(status_code=503, detail="The live SFeed worker supports NIFTY, BANKNIFTY, and FINNIFTY")
        current = feed_worker.snapshot_for(symbol)
        if not current:
            return waiting_live_snapshot(symbol, feed_worker.status())
        snapshot = current.model_copy(deep=True)
        snapshot.signal.recommendation = neutral_label(snapshot.signal.recommendation)  # snapshots saved before this change
        status = feed_worker.status()
        index_status = next((item for item in status.indices if item.symbol == symbol), None)
        snapshot.feed.state = index_status.state if index_status else status.state
        snapshot.feed.subscriptions = (index_status.option_subscriptions + 1) if index_status else status.subscriptions
        snapshot.feed.divider_status = "VERIFIED" if status.divider_verified else "PENDING"
        if index_status and index_status.last_tick:
            snapshot.feed.last_tick = index_status.last_tick
            snapshot.feed.heartbeat_ms = max(0, int((datetime.now(timezone.utc) - index_status.last_tick).total_seconds() * 1000))
        return snapshot
    return demo_snapshot(symbol)


@router.get("/feed-status", response_model=FeedStatus)
async def get_feed_status() -> FeedStatus:
    return feed_worker.status()


@router.get("/feed-fields")
async def get_feed_fields(owner: dict = Depends(require_admin)) -> dict:
    """Owner only: which fields Kotak really sends on index, option and stock messages (first message of each kind), and whether any looks like bid/ask/depth."""
    import re

    feed = feed_worker.feed
    samples = dict(feed.field_samples) if feed else {}
    looks = re.compile(r"bid|ask|buy|sell|depth|best|qty|quantity|orders", re.I)
    return {"connected": bool(feed and feed.authenticated), "kinds": {k: {"fields": sorted(v), "bid_ask_like": {n: v[n] for n in v if looks.search(n)}, "sample": v} for k, v in samples.items()},
            "note": "A kind appears after its first message arrives. 'premium' means SENSEX or a stock."}


@router.get("/alert-settings", response_model=AlertSettings)
async def get_alert_settings() -> AlertSettings:
    return feed_worker.alert_settings


@router.put("/alert-settings", response_model=AlertSettings, dependencies=[Depends(require_admin)])
async def update_alert_settings(request: AlertSettings) -> AlertSettings:
    return await feed_worker.update_alert_settings(request)


@router.get("/opening-report", response_model=OpeningReport | None)
async def get_opening_report() -> OpeningReport | None:
    return feed_worker.opening_report


@router.get("/export.csv")
async def export_current_trading_day(symbol: IndexSymbol = Query(...)) -> StreamingResponse:
    trading_day = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    query = _verified_filter(symbol, trading_day)
    filename = f"{symbol}-{trading_day}-kotak-live.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if await db.market_snapshot_history.find_one(query, {"_id": 1}) is not None:

        async def stream_history():
            output = io.StringIO()
            csv.writer(output, lineterminator="\n").writerow(CSV_COLUMNS)
            yield output.getvalue()
            cursor = db.market_snapshot_history.find(query, {"_id": 0}).sort("captured_at", 1).batch_size(ARCHIVE_BATCH)
            async for document in cursor:  # one small batch in memory at a time
                if not _verified_document(document, symbol, trading_day):
                    continue
                output = io.StringIO()
                writer = csv.writer(output, lineterminator="\n")
                for row in _history_rows(document):
                    writer.writerow([_safe_csv_cell(value) for value in row])
                yield output.getvalue()

        return StreamingResponse(stream_history(), media_type="text/csv; charset=utf-8", headers=headers)

    documents = await _verified_export_documents(symbol, trading_day)  # no history yet: the latest snapshot only
    if not documents:
        raise HTTPException(status_code=404, detail="No verified Kotak live data is available for this index today")

    def stream_csv():
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        yield output.getvalue()
        for document in documents:
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            for row in _history_rows(document):
                writer.writerow([_safe_csv_cell(value) for value in row])
            yield output.getvalue()

    filename = f"{symbol}-{trading_day}-kotak-live.csv"
    return StreamingResponse(
        stream_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/export-archive", response_model=ExportArchiveResponse)
async def get_export_archive() -> ExportArchiveResponse:
    trading_day = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
    manifest = await db.export_manifests.find_one({"trading_day": trading_day}, {"_id": 0, "prepared_at": 1})
    items: list[ExportArchiveItem] = []
    for symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        stats = await _archive_stats(symbol, trading_day)
        items.append(
            ExportArchiveItem(
                symbol=symbol,
                available=stats["snapshots"] > 0,
                snapshot_count=stats["snapshots"],
                row_count=stats["rows"],
                first_capture=stats["first"],
                last_capture=stats["last"],
                filename=f"{symbol}-{trading_day}-kotak-live.csv" if stats["snapshots"] else None,
            )
        )
    return ExportArchiveResponse(
        trading_day=trading_day,
        prepared_at=manifest.get("prepared_at") if manifest else None,
        items=items,
    )


@router.get("/candles")
async def get_index_candles(
    symbol: IndexSymbol = Query(default="NIFTY"),
    interval: int = Query(default=1, description="Candle size in minutes: 1, 5 or 15"),
    day: date | None = Query(default=None, description="Trading day (YYYY-MM-DD); defaults to today (IST)"),
) -> dict:
    """Read-only index candles built from live Kotak index ticks. Never synthetic, never backfilled."""
    if interval not in (1, 5, 15):
        raise HTTPException(status_code=422, detail="interval must be 1, 5 or 15")
    return await candle_store.get(symbol, interval, day)


@router.get("/market-read")
async def get_market_read(symbol: IndexSymbol = Query(default="NIFTY")) -> dict:
    """Read-only, descriptive readings: PCR lean, 5 and 15 minute index moves, 15 minute range. No recommendation."""
    if settings.mode == "LIVE":
        snapshot = feed_worker.snapshot_for(symbol)
        status = feed_worker.status()
        index_status = next((item for item in status.indices if item.symbol == symbol), None)
        feed_state = index_status.state if index_status else status.state
    else:
        snapshot = demo_snapshot(symbol)
        feed_state = "DEMO"
    candles = (await candle_store.get(symbol, 1))["candles"]
    return build_market_read(snapshot, candles, feed_state)
