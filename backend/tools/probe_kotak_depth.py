"""One-time check: does YOUR Kotak feed carry bid/ask or market depth for stocks? (read-only, places no orders)

    python tools/probe_kotak_depth.py            # 40 s during market hours (09:15-15:30 IST, Mon-Fri)

It runs the normal stock subscription, looks at the raw messages the Kotak SDK delivers and prints:
  * every field name on a stock message, and which of them look like bid / ask / depth / quantity fields (with sample values);
  * the signature of the SDK's subscribe call, so we can see whether a separate depth subscription exists.
It never prints tokens, session ids, UCC, MPIN or TOTP. Tell Claude what it printed; the app shows bid/ask or depth only
for fields this probe proves exist. Exit code: 0 = ran, 1 = failed, 3 = market closed.
"""
import argparse
import asyncio
import inspect
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
LOOKS = re.compile(r"bid|ask|buy|sell|depth|best|qty|quantity|orders", re.I)


async def main(seconds: int) -> int:
    from neo_api_client.websocket.feed import SFeedScrip, SFeedWebSocket

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
    market = PremiumMarket()
    market.configure(plan.symbol_by_key, plan.names, plan.kinds)
    first: dict[str, object] = {}

    class Probe(KotakSFeed):
        def _to_tick(self, message):  # noqa: ANN001
            if isinstance(message, SFeedScrip) and not first:
                for name in dir(message):
                    if name.startswith("_"):
                        continue
                    try:
                        value = getattr(message, name)
                    except Exception:  # noqa: BLE001
                        continue
                    if not callable(value):
                        first[name] = value
            return super()._to_tick(message)

    async def on_message(message: dict) -> None:
        return None

    feed = Probe(session, on_message, premium=plan)
    task = asyncio.create_task(feed.run_once(list(INDEX_SUBSCRIPTIONS.values()), []))
    started = time.monotonic()
    try:
        while time.monotonic() - started < seconds and not task.done():
            await asyncio.sleep(1)
        if task.done():
            task.result()
    except FeedAuthError:
        print("FAIL: SFeed rejected authentication.")
        return 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    print(f"stock message fields seen: {sorted(first) or 'NO stock message arrived'}")
    hits = {k: v for k, v in first.items() if LOOKS.search(k)}
    print("fields that look like bid/ask/depth/quantity:", hits or "NONE")
    for method in ("subscribe", "subscribe_index"):
        fn = getattr(SFeedWebSocket, method, None)
        print(f"SDK {method}{inspect.signature(fn) if fn else ': not found'}")
    print("other SDK methods mentioning depth:", [m for m in dir(SFeedWebSocket) if "depth" in m.lower()] or "none")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=int, default=40)
    sys.exit(asyncio.run(main(p.parse_args().seconds)))
