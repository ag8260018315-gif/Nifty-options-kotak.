"""Load EVERY NSE stock into the app: the searchable list (names) and daily candles for each one (read-only market data from Upstox).

  python tools/import_upstox_all_stocks.py --list-only       # names for search only; no Upstox login needed, a few seconds
  python tools/import_upstox_all_stocks.py --probe           # checks the token and prints what Upstox returns for one stock; saves nothing
  python tools/import_upstox_all_stocks.py                   # list + one year of daily candles for every stock (about 15-25 minutes)
  python tools/import_upstox_all_stocks.py --years 2 --limit 300       # a smaller or longer run
  python tools/import_upstox_all_stocks.py --years 0.1                 # a quick top-up later: only the last ~5 weeks, merged into what is stored

The Stocks page then finds any stock by name or symbol and opens an END-OF-DAY chart for it (daily, weekly and monthly candles).
These stocks are not on the live Kotak feed, so no live price is shown for them.

Space: one stock takes roughly 14 KB per year of daily candles, so about 2,200 stocks for one year is around 30 MB of the free 512 MB database.
Needs UPSTOX_ACCESS_TOKEN (not for --list-only), MONGO_URL and DB_NAME in backend/.env; never paste them into chat or GitHub.
Safe to re-run: a stock updated within the last --fresh-hours is skipped, so an interrupted run carries on where it stopped.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

KB_PER_STOCK_YEAR = 14


async def fresh_symbols(db, hours: float) -> set[str]:
    """Symbols whose stored daily history was written in the last `hours` hours (one small query, no candle data transferred)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    done: set[str] = set()
    async for doc in db["index_history"].find({"interval": "1d"}, {"symbol": 1, "updated_at": 1}):
        try:
            if datetime.fromisoformat(doc["updated_at"]) >= cutoff:
                done.add(doc["symbol"])
        except (KeyError, ValueError):
            continue
    return done


async def main(args: argparse.Namespace) -> int:
    import httpx

    from jobs import upstox
    from lib.db import db
    from premium import directory, history

    async with httpx.AsyncClient() as client:
        items = upstox.directory_items(await upstox.load_instruments(client))
        print(f"Upstox lists {len(items)} NSE stocks.")
        if len(items) < 500:
            print("FAIL: far fewer stocks than expected; the instrument file may have changed. Nothing was saved.")
            return 1
        if not args.probe:
            saved = await directory.save(db, items, source="upstox")
            print(f"search list saved: {saved} stocks")
        if args.list_only:
            return 0

        token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
        if not token:
            print("FAIL: set UPSTOX_ACCESS_TOKEN in backend/.env first (it expires every day; make a new one when Upstox says 401).")
            return 1
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=int(365 * args.years))
        if args.probe:
            first = items[0]
            raw = await upstox.fetch_range(client, token, first["key"], end - timedelta(days=10), end, "day")
            rows = (raw.get("data") or {}).get("candles") or []
            bars = upstox.parse_candles(raw, session_only=False)
            print(f"{first['symbol']}: status={raw.get('status')} candles={len(rows)} usable={len(bars)} first row: {rows[0] if rows else None}")
            return 0 if bars else 1

        skip = set() if args.refresh else await fresh_symbols(db, args.fresh_hours)
        todo = [i for i in items if i["symbol"] not in skip]
        if args.limit:
            todo = todo[: args.limit]
        print(f"{len(todo)} stocks to download ({len(items) - len(todo)} already fresh). About {len(todo) * KB_PER_STOCK_YEAR * max(args.years, 0.1) / 1024:.0f} MB of space.")
        saved_total = failed = 0
        for n, item in enumerate(todo, start=1):
            bars: list[dict] = []
            try:
                for a, b in upstox.windows(start, end, args.chunk_days):
                    bars.extend(upstox.parse_candles(await upstox.fetch_range(client, token, item["key"], a, b, "day"), session_only=False))
                    await asyncio.sleep(0.35)  # stay well inside Upstox's rate limit
            except upstox.UpstoxError as exc:
                print(f"{item['symbol']}: {exc}")
                if "401" in str(exc):
                    print("Stopped: the token is missing or expired. Make a new one and run the same command again; finished stocks are skipped.")
                    return 1
                failed += 1
                continue
            if bars:
                await history.merge_save(db, item["symbol"], "1d", bars)
                saved_total += 1
            if n % 50 == 0 or n == len(todo):
                print(f"{n}/{len(todo)} done ({saved_total} saved, {failed} failed)")
        print(f"finished: {saved_total} stocks saved" + (f", {failed} failed (run the same command again to retry them)" if failed else ""))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--list-only", action="store_true", help="save the searchable list only; no candles, no Upstox login")
    p.add_argument("--probe", action="store_true", help="check the token on one stock; save nothing")
    p.add_argument("--years", type=float, default=1.0, help="years of daily candles (default 1; each extra year adds about 30 MB for all stocks)")
    p.add_argument("--limit", type=int, default=0, help="only the first N stocks that still need data")
    p.add_argument("--refresh", action="store_true", help="download again even stocks updated within --fresh-hours")
    p.add_argument("--fresh-hours", type=float, default=20.0, help="skip stocks updated within this many hours")
    p.add_argument("--chunk-days", type=int, default=365, help="days per request; lower it if Upstox rejects long ranges")
    sys.exit(asyncio.run(main(p.parse_args())))
