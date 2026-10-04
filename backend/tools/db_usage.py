"""Shows what is using your MongoDB space (read-only, changes nothing):

    python tools/db_usage.py

Needs MONGO_URL and DB_NAME in backend/.env. Lists every collection in the app database and the research database,
largest first, with document counts and sizes in MB.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main() -> int:
    from lib.db import db, research_db

    for label, handle in (("app database", db), ("research database", research_db)):
        stats = await handle.command("dbStats", scale=1024 * 1024)
        print(f"\n{label} '{handle.name}': data {stats.get('dataSize', 0):.1f} MB, on disk {stats.get('storageSize', 0):.1f} MB, indexes {stats.get('indexSize', 0):.1f} MB")
        rows = []
        for name in await handle.list_collection_names():
            try:
                c = await handle.command("collStats", name, scale=1024 * 1024)
                rows.append((c.get("storageSize", 0) + c.get("totalIndexSize", 0), name, c.get("count", 0), c.get("size", 0)))
            except Exception:  # noqa: BLE001  views or odd collections
                continue
        for total, name, count, size in sorted(rows, reverse=True):
            print(f"  {total:8.1f} MB  {name:32s} {count:>10,} docs  (data {size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
