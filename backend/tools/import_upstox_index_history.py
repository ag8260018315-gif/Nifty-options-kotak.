"""Download long-timeframe history for the four indices (and optionally all 129 stocks) from Upstox into the app database (read-only market data).

  python tools/import_upstox_index_history.py --probe            # one index: prints what Upstox returns, saves nothing
  python tools/import_upstox_index_history.py                     # 2 years of daily + 6 months of 30-minute candles
  python tools/import_upstox_index_history.py --daily-years 5 --intraday-months 12 --intraday-chunk 28
  python tools/import_upstox_index_history.py --stocks --only-stocks      # the 129 stocks too (30-minute + daily, with volume)

The Premium page builds its 1-hour and 4-hour charts from the 30-minute candles and its 1-day and 1-week charts from the daily ones.
Needs UPSTOX_ACCESS_TOKEN, MONGO_URL and DB_NAME in backend/.env (never paste them into chat or GitHub). Safe to re-run: new candles
are merged into the stored ones. Default instrument keys can be overridden with --key SYMBOL=KEY if Upstox names an index differently.
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

DEFAULT_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank", "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "SENSEX": "BSE_INDEX|SENSEX"}
INTERVALS = {"day": "1d", "30minute": "30m"}


async def main(args: argparse.Namespace) -> int:
    import httpx

    from jobs import upstox
    from lib.db import db
    from premium import history

    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        print("FAIL: set UPSTOX_ACCESS_TOKEN in backend/.env first.")
        return 1
    keys = {} if args.only_stocks else dict(DEFAULT_KEYS)
    if args.stocks:
        from premium.universe import stock_symbols

        async with httpx.AsyncClient() as meta_client:
            found = upstox.symbol_keys(await upstox.load_instruments(meta_client), stock_symbols())
        missing = [s for s in stock_symbols() if s not in found]
        print(f"instrument keys found for {len(found)} of {len(stock_symbols())} stocks" + (f"; missing: {missing[:12]}" if missing else ""))
        keys.update(found)
    for item in args.key or []:
        name, _, value = item.partition("=")
        keys[name.strip().upper()] = value.strip()
    end = date.today() - timedelta(days=1)
    spans = {"day": (end - timedelta(days=365 * args.daily_years), args.daily_chunk), "30minute": (end - timedelta(days=30 * args.intraday_months), args.intraday_chunk)}
    async with httpx.AsyncClient() as client:
        if args.probe:
            symbol, key = next(iter(keys.items()))
            for interval in INTERVALS:
                try:
                    raw = await upstox.fetch_range(client, token, key, end - timedelta(days=10), end, interval)
                except upstox.UpstoxError as exc:
                    print(f"{symbol} {interval}: {exc}")
                    continue
                rows = (raw.get("data") or {}).get("candles") or []
                bars = upstox.parse_candles(raw, session_only=interval != "day")
                print(f"{symbol} {interval}: status={raw.get('status')} candles={len(rows)} usable={len(bars)} first row: {rows[0] if rows else None}")
            return 0
        failures = 0
        for symbol, key in keys.items():
            for interval, label in INTERVALS.items():
                start, chunk = spans[interval]
                bars: list[dict] = []
                for a, b in upstox.windows(start, end, chunk):
                    try:
                        bars.extend(upstox.parse_candles(await upstox.fetch_range(client, token, key, a, b, interval), session_only=interval != "day"))
                    except upstox.UpstoxError as exc:
                        print(f"{symbol} {interval} {a}..{b}: {exc}")
                        if "401" in str(exc):
                            return 1
                        failures += 1
                    await asyncio.sleep(0.35)
                stored = await history.merge_save(db, symbol, label, bars) if bars else 0
                print(f"{symbol} {label}: downloaded {len(bars)} candles, {stored} stored")
        print("done" + (f" with {failures} failed windows (lower --intraday-chunk or --daily-chunk and re-run)" if failures else ""))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--stocks", action="store_true", help="also download the 129 premium stocks")
    p.add_argument("--only-stocks", action="store_true", help="skip the four indices")
    p.add_argument("--daily-years", type=int, default=2)
    p.add_argument("--intraday-months", type=int, default=6)
    p.add_argument("--daily-chunk", type=int, default=365)
    p.add_argument("--intraday-chunk", type=int, default=28)
    p.add_argument("--key", action="append", help="override an instrument key, e.g. --key SENSEX='BSE_INDEX|SENSEX'")
    sys.exit(asyncio.run(main(p.parse_args())))
