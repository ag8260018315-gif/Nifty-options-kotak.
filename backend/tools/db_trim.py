"""Frees database space by deleting OLD records of one kind. Safe by default (a dry run only counts):

    python tools/db_trim.py --target snapshots --keep-days 3           # dry run
    python tools/db_trim.py --target snapshots --keep-days 3 --yes     # really delete
    python tools/db_trim.py --target candles --keep-days 10 [--yes]

  --target snapshots : `market_snapshot_history`, the 5-second option-chain snapshots (the biggest user of space). The app only
                       needs the recent days: the daily export of a day and the nightly copy into research. Older days' snapshot
                       exports can no longer be downloaded after this.
  --target candles   : `premium_candles`, 1-minute stock candles older than --keep-days.
Nothing else is touched (charts, history imports, back-test results, watchlists, logins). Deleted records cannot be brought back.
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


async def main(keep_days: int, yes: bool, target: str) -> int:
    from lib.db import db

    col = db["market_snapshot_history" if target == "snapshots" else "premium_candles"]
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
    p.add_argument("--target", choices=("snapshots", "candles"), required=True)
    p.add_argument("--keep-days", type=int, default=10)
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()
    if a.keep_days < 3:
        sys.exit("Keep at least 3 days.")
    sys.exit(asyncio.run(main(a.keep_days, a.yes, a.target)))
