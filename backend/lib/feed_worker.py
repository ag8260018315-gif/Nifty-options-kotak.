import asyncio
import math
import random
from collections import deque
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Any

from lib.db import db
from lib.instruments import OptionContract, instrument_repository
from lib.kotak_client import kotak_client
from lib.kotak_feed import FeedAuthError, KotakSFeed
from lib.settings import settings
from models.dashboard import (
    DashboardSnapshot,
    FeedAlert,
    FeedHealth,
    FeedStatus,
    MarketStructure,
    OptionLeg,
    OptionRow,
    SignalSnapshot,
    SpotSnapshot,
)


IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


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
    if is_call:
        return spot * _normal_cdf(d1) - discounted * _normal_cdf(d2)
    return discounted * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def _greeks(spot: float, strike: float, premium: float, expiry: date, is_call: bool) -> tuple[float, float]:
    expiry_at = datetime.combine(expiry, time(15, 30), tzinfo=IST).astimezone(UTC)
    years = max((expiry_at - datetime.now(UTC)).total_seconds() / (365 * 24 * 3600), 1 / (365 * 24))
    intrinsic = max(spot - strike, 0) if is_call else max(strike - spot, 0)
    if premium <= intrinsic or spot <= 0:
        return 0.0, 1.0 if is_call and spot > strike else -1.0 if not is_call and spot < strike else 0.0
    low, high = 0.01, 3.0
    for _ in range(50):
        mid = (low + high) / 2
        if _option_price(spot, strike, years, 0.065, mid, is_call) > premium:
            high = mid
        else:
            low = mid
    sigma = (low + high) / 2
    d1 = (math.log(spot / strike) + (0.065 + sigma * sigma / 2) * years) / (sigma * math.sqrt(years))
    delta = _normal_cdf(d1) if is_call else _normal_cdf(d1) - 1
    return round(sigma * 100, 2), round(delta, 3)


