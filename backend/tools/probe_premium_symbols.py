"""One-time check of the premium instruments on YOUR Kotak account (read-only). Run from backend/ during market hours:

    python tools/probe_premium_symbols.py            # 40 s, reuses the stored server session
    python tools/probe_premium_symbols.py --seconds 90

It resolves the stock tokens from Kotak's scrip master, subscribes SENSEX and the stocks, and prints which ones sent
prices, whether volume and VWAP arrived, and any subscription error. It never prints tokens, sid, UCC, MPIN or TOTP and
places no orders. Exit code: 0 = SENSEX or stock ticks received, 1 = failed, 3 = market closed.
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


async def main(seconds: int) -> int:
    from lib.kotak_client import kotak_client
    from lib.kotak_feed import FeedAuthError, KotakSFeed, _market_open_now
    from lib.multi_feed_worker import INDEX_SUBSCRIPTIONS
    from lib.settings import settings
    from premium.market import PremiumMarket
    from premium.universe import build_plan

    if not settings.live_configured:
        print("FAIL: Kotak LIVE configuration is incomplete in backend/.env.")
        return 1
    if not _market_open_now():
        print("Market is closed (09:15-15:30 IST, Mon-Fri). Run this during the session.")
        return 3
    session = await kotak_client.restore_session()
    if session is None:
        print("FAIL: no stored Kotak session. Press Connect on the dashboard first.")
        return 1
    plan = await build_plan()
    print(f"stocks resolved: {len(plan.scrip_tokens)}  unresolved: {plan.unresolved or 'none'}  plan error: {plan.error or 'none'}")
    market = PremiumMarket()
    market.configure(plan.symbol_by_key, plan.names, plan.kinds)
    seen: dict[str, dict] = {}

    async def on_message(message: dict) -> None:
        return None

    feed = KotakSFeed(session, on_message, premium=plan)
    task = asyncio.create_task(feed.run_once(list(INDEX_SUBSCRIPTIONS.values()), []))
    from premium import market as market_module

    market_module.premium_market = market  # the feed writes into this probe store
    started = time.monotonic()
    try:
        while time.monotonic() - started < seconds:
            if task.done():
                task.result()
                break
            await asyncio.sleep(1)
    except FeedAuthError as exc:
        print(f"FAIL: SFeed rejected authentication ({type(exc).__name__}).")
        return 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    for symbol, quote in market.quotes.items():
        seen[symbol] = quote
    sens = seen.get("SENSEX")
    print(f"SENSEX: {'ticks received, ltp=' + str(sens['ltp']) if sens else 'NO ticks (check PREMIUM_SENSEX_SUBSCRIPTION)'}")
    stocks = [q for s, q in seen.items() if s != "SENSEX"]
    print(f"stocks with prices: {len(stocks)} of {len(plan.scrip_tokens)}")
    print(f"with volume: {sum(1 for q in stocks if q.get('volume'))}  with VWAP: {sum(1 for q in stocks if q.get('vwap'))}")
    for q in stocks[:5]:
        print(f"  {q['symbol']}: ltp={q['ltp']} prev_close={q.get('prev_close')} volume={q.get('volume')}")
    print(f"subscription error: {market.subscription_error or feed.premium and 'none'}")
    return 0 if (sens or stocks) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=40)
    sys.exit(asyncio.run(main(parser.parse_args().seconds)))
