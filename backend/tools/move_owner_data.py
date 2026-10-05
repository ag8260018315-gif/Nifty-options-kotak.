"""Moves watchlists, chart layouts, alerts, Exchange items and any subscription from one email to another. Dry run by default:

    python tools/move_owner_data.py --from ag8260018315@gmail.com --to admin@edgedesk.in          # shows what would move
    python tools/move_owner_data.py --from ag8260018315@gmail.com --to admin@edgedesk.in --yes    # really moves it

Run it AFTER signing in once as the new email. Nothing in the new email is overwritten; lists and layouts are merged (the new email's own win).
"""
import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main(old: str, new: str, yes: bool) -> int:
    from lib.db import db
    from lib.owner_move import move_owner_data

    report = await move_owner_data(db, old, new, apply=yes)
    if not report:
        print(f"Nothing found under {old}.")
        return 0
    for name, count in report.items():
        print(f"  {name}: {count}")
    print("Moved." if yes else "Dry run: nothing changed. Add --yes to move it.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="old", required=True)
    p.add_argument("--to", dest="new", required=True)
    p.add_argument("--yes", action="store_true")
    a = p.parse_args()
    sys.exit(asyncio.run(main(a.old, a.new, a.yes)))