class LiveFeedWorker:
    def __init__(self) -> None:
        self.feed: KotakSFeed | None = None
        self.socket_connected = False
        self.authenticated = False
        self.divider_verified = False
        self.last_tick: datetime | None = None
        self.subscription_count = 0
        self.current_atm: int | None = None
        self.current_expiry: date | None = None
        self.contracts: dict[str, OptionContract] = {}
        self.option_ticks: dict[str, dict[str, Any]] = {}
        self.oi_baseline: dict[str, int] = {}
        self.index_tick: dict[str, Any] | None = None
        self.snapshot: DashboardSnapshot | None = None
        self.alerts: deque[FeedAlert] = deque(maxlen=12)
        self.alert_ids: set[str] = set()
        self.error_message = "Waiting for Kotak SFeed"

    def state(self) -> str:
        if settings.mode != "LIVE":
            return "DEMO"
        if not _market_open():
            return "MARKET_CLOSED"
        if not kotak_client.connected:
            return "EXPIRED"
        if not self.last_tick or (datetime.now(UTC) - self.last_tick).total_seconds() > 5:
            return "STALE"
        return "LIVE"

    def status(self) -> FeedStatus:
        state = self.state()
        messages = {
            "LIVE": "Kotak SFeed is authenticated and ticks are fresh.",
            "STALE": "Kotak session is active, but no market tick arrived in the last 5 seconds.",
            "EXPIRED": "Kotak session expired; automated TOTP re-login is required.",
            "MARKET_CLOSED": "NSE derivatives market is outside the 09:15–15:30 IST session.",
            "DEMO": "Explicit DEMO mode is active.",
        }
        return FeedStatus(
            state=state,
            connected=self.socket_connected,
            authenticated=self.authenticated,
            last_tick=self.last_tick,
            subscriptions=self.subscription_count,
            divider_verified=self.divider_verified,
            atm_strike=self.current_atm,
            expiry=self.current_expiry.isoformat() if self.current_expiry else None,
            message=messages.get(state, self.error_message),
            alerts=list(self.alerts),
        )

    async def run(self) -> None:
        await self._restore_snapshot_and_alerts()
        if settings.mode != "LIVE" or not settings.live_configured:
            return
        delay = 1.0
        while True:
            try:
                session = await kotak_client.ensure_session()
                active = await instrument_repository.active_nifty_contracts()
                expiry = min(contract.expiry for contract in active)
                if self.current_expiry and expiry != self.current_expiry:
                    await self._add_alert("ROLL_REQUIRED", f"roll-{expiry.isoformat()}", "NIFTY expiry rolled", f"Option subscriptions moved from {self.current_expiry.isoformat()} to {expiry.isoformat()}.")
                self.current_expiry = expiry
                if not _market_open():
                    self.socket_connected = False
                    self.authenticated = False
                    self.subscription_count = 0
                    self.error_message = "NSE market is closed; SFeed will start automatically at 09:15 IST"
                    delay = 1.0
                    await asyncio.sleep(30)
                    continue
                initial_tokens: list[str] = []
                if self.current_atm:
                    selected, _ = await instrument_repository.select_atm_window(self.current_atm)
                    self.contracts = {contract.token: contract for contract in selected}
                    initial_tokens = [f"nse_fo|{contract.token}" for contract in selected]
                self.feed = KotakSFeed(session, self._on_message)
                self.error_message = "Connecting to Kotak SFeed"
                await self.feed.run_once([f"nse_cm|{settings.nifty_index_token}"], initial_tokens)
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except FeedAuthError:
                self.error_message = "Kotak SFeed authentication expired; re-login scheduled"
                self.authenticated = False
                self.socket_connected = False
                kotak_client.clear_session()
                await db.kotak_sessions.update_one({"_id": "current"}, {"$set": {"expires_at": 0}})
            except Exception as exc:
                self.error_message = f"Kotak SFeed reconnecting after {type(exc).__name__}"
                self.socket_connected = False
                self.authenticated = False
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
            return
        if message_type != "tick":
            return
        tick = message.get("tick", {})
        self.last_tick = datetime.now(UTC)
        if tick.get("kind") == "index":
            self.index_tick = tick
            await self._shift_atm_if_needed(float(tick.get("ltp", 0)))
        elif tick.get("kind") == "option":
            token = str(tick.get("token", ""))
            if token in self.contracts:
                self.option_ticks[token] = tick
                self.oi_baseline.setdefault(token, int(tick.get("oi", 0)))
        await self._publish_snapshot()
        await self._check_timed_alerts()

    async def _shift_atm_if_needed(self, spot: float) -> None:
        if spot <= 0:
            return
        active = await instrument_repository.active_nifty_contracts()
        strikes = sorted({contract.strike for contract in active})
        new_atm = min(strikes, key=lambda strike: abs(strike - spot))
        if new_atm == self.current_atm:
            return
        old_atm = self.current_atm
        selected, _ = await instrument_repository.select_atm_window(new_atm)
        self.current_atm = new_atm
        self.current_expiry = min(contract.expiry for contract in selected)
        self.contracts = {contract.token: contract for contract in selected}
        self.option_ticks = {token: tick for token, tick in self.option_ticks.items() if token in self.contracts}
        if self.feed:
            await self.feed.replace_option_tokens([f"nse_fo|{contract.token}" for contract in selected])
        if old_atm is not None:
            await self._add_alert("ATM_SHIFT", f"atm-{self.current_expiry}-{new_atm}", "NIFTY ATM shifted", f"ATM moved from {old_atm} to {new_atm}; the ±10 strike window was resubscribed.")

    def _leg(self, contract: OptionContract, tick: dict[str, Any], spot: float) -> OptionLeg:
        premium = float(tick.get("ltp", 0))
        iv, delta = _greeks(spot, contract.strike, premium, contract.expiry, contract.option_type == "CE")
        oi = int(tick.get("oi", 0))
        return OptionLeg(
            ltp=round(premium, 2),
            change=round(float(tick.get("change", 0)), 2),
            oi=oi,
            oi_change=oi - self.oi_baseline.get(contract.token, oi),
            iv=iv,
            delta=delta,
        )

    async def _publish_snapshot(self) -> None:
        if not self.index_tick or not self.current_atm or not self.current_expiry or not self.last_tick:
            return
        by_strike: dict[int, dict[str, tuple[OptionContract, dict[str, Any]]]] = {}
        for token, contract in self.contracts.items():
            tick = self.option_ticks.get(token)
            if tick:
                by_strike.setdefault(contract.strike, {})[contract.option_type] = (contract, tick)
        complete = {strike: pair for strike, pair in by_strike.items() if "CE" in pair and "PE" in pair}
        if len(complete) < 3:
            return
        spot = float(self.index_tick.get("ltp", 0))
        rows: list[OptionRow] = []
        for strike, pair in sorted(complete.items()):
            call_contract, call_tick = pair["CE"]
            put_contract, put_tick = pair["PE"]
            rows.append(
                OptionRow(
                    strike=strike,
                    call=self._leg(call_contract, call_tick, spot),
                    put=self._leg(put_contract, put_tick, spot),
                    is_atm=strike == self.current_atm,
                )
            )
        call_oi = sum(row.call.oi for row in rows)
        put_oi = sum(row.put.oi for row in rows)
        pcr = round(put_oi / call_oi, 2) if call_oi else 0.0
        max_pain = min(
            (row.strike for row in rows),
            key=lambda settlement: sum(max(settlement - row.strike, 0) * row.call.oi + max(row.strike - settlement, 0) * row.put.oi for row in rows),
        )
        bias = "BULLISH" if pcr >= 1.05 else "BEARISH" if pcr <= 0.85 else "NEUTRAL"
        recommendation = "BUY CALLS" if bias == "BULLISH" else "BUY PUTS" if bias == "BEARISH" else "WAIT"
        close = float(self.index_tick.get("close", 0))
        snapshot = DashboardSnapshot(
            symbol="NIFTY",
            expiry=self.current_expiry.strftime("%d %b %Y"),
            spot=SpotSnapshot(
                symbol="NIFTY",
                ltp=spot,
                change=round(spot - close, 2) if close else 0,
                pct_change=float(self.index_tick.get("change_pct", 0)),
                high=float(self.index_tick.get("high", spot)),
                low=float(self.index_tick.get("low", spot)),
                timestamp=self.last_tick,
            ),
            option_chain=rows,
            structure=MarketStructure(
                pcr=pcr,
                max_pain=max_pain,
                bias=bias,
                oi_buildup=f"Live OI: {put_oi:,} puts vs {call_oi:,} calls",
            ),
            signal=SignalSnapshot(
                recommendation=recommendation,
                confidence=min(85, 55 + int(abs(pcr - 1) * 100)),
                reasons=[
                    f"Live PCR is {pcr:.2f}",
                    f"Calculated max pain is {max_pain}",
                    f"Spot is {spot:,.2f} with ATM at {self.current_atm}",
                ],
                timestamp=self.last_tick,
            ),
            feed=FeedHealth(
                state=self.state(),
                source="KOTAK_NEO",
                last_tick=self.last_tick,
                heartbeat_ms=max(0, int((datetime.now(UTC) - self.last_tick).total_seconds() * 1000)),
                subscriptions=self.subscription_count,
                divider_status="VERIFIED" if self.divider_verified else "PENDING",
            ),
            as_of=self.last_tick,
        )
        self.snapshot = snapshot
        document = snapshot.model_dump()
        document["_id"] = "NIFTY"
        await db.market_snapshots.replace_one({"_id": "NIFTY"}, document, upsert=True)

    async def _check_timed_alerts(self) -> None:
        if not self.current_expiry:
            return
        local = datetime.now(UTC).astimezone(IST)
        day_key = local.date().isoformat()
        if local.date() == self.current_expiry:
            await self._add_alert("EXPIRY_DAY", f"expiry-{day_key}", "NIFTY expiry day", f"The selected NIFTY contract expires today ({self.current_expiry.isoformat()}).")
        if local.weekday() < 5 and time(15, 15) <= local.time() < time(15, 30):
            await self._add_alert("NEAR_CLOSE", f"close-{day_key}", "Expiry window near close", "NSE closes in under 15 minutes; review liquidity and expiry exposure.")

    async def _add_alert(self, alert_type: str, alert_id: str, title: str, message: str) -> None:
        if alert_id in self.alert_ids:
            return
        alert = FeedAlert(id=alert_id, type=alert_type, title=title, message=message, created_at=datetime.now(UTC))
        self.alert_ids.add(alert_id)
        self.alerts.appendleft(alert)
        await db.feed_alerts.update_one({"id": alert_id}, {"$setOnInsert": alert.model_dump()}, upsert=True)

    async def _restore_snapshot_and_alerts(self) -> None:
        document = await db.market_snapshots.find_one({"_id": "NIFTY"}, {"_id": 0})
        if document:
            try:
                snapshot = DashboardSnapshot(**document)
                snapshot.as_of = _aware(snapshot.as_of) or snapshot.as_of
                snapshot.spot.timestamp = _aware(snapshot.spot.timestamp) or snapshot.spot.timestamp
                snapshot.signal.timestamp = _aware(snapshot.signal.timestamp) or snapshot.signal.timestamp
                snapshot.feed.last_tick = _aware(snapshot.feed.last_tick) or snapshot.feed.last_tick
                self.snapshot = snapshot
                self.last_tick = snapshot.feed.last_tick
                self.current_atm = min(snapshot.option_chain, key=lambda row: abs(row.strike - snapshot.spot.ltp)).strike if snapshot.option_chain else None
            except Exception:
                self.snapshot = None
        alert_docs = await db.feed_alerts.find({}, {"_id": 0}).sort("created_at", -1).limit(12).to_list(12)
        for document in reversed(alert_docs):
            try:
                alert = FeedAlert(**document)
                alert.created_at = _aware(alert.created_at) or alert.created_at
                self.alerts.appendleft(alert)
                self.alert_ids.add(alert.id)
            except Exception:
                continue


from lib.multi_feed_worker import MultiIndexFeedWorker


feed_worker = MultiIndexFeedWorker()