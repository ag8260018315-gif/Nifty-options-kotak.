"""Download past 1-minute stock candles from Upstox into research storage (read-only).

  python tools/import_upstox_history.py --probe                       # one stock, one day: prints the response shape
  python tools/import_upstox_history.py --months 6 --limit 25         # first 25 premium stocks, last 6 months
  python tools/import_upstox_history.py --from 2026-04-01 --to 2026-09-30

Needs UPSTOX_ACCESS_TOKEN in backend/.env (never paste it into chat or GitHub). Safe to re-run: stored days are skipped.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main(args: argparse.Namespace) -> int:
    import httpx

    from jobs import upstox
    from lib.db import research_db
    from premium.universe import stock_symbols
    from research import stock_history

    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        print("FAIL: set UPSTOX_ACCESS_TOKEN in backend/.env first.")
        return 1
    wanted = stock_symbols()[: args.limit] if args.limit else stock_symbols()
    today = date.today()
    end = date.fromisoformat(args.to) if args.to else today - timedelta(days=1)
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=30 * args.months)
    async with httpx.AsyncClient() as client:
        keys = upstox.symbol_keys(await upstox.load_instruments(client), wanted)
        missing = [s for s in wanted if s not in keys]
        print(f"instrument keys found for {len(keys)} of {len(wanted)} stocks" + (f"; missing: {missing[:10]}" if missing else ""))
        if args.probe:
            symbol = next(iter(keys), None)
            if symbol is None:
                print("FAIL: no instrument keys resolved.")
                return 1
            raw = await upstox.fetch_range(client, token, keys[symbol], end, end)
            rows = (raw.get("data") or {}).get("candles") or []
            print(f"{symbol} {end}: status={raw.get('status')} candles={len(rows)}")
            print("first row:", rows[0] if rows else None)
            bars = upstox.parse_candles(raw)
            print(f"usable in-session bars: {len(bars)}; with volume: {sum(1 for b in bars if b['volume'])}")
            return 0 if bars else 1
        total_days = 0
        for symbol, key in keys.items():
            have = await stock_history.stored_days(research_db, symbol)
            got = 0
            for a, b in upstox.windows(start, end, args.chunk_days):
                try:
                    bars = upstox.parse_candles(await upstox.fetch_range(client, token, key, a, b))
                except upstox.UpstoxError as exc:
                    print(f"{symbol} {a}..{b}: {exc}")
                    if "401" in str(exc):
                        return 1
                    continue
                bars = [x for x in bars if stock_history.day_of(x["time"]) not in have]
                if bars:
                    got += await stock_history.save_days(research_db, symbol, bars, source="upstox")
                await asyncio.sleep(0.35)  # stay well inside the rate limit
            total_days += got
            print(f"{symbol}: saved {got} new sessions")
        print(f"done: {total_days} sessions saved for {len(keys)} stocks")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--from", dest="start")
    p.add_argument("--to")
    p.add_argument("--limit", type=int, default=0, help="only the first N premium stocks")
    p.add_argument("--chunk-days", type=int, default=28, help="days per request; lower it if Upstox rejects long ranges")
    sys.exit(asyncio.run(main(p.parse_args())))
