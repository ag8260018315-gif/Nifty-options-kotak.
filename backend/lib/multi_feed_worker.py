import asyncio
import logging
import math
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from lib.db import db
from lib.instruments import OptionContract, instrument_repository
from lib.kotak_client import kotak_client
from lib.kotak_feed import FeedAuthError, KotakSFeed
from lib.settings import settings
from models.dashboard import (
    AlertSettings,
    DashboardSnapshot,
    FeedAlert,
    FeedHealth,
    FeedStatus,
    IndexFeedStatus,
    MarketStructure,
    OpeningIndexHealth,
    OpeningReport,
    OptionLeg,
    OptionRow,
    SignalSnapshot,
    SpotSnapshot,
)


logger = logging.getLogger(__name__)


IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc
LIVE_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
INDEX_SUBSCRIPTIONS = {
    "NIFTY": "nse_cm|Nifty 50",
    "BANKNIFTY": "nse_cm|Nifty Bank",
    "FINNIFTY": "nse_cm|Nifty Fin Service",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _market_open(now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(IST)
    return local.weekday() < 5 and time(9, 15) <= local.time() < time(15, 30)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _option_price(spot: float, strike: float, years: float, rate: float, sigma: float, is_call: bool) -> float:
    if years <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return max(spot - strike, 0) if is_call else max(strike - spot, 0)
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + sigma * sigma / 2) * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discounted = strike * math.exp(-rate * years)
    return spot * _normal_cdf(d1) - discounted * _normal_cdf(d2) if is_call else discounted * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def _greeks(spot: float, strike: float, premium: float, expiry: date, is_call: bool) -> tuple[float, float]:
    expiry_at = datetime.combine(expiry, time(15, 30), tzinfo=IST).astimezone(UTC)
    years = max((expiry_at - datetime.now(UTC)).total_seconds() / (365 * 24 * 3600), 1 / (365 * 24))
    intrinsic = max(spot - strike, 0) if is_call else max(strike - spot, 0)
    if premium <= intrinsic or spot <= 0:
        return 0.0, 1.0 if is_call and spot > strike else -1.0 if not is_call and spot < strike else 0.0
    low, high = 0.01, 3.0
    for _ in range(50):
        sigma = (low + high) / 2
        if _option_price(spot, strike, years, 0.065, sigma, is_call) > premium:
            high = sigma
        else:
            low = sigma
    sigma = (low + high) / 2
    d1 = (math.log(spot / strike) + (0.065 + sigma * sigma / 2) * years) / (sigma * math.sqrt(years))
    delta = _normal_cdf(d1) if is_call else _normal_cdf(d1) - 1
    return round(sigma * 100, 2), round(delta, 3)


@dataclass
class IndexRuntime:
    symbol: str
    current_atm: int | None = None
    current_expiry: date | None = None
    strike_step: int = 0
    contracts: dict[str, OptionContract] = field(default_factory=dict)
    option_ticks: dict[str, dict[str, Any]] = field(default_factory=dict)
    oi_baseline: dict[str, int] = field(default_factory=dict)
    index_tick: dict[str, Any] | None = None
    last_tick: datetime | None = None
    snapshot: DashboardSnapshot | None = None
    last_atm_alert: datetime | None = None
    last_alerted_atm: int | None = None
    last_history_at: datetime | None = None


class MultiIndexFeedWorker:
    def __init__(self) -> None:
        self.feed: KotakSFeed | None = None
        self.socket_connected = False
        self.authenticated = False
        self.divider_verified = False
        self.subscription_count = 0
        self.runtimes = {symbol: IndexRuntime(symbol=symbol) for symbol in LIVE_SYMBOLS}
        self.alerts: deque[FeedAlert] = deque(maxlen=20)
        self.alert_ids: set[str] = set()
        self.alert_settings = AlertSettings()
        self.opening_report: OpeningReport | None = None
        self.error_message = "Waiting for Kotak SFeed"
        logger.info("FEED_WORKER_START_SFE event=startup symbols=%s mode=%s live_configured=%s", list(LIVE_SYMBOLS), settings.mode, getattr(settings, "live_configured", False))

    def state_for(self, symbol: str) -> str:
        if settings.mode != "LIVE":
            return "DEMO"
        if not _market_open():
            return "MARKET_CLOSED"
        if not kotak_client.connected:
            return "EXPIRED"
        last_tick = self.runtimes[symbol].last_tick
        if not last_tick or (datetime.now(UTC) - last_tick).total_seconds() > 5:
            logger.warning("FEED_WORKER_STALE symbol=%s last_tick=%s age_seconds=%.1f", symbol, last_tick.isoformat() if last_tick else None, (datetime.now(UTC) - last_tick).total_seconds() if last_tick else float("inf"))
            return "STALE"
        return "LIVE"

    def state(self) -> str:
        states = [self.state_for(symbol) for symbol in LIVE_SYMBOLS]
        if states[0] == "MARKET_CLOSED":
            return "MARKET_CLOSED"
        if all(state == "LIVE" for state in states):
            return "LIVE"
        if any(state == "EXPIRED" for state in states):
            return "EXPIRED"
        if all(state == "DEMO" for state in states):
            return "DEMO"
        return "STALE"

    def status(self) -> FeedStatus:
        state = self.state()
        index_statuses = [
            IndexFeedStatus(
                symbol=symbol,
                state=self.state_for(symbol),
                last_tick=runtime.last_tick,
                atm_strike=runtime.current_atm,
                expiry=runtime.current_expiry.isoformat() if runtime.current_expiry else None,
                option_subscriptions=len(runtime.contracts),
                paired_strikes=self._paired_strikes(runtime),
                expected_pairs=21,
            )
            for symbol, runtime in self.runtimes.items()
        ]
        messages = {
            "LIVE": "Kotak SFeed is fresh for NIFTY, BANKNIFTY, and FINNIFTY.",
            "STALE": "One or more index feeds have no fresh tick in the last 5 seconds.",
            "EXPIRED": "Kotak session expired; automated TOTP re-login is required.",
            "MARKET_CLOSED": "NSE derivatives market is outside the 09:15–15:30 IST session.",
            "DEMO": "Explicit DEMO mode is active.",
        }
        last_ticks = [runtime.last_tick for runtime in self.runtimes.values() if runtime.last_tick]
        nifty = self.runtimes["NIFTY"]
        return FeedStatus(
            state=state,
            connected=self.socket_connected,
            authenticated=self.authenticated,
            last_tick=max(last_ticks) if last_ticks else None,
            subscriptions=self.subscription_count,
            divider_verified=self.divider_verified,
            atm_strike=nifty.current_atm,
            expiry=nifty.current_expiry.isoformat() if nifty.current_expiry else None,
            message=messages.get(state, self.error_message),
            alerts=list(self.alerts),
            indices=index_statuses,
            opening_report=self.opening_report,
            alert_settings=self.alert_settings,
        )

    def snapshot_for(self, symbol: str) -> DashboardSnapshot | None:
        runtime = self.runtimes.get(symbol)
        return runtime.snapshot if runtime else None

    async def update_alert_settings(self, new_settings: AlertSettings) -> AlertSettings:
        self.alert_settings = new_settings
        await db.feed_settings.replace_one({"_id": "alerts"}, {"_id": "alerts", **new_settings.model_dump()}, upsert=True)
        return self.alert_settings

    async def run(self) -> None:
        logger.info("FEED_WORKER_START_SFE event=run_start mode=%s live_configured=%s", settings.mode, bool(getattr(settings, "live_configured", False)))
        await self._restore_state()
        if settings.mode != "LIVE" or not settings.live_configured:
            return
        delay = 1.0
        while True:
            try:
                session = await kotak_client.ensure_session()
                logger.info("FEED_WORKER_SESSION_READY event=session_ready connected=%s", kotak_client.connected)
                for symbol, runtime in self.runtimes.items():
                    active = await instrument_repository.active_contracts(symbol)
                    expiry = min(contract.expiry for contract in active)
                    if runtime.current_expiry and expiry != runtime.current_expiry:
                        await self._add_alert("ROLL_REQUIRED", f"roll-{symbol}-{expiry}", f"{symbol} expiry rolled", f"Option subscriptions moved from {runtime.current_expiry} to {expiry}.", symbol)
                    runtime.current_expiry = expiry
                if not _market_open():
                    await self._prepare_closing_manifest()
                    self.socket_connected = False
                    self.authenticated = False
                    self.subscription_count = 0
                    self.error_message = "NSE market is closed; SFeed will start automatically at 09:15 IST"
                    logger.warning("FEED_WORKER_SFE_ERROR event=disconnect reason=market_closed")
                    delay = 1.0
                    await asyncio.sleep(30)
                    continue
                initial_options: list[str] = []
                for symbol, runtime in self.runtimes.items():
                    if runtime.current_atm:
                        selected, step = await instrument_repository.select_atm_window(symbol, runtime.current_atm)
                        runtime.strike_step = step
                        runtime.contracts = {contract.token: contract for contract in selected}
                        initial_options.extend(f"nse_fo|{contract.token}" for contract in selected)
                self.feed = KotakSFeed(session, self._on_message)
                self.error_message = "Connecting to Kotak SFeed"
                logger.info("FEED_WORKER_READY event=feed_start option_subscriptions=%s", len(initial_options))
                await self.feed.run_once(list(INDEX_SUBSCRIPTIONS.values()), initial_options)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except FeedAuthError:
                self.error_message = "Kotak SFeed authentication expired; re-login scheduled"
                self.authenticated = False
                self.socket_connected = False
                logger.warning("FEED_WORKER_SFE_ERROR event=feed_auth_error")
                kotak_client.clear_session()
                await db.kotak_sessions.update_one({"_id": "current"}, {"$set": {"expires_at": 0}})
            except Exception as exc:
                self.error_message = f"Kotak SFeed reconnecting after {type(exc).__name__}"
                self.socket_connected = False
                self.authenticated = False
                logger.warning("FEED_WORKER_SFE_ERROR event=feed_error kind=%s", type(exc).__name__)
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, 30)

    async def _on_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "auth":
            self.divider_verified = bool(message.get("dividers"))
            if message.get("message_code") == 1117:
                self.socket_connected = True
                self.authenticated = True
            return
        if message_type == "ready":
            self.subscription_count = int(message.get("subscriptions", 0))
            logger.info("FEED_WORKER_READY event=ready subscriptions=%s", self.subscription_count)
            return
        if message_type != "tick":
            return
        tick = message.get("tick", {})
        if tick.get("kind") == "index":
            symbol = self._index_symbol(tick)
            if not symbol:
                return
            runtime = self.runtimes[symbol]
            runtime.index_tick = tick
            runtime.last_tick = datetime.now(UTC)
            if symbol == "NIFTY":
                logger.info("FEED_WORKER_FIRST_INDEX_TICK symbol=%s ltp=%.2f", symbol, float(tick.get("ltp", 0)))
            await self._shift_atm_if_needed(symbol, float(tick.get("ltp", 0)))
            await self._publish_snapshot(symbol)
            await self._check_timed_alerts(symbol)
        elif tick.get("kind") == "option":
            token = str(tick.get("token", ""))
            for symbol, runtime in self.runtimes.items():
                if token in runtime.contracts:
                    runtime.option_ticks[token] = tick
                    runtime.oi_baseline.setdefault(token, int(tick.get("oi", 0)))
                    logger.info("FEED_WORKER_FIRST_OPTION_TICK symbol=%s token=%s", symbol, token)
                    await self._publish_snapshot(symbol)
                    break
        await self._maybe_opening_report()

    def _index_symbol(self, tick: dict[str, Any]) -> str | None:
        name = str(tick.get("name", "")).upper()
        if "FIN" in name and ("NIFTY" in name or "SERVICE" in name):
            return "FINNIFTY"
        if "BANK" in name:
            return "BANKNIFTY"
        if "NIFTY" in name:
            return "NIFTY"
        token = str(tick.get("token", ""))
        return "NIFTY" if token == "26000" else "BANKNIFTY" if token == "26009" else None

    async def _shift_atm_if_needed(self, symbol: str, spot: float) -> None:
        if spot <= 0:
            return
        runtime = self.runtimes[symbol]
        active = await instrument_repository.active_contracts(symbol)
        strikes = sorted({contract.strike for contract in active})
        new_atm = min(strikes, key=lambda strike: abs(strike - spot))
        if new_atm == runtime.current_atm:
            return
        old_atm = runtime.current_atm
        selected, step = await instrument_repository.select_atm_window(symbol, new_atm)
        runtime.current_atm = new_atm
        runtime.current_expiry = min(contract.expiry for contract in selected)
        runtime.strike_step = step
        runtime.contracts = {contract.token: contract for contract in selected}
        runtime.option_ticks = {token: tick for token, tick in runtime.option_ticks.items() if token in runtime.contracts}
        await self._resubscribe_all_options()
        if old_atm is None:
            runtime.last_alerted_atm = new_atm
            return
        if self._alert_allowed() and self._atm_alert_due(runtime, new_atm):
            local = datetime.now(UTC).astimezone(IST)
            await self._add_alert("ATM_SHIFT", f"atm-{symbol}-{local:%Y%m%d%H%M}-{new_atm}", f"{symbol} ATM shifted", f"ATM moved from {old_atm} to {new_atm}; the ±10 strike window was resubscribed.", symbol)
            runtime.last_alerted_atm = new_atm
            runtime.last_atm_alert = datetime.now(UTC)

    async def _resubscribe_all_options(self) -> None:
        if not self.feed:
            return
        tokens = [f"nse_fo|{contract.token}" for runtime in self.runtimes.values() for contract in runtime.contracts.values()]
        await self.feed.replace_option_tokens(tokens)

    def _atm_alert_due(self, runtime: IndexRuntime, new_atm: int) -> bool:
        baseline = runtime.last_alerted_atm if runtime.last_alerted_atm is not None else runtime.current_atm
        threshold = max(runtime.strike_step, 1) * self.alert_settings.atm_shift_steps
        moved = baseline is None or abs(new_atm - baseline) >= threshold
        cooled = runtime.last_atm_alert is None or (datetime.now(UTC) - runtime.last_atm_alert).total_seconds() >= self.alert_settings.cooldown_seconds
        return moved and cooled

    def _alert_allowed(self) -> bool:
        local_time = datetime.now(UTC).astimezone(IST).time().replace(second=0, microsecond=0)
        start = time.fromisoformat(self.alert_settings.quiet_start)
        end = time.fromisoformat(self.alert_settings.quiet_end)
        in_quiet = start <= local_time < end if start < end else local_time >= start or local_time < end
        return not in_quiet

    def _leg(self, contract: OptionContract, tick: dict[str, Any], spot: float) -> OptionLeg:
        premium = float(tick.get("ltp", 0))
        iv, delta = _greeks(spot, contract.strike, premium, contract.expiry, contract.option_type == "CE")
        oi = int(tick.get("oi", 0))
        runtime = self.runtimes[contract.underlying]
        return OptionLeg(ltp=round(premium, 2), change=round(float(tick.get("change", 0)), 2), oi=oi, oi_change=oi - runtime.oi_baseline.get(contract.token, oi), iv=iv, delta=delta)

    async def _publish_snapshot(self, symbol: str) -> None:
        runtime = self.runtimes[symbol]
        if not runtime.index_tick or not runtime.current_atm or not runtime.current_expiry or not runtime.last_tick:
            return
        by_strike: dict[int, dict[str, tuple[OptionContract, dict[str, Any]]]] = {}
        for token, contract in runtime.contracts.items():
            tick = runtime.option_ticks.get(token)
            if tick:
                by_strike.setdefault(contract.strike, {})[contract.option_type] = (contract, tick)
        complete = {strike: pair for strike, pair in by_strike.items() if "CE" in pair and "PE" in pair}
        if len(complete) < 3:
            return
        spot = float(runtime.index_tick.get("ltp", 0))
        rows = [OptionRow(strike=strike, call=self._leg(pair["CE"][0], pair["CE"][1], spot), put=self._leg(pair["PE"][0], pair["PE"][1], spot), is_atm=strike == runtime.current_atm) for strike, pair in complete.items()]
        call_oi = sum(row.call.oi for row in rows)
        put_oi = sum(row.put.oi for row in rows)
        pcr = round(put_oi / call_oi, 2) if call_oi else 0.0
        max_pain = min((row.strike for row in rows), key=lambda settlement: sum(max(settlement - row.strike, 0) * row.call.oi + max(row.strike - settlement, 0) * row.put.oi for row in rows))
        bias = "BULLISH" if pcr >= 1.05 else "BEARISH" if pcr <= 0.85 else "NEUTRAL"
        recommendation = "BUY CALLS" if bias == "BULLISH" else "BUY PUTS" if bias == "BEARISH" else "WAIT"
        close = float(runtime.index_tick.get("close", 0))
        snapshot = DashboardSnapshot(
            symbol=symbol,
            expiry=runtime.current_expiry.strftime("%d %b %Y"),
            spot=SpotSnapshot(symbol=symbol, ltp=spot, change=round(spot - close, 2) if close else 0, pct_change=float(runtime.index_tick.get("change_pct", 0)), high=float(runtime.index_tick.get("high", spot)), low=float(runtime.index_tick.get("low", spot)), timestamp=runtime.last_tick),
            option_chain=rows,
            structure=MarketStructure(pcr=pcr, max_pain=max_pain, bias=bias, oi_buildup=f"Live OI: {put_oi:,} puts vs {call_oi:,} calls"),
            signal=SignalSnapshot(recommendation=recommendation, confidence=min(85, 55 + int(abs(pcr - 1) * 100)), reasons=[f"Live PCR is {pcr:.2f}", f"Calculated max pain is {max_pain}", f"Spot is {spot:,.2f} with ATM at {runtime.current_atm}"], timestamp=runtime.last_tick),
            feed=FeedHealth(state=self.state_for(symbol), source="KOTAK_NEO", last_tick=runtime.last_tick, heartbeat_ms=max(0, int((datetime.now(UTC) - runtime.last_tick).total_seconds() * 1000)), subscriptions=self.subscription_count, divider_status="VERIFIED" if self.divider_verified else "PENDING"),
            as_of=runtime.last_tick,
        )
        runtime.snapshot = snapshot
        await db.market_snapshots.replace_one({"_id": symbol}, {"_id": symbol, **snapshot.model_dump()}, upsert=True)
        logger.info("FEED_WORKER_SNAPSHOT_WRITTEN symbol=%s rows=%s pcr=%.2f", symbol, len(rows), pcr)
        if runtime.last_history_at is None or (runtime.last_tick - runtime.last_history_at).total_seconds() >= 5:
            local_day = runtime.last_tick.astimezone(IST).date().isoformat()
            await db.market_snapshot_history.insert_one(
                {
                    "symbol": symbol,
                    "trading_day": local_day,
                    "captured_at": runtime.last_tick,
                    "source": "KOTAK_NEO",
                    "verified": True,
                    "feed_state": self.state_for(symbol),
                    "snapshot": snapshot.model_dump(),
                }
            )
            runtime.last_history_at = runtime.last_tick
        if symbol == "FINNIFTY" and len(rows) >= 21 and self._alert_allowed():
            day_key = runtime.last_tick.astimezone(IST).date().isoformat()
            await self._add_alert("EXPORT_READY", f"export-ready-{symbol}-{day_key}", "FINNIFTY CSV is ready", "The first verified FINNIFTY spot and 21 paired CE/PE rows are now available to export.", symbol)

    def _paired_strikes(self, runtime: IndexRuntime) -> int:
        sides: dict[int, set[str]] = {}
        for token, contract in runtime.contracts.items():
            if token in runtime.option_ticks:
                sides.setdefault(contract.strike, set()).add(contract.option_type)
        return sum(1 for values in sides.values() if values == {"CE", "PE"})

    async def _maybe_opening_report(self) -> None:
        local = datetime.now(UTC).astimezone(IST)
        if (self.opening_report and self.opening_report.session_date == local.date().isoformat()) or local.time() < time(9, 16):
            return
        checks: list[OpeningIndexHealth] = []
        for symbol, runtime in self.runtimes.items():
            fresh = bool(runtime.last_tick and (datetime.now(UTC) - runtime.last_tick).total_seconds() < 10)
            paired = self._paired_strikes(runtime)
            checks.append(OpeningIndexHealth(symbol=symbol, fresh_spot=fresh, divider_verified=self.divider_verified, option_window_complete=len(runtime.contracts) >= 42, paired_ce_pe_complete=paired, socket_connected=self.socket_connected))
        passed = all(item.fresh_spot and item.divider_verified and item.option_window_complete and item.paired_ce_pe_complete and item.socket_connected for item in checks)
        report = OpeningReport(session_date=local.date().isoformat(), generated_at=datetime.now(UTC), status="PASS" if passed else "WARN", indices=checks)
        self.opening_report = report
        await db.opening_reports.replace_one({"session_date": report.session_date}, report.model_dump(), upsert=True)
        await self._add_alert("OPENING_REPORT", f"opening-{report.session_date}", f"09:16 opening check: {report.status}", "NIFTY, BANKNIFTY, and FINNIFTY opening health report is ready.", None)

    async def _check_timed_alerts(self, symbol: str) -> None:
        runtime = self.runtimes[symbol]
        if not runtime.current_expiry or not self._alert_allowed():
            return
        local = datetime.now(UTC).astimezone(IST)
        day_key = local.date().isoformat()
        if local.date() == runtime.current_expiry:
            await self._add_alert("EXPIRY_DAY", f"expiry-{symbol}-{day_key}", f"{symbol} expiry day", f"The selected contract expires today ({runtime.current_expiry}).", symbol)
        if local.weekday() < 5 and time(15, 15) <= local.time() < time(15, 30):
            await self._add_alert("NEAR_CLOSE", f"close-{symbol}-{day_key}", f"{symbol} expiry window near close", "NSE closes in under 15 minutes; review liquidity and expiry exposure.", symbol)

    async def _prepare_closing_manifest(self) -> None:
        local = datetime.now(UTC).astimezone(IST)
        if local.weekday() >= 5 or local.time() < time(15, 31):
            return
        trading_day = local.date().isoformat()
        if await db.export_manifests.find_one({"trading_day": trading_day}, {"_id": 1}):
            return
        items: list[dict[str, Any]] = []
        for symbol, runtime in self.runtimes.items():
            history_count = await db.market_snapshot_history.count_documents({"symbol": symbol, "trading_day": trading_day, "source": "KOTAK_NEO", "verified": True})
            snapshot = runtime.snapshot
            has_verified_latest = bool(
                snapshot
                and snapshot.feed.source == "KOTAK_NEO"
                and snapshot.feed.last_tick
                and snapshot.feed.last_tick.astimezone(IST).date().isoformat() == trading_day
                and snapshot.spot.ltp > 0
                and len(snapshot.option_chain) >= 21
            )
            items.append({"symbol": symbol, "available": bool(history_count or has_verified_latest), "snapshot_count": max(history_count, 1 if has_verified_latest else 0)})
        await db.export_manifests.insert_one({"trading_day": trading_day, "prepared_at": datetime.now(UTC), "items": items})

    async def _add_alert(self, alert_type: str, alert_id: str, title: str, message: str, symbol: str | None) -> None:
        if alert_id in self.alert_ids:
            return
        alert = FeedAlert(id=alert_id, type=alert_type, title=title, message=message, created_at=datetime.now(UTC), symbol=symbol)
        self.alert_ids.add(alert_id)
        self.alerts.appendleft(alert)
        await db.feed_alerts.update_one({"id": alert_id}, {"$setOnInsert": alert.model_dump()}, upsert=True)

    async def _restore_state(self) -> None:
        settings_doc = await db.feed_settings.find_one({"_id": "alerts"}, {"_id": 0})
        if settings_doc:
            self.alert_settings = AlertSettings(**settings_doc)
        local_date = datetime.now(UTC).astimezone(IST).date().isoformat()
        report_doc = await db.opening_reports.find_one({"session_date": local_date}, {"_id": 0})
        if report_doc:
            candidate = OpeningReport(**report_doc)
            if {item.symbol for item in candidate.indices} == set(LIVE_SYMBOLS):
                self.opening_report = candidate
        for symbol, runtime in self.runtimes.items():
            document = await db.market_snapshots.find_one({"_id": symbol}, {"_id": 0})
            if not document:
                continue
            try:
                snapshot = DashboardSnapshot(**document)
                snapshot.as_of = _aware(snapshot.as_of) or snapshot.as_of
                snapshot.spot.timestamp = _aware(snapshot.spot.timestamp)
                snapshot.signal.timestamp = _aware(snapshot.signal.timestamp)
                snapshot.feed.last_tick = _aware(snapshot.feed.last_tick)
                runtime.snapshot = snapshot
                runtime.last_tick = snapshot.feed.last_tick
                runtime.current_atm = min(snapshot.option_chain, key=lambda row: abs(row.strike - snapshot.spot.ltp)).strike if snapshot.option_chain else None
            except Exception:
                runtime.snapshot = None
        alert_docs = await db.feed_alerts.find({}, {"_id": 0}).sort("created_at", -1).limit(20).to_list(20)
        for document in reversed(alert_docs):
            try:
                alert = FeedAlert(**document)
                if alert.type == "OPENING_REPORT" and "FINNIFTY" not in alert.message:
                    continue
                alert.created_at = _aware(alert.created_at) or alert.created_at
                self.alerts.appendleft(alert)
                self.alert_ids.add(alert.id)
            except Exception:
                continue
