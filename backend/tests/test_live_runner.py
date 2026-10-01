"""Live runner persistence, cooldown, outcomes, replay and database separation (in-memory Mongo)."""
from datetime import timedelta

import pytest
from mongomock_motor import AsyncMongoMockClient

from live import store
from live.engine import replay
from live.inputs import ChainRow, Leg, LiveInputs
from live.runner import LiveSignalRunner
from shared.config import EngineConfig
from tests.test_engines_core import AS_OF, CFG, uptrend_inputs
import live.runner as runner_mod


@pytest.fixture
def dbs():
    client = AsyncMongoMockClient()
    return client["live"], client["research"]


async def test_signal_stored_with_inputs_once_then_cooldown(dbs, monkeypatch):
    live_db, research_db = dbs
    monkeypatch.setattr(runner_mod, "load_config", lambda: CFG)
    current = {"inputs": uptrend_inputs()}

    async def provider(symbol):
        return current["inputs"]

    runner = LiveSignalRunner(live_db, provider)
    # evaluate() compares against the wall clock; inputs are from 2026 so use a stub clock-free path
    first = await runner.evaluate("NIFTY")
    assert first["action"] == "BUY CE"
    stored = await store.get_signal_with_inputs(live_db, first["signal_id"])
    assert stored and stored["inputs"]["symbol"] == "NIFTY"
    assert replay(stored, stored["inputs"], EngineConfig.model_validate(stored["config"]))["reproducible"]
    # 60 s later: still a signal on screen, but not stored again (cooldown 300 s)
    later = uptrend_inputs(as_of=AS_OF + timedelta(seconds=60))
    current["inputs"] = later
    second = await runner.evaluate("NIFTY")
    assert second.get("cooldown") is True
    assert await live_db.live_signals.count_documents({}) == 1
    assert await research_db.list_collection_names() == []  # live work never touches research storage


async def test_outcome_resolved_from_later_live_premium(dbs, monkeypatch):
    live_db, _ = dbs
    monkeypatch.setattr(runner_mod, "load_config", lambda: CFG)
    box = {"inputs": uptrend_inputs()}

    async def provider(symbol):
        return box["inputs"]

    runner = LiveSignalRunner(live_db, provider)
    sig = await runner.evaluate("NIFTY")
    target = sig["risk"]["premium_target"]
    later = uptrend_inputs(as_of=AS_OF + timedelta(seconds=30))
    strike = sig["strike"]["strike"]
    chain = tuple(ChainRow(r.strike, Leg(target + 1, 0, r.call.oi, 0, 14, r.call.delta, r.call.volume) if r.strike == strike else r.call, r.put) for r in later.chain)
    box["inputs"] = LiveInputs(**{**later.__dict__, "chain": chain})
    await runner.evaluate("NIFTY")
    outcome = await live_db.signal_outcomes.find_one({"signal_id": sig["signal_id"]})
    assert outcome["outcome"] == "TARGET_HIT" and outcome["return_pct"] > 0


async def test_demo_data_is_never_persisted(dbs, monkeypatch):
    live_db, _ = dbs
    monkeypatch.setattr(runner_mod, "load_config", lambda: CFG)
    demo = uptrend_inputs()

    async def provider(symbol):
        return LiveInputs(**{**demo.__dict__, "source": "DEMO", "feed_state": "DEMO"})

    sig = await LiveSignalRunner(live_db, provider).evaluate("NIFTY")
    assert sig["simulated"] is True
    assert await live_db.live_signals.count_documents({}) == 0
