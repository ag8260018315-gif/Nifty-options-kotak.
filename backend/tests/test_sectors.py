import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "t")

from premium import sectors as sv  # noqa: E402
from tests.test_premium import api  # noqa: E402,F401


def row(sym, sector, pct, action="NEUTRAL", rvol=1.0, priced=True):
    return {"symbol": sym, "name": sym, "sector": sector, "quote": {"ltp": 100, "change_pct": pct} if priced else None, "signal": {"action": action, "relative_volume": rvol}}


def test_equal_weight_average_leaders_and_unpriced_are_left_out():
    out = sv.summarize([row("A", "Banks", 2.0, "BUY", 2.0), row("B", "Banks", -1.0, "SELL", 1.0), row("C", "Banks", 0.0, priced=False), row("D", "IT", 3.0, "BUY"), row("E", "Auto", -2.0)])
    assert [s["sector"] for s in out] == ["IT", "Banks", "Auto"]                 # best average first
    banks = out[1]
    assert banks["stocks"] == 3 and banks["with_prices"] == 2 and banks["avg_change_pct"] == 0.5
    assert (banks["advancers"], banks["decliners"], banks["bullish"], banks["bearish"]) == (1, 1, 1, 1) and banks["avg_relative_volume"] == 1.5
    assert banks["leaders"][0] == "A" and banks["laggards"][0] == "B" and [m["symbol"] for m in banks["members"]] == ["A", "B"]
    assert sv.summarize([row("X", "Metals", 0, priced=False)])[0]["avg_change_pct"] is None


def test_api_lists_every_sector_with_a_plain_label_and_is_premium_only(api):
    ok = api.client.get("/api/premium/sectors", headers=api.cookie("paid@example.com")).json()
    assert len(ok["sectors"]) >= 15 and "equal-weight" in ok["note"].lower() and sum(s["stocks"] for s in ok["sectors"]) == 129
    assert api.client.get("/api/premium/sectors", headers=api.cookie("viewer@example.com")).status_code == 403
