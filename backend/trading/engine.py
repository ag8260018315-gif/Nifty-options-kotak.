"""Pure trading rules: no clock, no database, no network. Easy to test and to reason about."""
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from trading.settings import TradingSettings

IST = ZoneInfo("Asia/Kolkata")
MAX_SIGNAL_AGE_SECONDS = 15


def _t(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def entry_decision(signal: dict[str, Any], day: dict[str, Any], now: datetime, settings: TradingSettings, killed: bool) -> str | None:
    """None means 'enter'. Otherwise the reason NOT to enter."""
    if settings.mode == "OFF":
        return "trading is OFF"
    if killed:
        return "kill switch is on"
    if signal.get("action") not in ("BUY CE", "BUY PE") or not signal.get("strike") or not signal.get("risk"):
        return "no signal"
    if signal.get("simulated") or signal.get("source") != "KOTAK_NEO":
        return "signal is not from live market data"
    if not signal.get("data_status", {}).get("ok"):
        return "data checks failed"
    if (now - datetime.fromisoformat(signal["as_of"])).total_seconds() > MAX_SIGNAL_AGE_SECONDS:
        return "signal is too old"
    if now.astimezone(IST).time() >= _t(settings.squareoff_time):
        return "past square-off time"
    if day["open_positions"] >= settings.max_open_positions:
        return "max open positions reached"
    if day["trades"] >= settings.max_trades_per_day:
        return "max trades for today reached"
    if settings.max_daily_loss > 0 and day["pnl"] <= -settings.max_daily_loss:
        return "daily loss limit reached"
    if signal.get("signal_id") in day["signal_ids"]:
        return "signal already traded"
    if settings.quantity(signal["symbol"]) <= 0:
        return "unknown lot size"
    return None


def open_position(signal: dict[str, Any], fill: float, now: datetime, settings: TradingSettings, mode: str) -> dict[str, Any]:
    risk = signal["risk"]
    entry_quote = risk["entry_premium"]
    scale = fill / entry_quote if entry_quote else 1.0  # keep stop/target at the same % distance from the actual fill
    return {
        "trade_id": f"{signal['signal_id']}:{mode}", "signal_id": signal["signal_id"], "symbol": signal["symbol"], "mode": mode,
        "direction": signal["direction"], "strike": signal["strike"]["strike"], "quantity": settings.quantity(signal["symbol"]),
        "entry_premium": fill, "stop": round(risk["premium_stop"] * scale, 2), "target": round(risk["premium_target"] * scale, 2),
        "confidence": signal["confidence"], "opened_at": now.isoformat(), "trading_day": now.astimezone(IST).date().isoformat(),
        "status": "OPEN", "exit_premium": None, "exit_reason": None, "pnl": None,
    }


def exit_reason(position: dict[str, Any], quote: float, now: datetime, settings: TradingSettings, killed: bool) -> str | None:
    if killed:
        return "KILL_SWITCH"
    if quote <= position["stop"]:
        return "STOP"
    if quote >= position["target"]:
        return "TARGET"
    if now.astimezone(IST).time() >= _t(settings.squareoff_time):
        return "SQUARE_OFF"
    return None


def close_position(position: dict[str, Any], fill: float, reason: str, now: datetime) -> dict[str, Any]:
    pnl = round((fill - position["entry_premium"]) * position["quantity"], 2)
    return {**position, "status": "CLOSED", "exit_premium": fill, "exit_reason": reason, "closed_at": now.isoformat(), "pnl": pnl}


def account(start_capital: float, realised_pnl: float, open_cost: float) -> dict[str, Any]:
    """Practice account: cash left to open new trades, and the total value if open trades were held at cost."""
    equity = start_capital + realised_pnl
    return {
        "start_capital": start_capital, "realised_pnl": round(realised_pnl, 2), "equity": round(equity, 2),
        "available": round(equity - open_cost, 2), "return_pct": round(realised_pnl / start_capital * 100, 2) if start_capital else None,
    }


def can_afford(start_capital: float, available: float, fill: float, quantity: int) -> bool:
    """With no capital set there is no limit; otherwise the buy must fit in the cash that is free."""
    return start_capital <= 0 or fill * quantity <= available
