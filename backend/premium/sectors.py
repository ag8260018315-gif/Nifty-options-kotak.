"""Sector view of the stock universe: how each sector is moving today and which stocks lead or lag. Pure.

Every figure is a plain EQUAL-WEIGHT average over the sector's stocks that have a price (no market-cap weighting: the app has no
market-cap data), so a sector's number is not an index value. Stocks without a price are counted but left out of the averages."""
from typing import Any

NOTE = "Equal-weight average of the sector's stocks that have a price (not market-cap weighted, so it is not a sector index). Informational."


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """rows: {symbol, name, sector, quote (or None), signal {action, relative_volume}}. Returns one dict per sector, best average first."""
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["sector"] or "Other", []).append(r)
    out = []
    for sector, items in by.items():
        priced = [r for r in items if r.get("quote") and r["quote"].get("change_pct") is not None]
        pct = [r["quote"]["change_pct"] for r in priced]
        rvol = [r["signal"]["relative_volume"] for r in priced if r.get("signal", {}).get("relative_volume") is not None]
        acts = [r["signal"]["action"] for r in priced if r.get("signal")]
        ranked = sorted(priced, key=lambda r: r["quote"]["change_pct"], reverse=True)
        out.append({
            "sector": sector, "stocks": len(items), "with_prices": len(priced),
            "avg_change_pct": round(sum(pct) / len(pct), 2) if pct else None,
            "advancers": sum(1 for p in pct if p > 0), "decliners": sum(1 for p in pct if p < 0),
            "bullish": acts.count("BUY"), "bearish": acts.count("SELL"),
            "avg_relative_volume": round(sum(rvol) / len(rvol), 2) if rvol else None,
            "leaders": [r["symbol"] for r in ranked[:3]], "laggards": [r["symbol"] for r in ranked[::-1][:3]],
            "members": [{"symbol": r["symbol"], "name": r["name"], "ltp": r["quote"]["ltp"], "change_pct": r["quote"]["change_pct"]} for r in ranked],
        })
    out.sort(key=lambda s: (s["avg_change_pct"] is None, -(s["avg_change_pct"] or 0)))
    return out
