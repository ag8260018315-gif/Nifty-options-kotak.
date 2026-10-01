"""Command line: python -m research.cli --csv bars.csv [--symbol NIFTY] [--apply]

Reads historical bars from a CSV or research_db, runs the walk-forward optimisation, stores the report in
research_db, and (only with --apply and status OK) writes config.json for the live engine.
"""
import argparse
import asyncio
import json

from research import data
from research.optimize import optimize
from shared.config import CONFIG_PATH, EngineConfig, load_config, save_config


async def _main(args: argparse.Namespace) -> int:
    from lib.db import research_db  # research storage only

    from research.store import save_optimization

    if args.csv:
        days = data.group_by_day(data.load_csv(args.csv))
        await data.store_bars(research_db, args.symbol, data.load_csv(args.csv), source=f"csv:{args.csv}")
    else:
        days = await data.load_days(research_db, args.symbol, before_day=args.before)
    report = optimize(days, load_config(), horizon_bars=args.horizon, train_days=args.train_days, test_days=args.test_days, symbol=args.symbol)
    await save_optimization(research_db, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"folds", "config"}}, indent=2, default=str))
    if args.apply and report["status"] == "OK":
        print("wrote", save_config(EngineConfig.model_validate(report["config"])), "(live engine reads", CONFIG_PATH, ")")
    elif args.apply:
        print("config NOT written:", report["status"])
    return 0 if report["status"] == "OK" else 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="NIFTY")
    p.add_argument("--csv")
    p.add_argument("--before", help="exclude this trading day and later (YYYY-MM-DD)")
    p.add_argument("--horizon", type=int, default=15)
    p.add_argument("--train-days", type=int, default=10)
    p.add_argument("--test-days", type=int, default=3)
    p.add_argument("--apply", action="store_true")
    raise SystemExit(asyncio.run(_main(p.parse_args())))


if __name__ == "__main__":
    main()
