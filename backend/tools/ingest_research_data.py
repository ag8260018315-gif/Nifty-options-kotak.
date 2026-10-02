"""Manual run of the one-way bridge (the backend also does this automatically every trading day).

  python tools/ingest_research_data.py --symbol NIFTY
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main(symbol: str) -> None:
    from jobs.bridge import ingest_symbol
    from lib.db import live_db, research_db

    copied, days = await ingest_symbol(live_db, research_db, symbol)
    print(f"copied {copied} bars from {days} completed sessions for {symbol}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="NIFTY")
    asyncio.run(main(p.parse_args().symbol))
