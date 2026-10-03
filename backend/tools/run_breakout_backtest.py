"""Test the breakout watchlist rule on the stored history and save the result for the dashboard.

  python tools/run_breakout_backtest.py                      # default rule: +1% within 30 min, stop -0.5%
  python tools/run_breakout_backtest.py --target 1.5 --stop 0.7 --horizon 45

The result is saved to research_db (breakout_backtests) and shown on the Premium page next to the watchlist.
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")


async def main(args: argparse.Namespace) -> int:
    from jobs.breakout_validation import run_and_store
    from lib.db import research_db
    from premium.backtest import Rule

    result = await run_and_store(research_db, Rule(args.target, args.stop, args.horizon, args.step))
    if result is None:
        print("No stored history yet. Run tools/import_upstox_history.py first.")
        return 1
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} setups={result['setups']} hit_rate={result['hit_rate_pct']}% "
          f"(95% range {result['ci95_low_pct']}-{result['ci95_high_pct']}%) sessions={result['sessions_tested']} validated={result['validated']}")
    for band in result["by_score_band"]:
        print(f"  score {band['band']}: {band['setups']} setups, hit rate {band['hit_rate_pct']}")
    c = result.get("comparison")
    if c:
        print(f"vs chance (plain move test): listed {c['listed_rate_pct']}% of {c['listed_setups']} | random moments {c['random_rate_pct']}% of {c['random_moments']} | "
              f"near resistance, any score {c['near_resistance_rate_pct']}% of {c['near_resistance_moments']}")
        print(f"verdict: {c['verdict']} - {c['verdict_text']}")
    print(result["note"])
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=float, default=1.0)
    p.add_argument("--stop", type=float, default=0.5)
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--step", type=int, default=15, help="minutes between evaluations")
    sys.exit(asyncio.run(main(p.parse_args())))
