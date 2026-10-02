"""Auto-trader: guardrails, exits, kill switch, paper P&L, and the refusal to place real orders."""
import ast
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient

from live.engine import generate
from live.inputs import ChainRow, Leg, LiveInputs
from tests.test_engines_core import AS_OF, CFG, uptrend_inputs
from trading import engine, store
from trading.brokers import BrokerNotVerified, PaperBroker, build_broker
from trading.runner import AutoTrader
from trading.settings import TradingSettings

S = TradingSettings(slippage_pct=0.0)
DAY = {"open_positions": 0, "trades": 0, "pnl": 0.0, "signal_ids": set()}


def signal(inputs=None):
    return generate(inputs or uptrend_inputs(), CFG)


def test_entry_allowed_for_fresh_live_signal():
    assert engine.entry_decision(signal(), DAY, AS_OF + timedelta(seconds=2), S, killed=False) is None


@pytest.mark.parametrize("change,why", [
    ({"day": {**DAY, "open_positions": 1}}, "max open"),
    ({"day": {**DAY, "trades": 5}}, "max trades"),
    ({"day": {**DAY, "pnl": -2500.0}}, "daily loss"),
    ({"killed": True}, "kill switch"),
    ({"settings": replace(S, mode="OFF")}, "OFF"),
    ({"now": AS_OF + timedelta(seconds=60)}, "too old"),
    ({"now": AS_OF.replace(hour=15, minute=16)}, "square-off"),
])
def test_entry_blocked(change, why):
    args = {"signal": signal(), "day": DAY, "now": AS_OF + timedelta(seconds=2), "settings": S, "killed": False, **change}
    reason = engine.entry_decision(args["signal"], args["day"], args["now"], args["settings"], args["killed"])
    assert reason is not None, why


def test_demo_signal_never_trades():
    inputs = uptrend_inputs()
    demo = generate(LiveInputs(**{**inputs.__dict__, "source": "DEMO", "feed_state": "DEMO"}), CFG, require_live=False)
    assert engine.entry_decision(demo, DAY, AS_OF, S, False) == "signal is not from live market data" or demo["action"] == "NO SIGNAL"


def test_exit_rules_and_pnl():
    sig = signal()
    pos = engine.open_position(sig, 100.0, AS_OF, S, "PAPER")
    assert pos["stop"] < 100 < pos["target"] and pos["quantity"] == 75
    assert engine.exit_reason(pos, pos["stop"] - 1, AS_OF, S, False) == "STOP"
    assert engine.exit_reason(pos, pos["target"] + 1, AS_OF, S, False) == "TARGET"
    assert engine.exit_reason(pos, 100.0, AS_OF, S, True) == "KILL_SWITCH"
    assert engine.exit_reason(pos, 100.0, AS_OF.replace(hour=15, minute=20), S, False) == "SQUARE_OFF"
    assert engine.exit_reason(pos, 100.0, AS_OF, S, False) is None
    assert engine.close_position(pos, 110.0, "TARGET", AS_OF)["pnl"] == 750.0


def test_paper_slippage_is_always_unfavourable():
    b = PaperBroker(TradingSettings(slippage_pct=1.0))
    assert b.fill("BUY", 100) == 101.0 and b.fill("SELL", 100) == 99.0


def test_live_mode_refuses_real_orders():
    with pytest.raises(BrokerNotVerified):
        build_broker(TradingSettings(mode="LIVE"))
    with pytest.raises(BrokerNotVerified):
        build_broker(TradingSettings(mode="LIVE", live_confirmed=True)).fill("BUY", 100)


def test_trading_package_never_imports_research():
    for path in (Path(__file__).resolve().parent.parent / "trading").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(n.startswith("research") for n in names), path.name


def with_premium(inputs, strike, premium):
    chain = tuple(ChainRow(r.strike, Leg(premium, 0, r.call.oi, 0, 14, r.call.delta, r.call.volume) if r.strike == strike else r.call, r.put) for r in inputs.chain)
    return LiveInputs(**{**inputs.__dict__, "chain": chain})


async def test_full_cycle_open_then_target_then_no_reentry():
    db = AsyncMongoMockClient()["live"]
    box = {"inputs": uptrend_inputs()}
    sig = signal(box["inputs"])

    async def provider(symbol):
        return box["inputs"]

    trader = AutoTrader(db, provider, {"NIFTY": sig}, PaperBroker(S), S)
    now = AS_OF + timedelta(seconds=2)
    await trader.step("NIFTY", now)
    open_ = await store.open_trades(db)
    assert len(open_) == 1 and open_[0]["direction"] == "CE"
    await trader.step("NIFTY", now)  # same signal again: no second trade
    assert await db.auto_trades.count_documents({}) == 1
    box["inputs"] = with_premium(uptrend_inputs(), sig["strike"]["strike"], open_[0]["target"] + 1)
    await trader.step("NIFTY", now + timedelta(seconds=5))
    done = await db.auto_trades.find_one({"trade_id": open_[0]["trade_id"]})
    assert done["status"] == "CLOSED" and done["exit_reason"] == "TARGET" and done["pnl"] > 0
    assert (await store.day_summary(db, now))["pnl"] == done["pnl"]


async def test_kill_switch_closes_positions_and_blocks_entries():
    db = AsyncMongoMockClient()["live"]
    inputs = uptrend_inputs()
    sig = signal(inputs)

    async def provider(symbol):
        return inputs

    trader = AutoTrader(db, provider, {"NIFTY": sig}, PaperBroker(S), S)
    now = AS_OF + timedelta(seconds=2)
    await trader.step("NIFTY", now)
    await store.set_killed(db, True, "test")
    await trader.step("NIFTY", now + timedelta(seconds=3))
    t = await db.auto_trades.find_one({})
    assert t["status"] == "CLOSED" and t["exit_reason"] == "KILL_SWITCH"
    assert await db.auto_trades.count_documents({}) == 1
