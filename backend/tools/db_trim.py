"""Frees database space by deleting OLD per-minute stock candles (the biggest growth in the app). Safe by default:

    python tools/db_trim.py                      # dry run: only counts what WOULD be deleted
    python tools/db_trim.py --keep-days 7        # dry run with a different window
    python tools/db_trim.py --keep-days 7 --yes  # really delete

Only the `premium_candles` collection is touched (1-minute stock/SENSEX candles older than --keep-days sessions). The app only
needs the last few sessions from it (previous-day levels, the last-session view, filling gaps since your last history import).
Charts, history imports, back-test results, watchlists and logins are not touched. Deleted candles cannot be brought back.
After deleting, Atlas can take a few minutes to show the lower size; if it does not drop, run this in the Atlas shell:
db.runCommand({compact: "premium_candles"})  (free clusters may not allow it; the freed space is reused anyway).
"""
import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main(keep_days: int, yes: bool) -> int:
    from lib.db import db

    col = db["premium_candles"]
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    days = sorted(await col.distinct("trading_day"))
    print(f"stored sessions: {len(days)} ({days[0] if days else '-'} to {days[-1] if days else '-'})")
    old = await col.count_documents({"trading_day": {"$lt": cutoff}})
    total = await col.estimated_document_count()
    print(f"candles older than {cutoff} (keeping about the last {keep_days} calendar days): {old:,} of {total:,}")
    if not yes:
        print("Dry run: nothing deleted. Add --yes to delete them.")
        return 0
    result = await col.delete_many({"trading_day": {"$lt": cutoff}})
    print(f"deleted {result.deleted_count:,} candles.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--keep-days", type=int, default=10)
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()
    if a.keep_days < 3:
        sys.exit("Keep at least 3 days.")
    sys.exit(asyncio.run(main(a.keep_days, a.yes)))
