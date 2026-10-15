"""Load EVERY NSE stock into the app: the searchable list (names) and daily candles for each one (read-only market data from Upstox).

  python tools/import_upstox_all_stocks.py --list-only       # names for search only; no Upstox login needed, a few seconds
  python tools/import_upstox_all_stocks.py --probe           # checks the token and prints what Upstox returns for one stock; saves nothing
  python tools/import_upstox_all_stocks.py                   # list + one year of daily candles for every stock (about 15-25 minutes)
  python tools/import_upstox_all_stocks.py --years 2 --limit 300       # a smaller or longer run
  python tools/import_upstox_all_stocks.py --years 0.1                 # a quick top-up later: only the last ~5 weeks, merged into what is stored

The Stocks page then finds any stock by name or symbol and opens an END-OF-DAY chart for it (daily, weekly and monthly candles).
These stocks are not on the live Kotak feed, so no live price is shown for them.

Space: one stock takes about 17 KB per year of daily candles, so about 2,200 stocks for one year is around 36 MB of the free 512 MB database. The run
stops by itself when the database is 75% full (LOADER_STOP_PERCENT).
Needs UPSTOX_ACCESS_TOKEN (not for --list-only), MONGO_URL and DB_NAME in backend/.env; never paste them into chat or GitHub.
Safe to re-run: a stock updated within the last --fresh-hours is skipped, so an interrupted run carries on where it stopped.
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

    from jobs import stock_loader, upstox
    from lib.db import db, live_db, research_db

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            if args.probe:
                items = upstox.directory_items(upstox.iter_json_array(upstox._text_chunks((await client.get(upstox.INSTRUMENTS_URL, timeout=90)).content)))
                print(f"Upstox lists {len(items)} NSE stocks.")
            else:
                items = await stock_loader.load_list(db, client)
                print(f"Upstox lists {len(items)} NSE stocks. Search list saved: {len(items)} stocks.")
        except stock_loader.LoaderError as exc:
            print(f"FAIL: {exc}")
            return 1
        if args.list_only:
            return 0

        token = os.environ.get(stock_loader.TOKEN_ENV, "").strip()
        if not token:
            print("FAIL: set UPSTOX_ACCESS_TOKEN in backend/.env first (it expires every day; make a new one when Upstox says 401).")
            return 1
        if args.probe:
            end = date.today() - timedelta(days=1)
            raw = await upstox.fetch_range(client, token, items[0]["key"], end - timedelta(days=10), end, "day")
            rows = (raw.get("data") or {}).get("candles") or []
            bars = upstox.parse_candles(raw, session_only=False)
            print(f"{items[0]['symbol']}: status={raw.get('status')} candles={len(rows)} usable={len(bars)} first row: {rows[0] if rows else None}")
            return 0 if bars else 1

        print(f"About {len(items) * stock_loader.KB_PER_STOCK_YEAR * max(args.years, 0.1) / 1024:.0f} MB of space if every stock is downloaded.")

        def show(p: dict) -> None:
            if p["done"] % 50 == 0 or p["done"] == p["total"]:
                print(f"{p['done']}/{p['total']} done ({p['saved']} saved, {p['failed']} failed)")

        try:
            out = await stock_loader.load_history(db, client, token, items, years=args.years, chunk_days=args.chunk_days, fresh_hours=args.fresh_hours,
                                                  limit=args.limit, force=args.refresh, progress=show,
                                                  guard=stock_loader.space_guard({"app": db, "live": live_db, "research": research_db}))
        except upstox.UpstoxError as exc:
            print(f"Stopped: {exc}\nThe token is missing or expired. Make a new one and run the same command again; finished stocks are skipped.")
            return 1
        if out["reason"]:
            print(out["reason"])
            return 1
        print(f"finished: {out['saved']} stocks saved ({out['skipped']} already fresh)" + (f", {out['failed']} failed (run the same command again to retry them)" if out["failed"] else ""))
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--list-only", action="store_true", help="save the searchable list only; no candles, no Upstox login")
    p.add_argument("--probe", action="store_true", help="check the token on one stock; save nothing")
    p.add_argument("--years", type=float, default=1.0, help="years of daily candles (default 1; each year adds about 36 MB for all stocks)")
    p.add_argument("--limit", type=int, default=0, help="only the first N stocks that still need data")
    p.add_argument("--refresh", action="store_true", help="download again even stocks updated within --fresh-hours")
    p.add_argument("--fresh-hours", type=float, default=20.0, help="skip stocks updated within this many hours")
    p.add_argument("--chunk-days", type=int, default=365, help="days per request; lower it if Upstox rejects long ranges")
    sys.exit(asyncio.run(main(p.parse_args())))
