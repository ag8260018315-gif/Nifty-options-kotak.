from datetime import datetime, timedelta, timezone

from models.dashboard import (
    DashboardSnapshot,
    FeedHealth,
    MarketStructure,
    OptionLeg,
    OptionRow,
    SignalSnapshot,
    SpotSnapshot,
)


BASE_VALUES = {
    "NIFTY": (25142.35, 25000, "Bullish call writing", 1.08),
    "BANKNIFTY": (58218.70, 58000, "Put support building", 1.16),
    "FINNIFTY": (26548.15, 26500, "Balanced two-way OI", 0.97),
}


def _leg(strike: int, spot: float, is_call: bool, offset: int) -> OptionLeg:
    distance = abs(strike - round(spot / 50) * 50) / 50
    base_ltp = max(8.5, 122 - distance * 26) if is_call else max(9.25, 128 - distance * 24)
    if strike < spot and is_call:
        base_ltp += 22
    if strike > spot and not is_call:
        base_ltp += 19
    direction = 1 if is_call else -1
    return OptionLeg(
        ltp=round(base_ltp + offset * 0.35, 2),
        change=round(direction * (1.8 - distance * 0.22), 2),
        oi=int((82000 + (5 - min(distance, 5)) * 12500 + offset * 850) * (1.05 if not is_call else 0.94)),
        oi_change=int(direction * (3400 - min(distance, 4) * 480)),
        iv=round(11.9 + distance * 0.85 + (0.45 if not is_call else 0), 2),
        delta=round((0.5 - distance * 0.065) * direction, 2),
    )


def demo_snapshot(symbol: str) -> DashboardSnapshot:
    spot, atm, buildup, pcr = BASE_VALUES[symbol]
    now = datetime.now(timezone.utc)
    strikes = [atm + (step * 50) for step in range(-5, 6)]
    rows = [
        OptionRow(
            strike=strike,
            call=_leg(strike, spot, True, index),
            put=_leg(strike, spot, False, index),
            is_atm=strike == atm,
        )
        for index, strike in enumerate(strikes)
    ]
    change = 184.25 if symbol == "NIFTY" else 302.10 if symbol == "BANKNIFTY" else 96.45
    return DashboardSnapshot(
        symbol=symbol,
        expiry=(now + timedelta(days=5)).strftime("%d %b %Y"),
        spot=SpotSnapshot(
            symbol=symbol,
            ltp=spot,
            change=change,
            pct_change=round(change / (spot - change) * 100, 2),
            high=round(spot + 145.8, 2),
            low=round(spot - 212.4, 2),
            timestamp=now,
        ),
        option_chain=rows,
        structure=MarketStructure(
            pcr=pcr,
            max_pain=atm,
            bias="BULLISH" if pcr >= 1 else "NEUTRAL",
            oi_buildup=buildup,
        ),
        signal=SignalSnapshot(
            recommendation="BUY CALLS" if pcr >= 1.05 else "WAIT",
            confidence=72 if pcr >= 1.05 else 58,
            reasons=[
                "Put OI concentration above spot",
                "Call writing capped at the next resistance band",
                "Spot holding above VWAP proxy",
            ],
            timestamp=now,
        ),
        feed=FeedHealth(
            state="DEMO",
            source="DEMO",
            last_tick=now,
            heartbeat_ms=420,
            subscriptions=22,
            divider_status="PENDING",
        ),
        as_of=now,
    )