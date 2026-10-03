"""Test the stock signal engine on the stored 1-minute history and save win rate / drawdown for every stock (shown on each stock page).

  python tools/run_signal_backtest.py
  python tools/run_signal_backtest.py --horizon 60 --step 30 --cost 0.05

Needs MONGO_URL and DB_NAME in backend/.env. It takes a while; progress is printed after each stock.
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main(args: argparse.Namespace) -> int:
    from jobs.signal_validation import run_and_store
    from lib.db import research_db
    from premium.signal_backtest import Rule

    started = time.monotonic()

    def progress(done: int, total: int, symbol: str, trades: int) -> None:
        elapsed = time.monotonic() - started
        print(f"  {done}/{total} {symbol}: {trades} trades; {elapsed / 60:.1f} min so far, about {elapsed / done * (total - done) / 60:.1f} min left", flush=True)

    print("Replaying the signal engine over the stored history. This takes a while.", flush=True)
    result = await run_and_store(research_db, Rule(args.horizon, args.step, args.cost), progress)
    if result is None:
        print("No stored 1-minute history yet. Run tools/import_upstox_history.py first.")
        return 1
    print(f"Overall: {result['trades']} trades over {result.get('stocks_tested')} stocks. Win rate {result.get('win_rate_pct')}% (95% range {result.get('win_rate_ci95_pct')}), "
          f"average {result.get('avg_r')} R, max drawdown {result.get('max_drawdown_r')} R, profit factor {result.get('profit_factor')}.")
    print(result["note"])
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", type=int, default=90)
    p.add_argument("--step", type=int, default=15)
    p.add_argument("--cost", type=float, default=0.05, help="round-trip cost as %% of price")
    sys.exit(asyncio.run(main(p.parse_args())))
