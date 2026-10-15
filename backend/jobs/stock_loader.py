"""Loads every NSE stock into the app: the searchable list (names) and daily candles for each one, from Upstox (read-only market data).

Used two ways: by the owner's button in the Access panel (a background task on the server, so no PC is needed) and by
tools/import_upstox_all_stocks.py. The Upstox access token is only ever read from the environment (UPSTOX_ACCESS_TOKEN) and sent
to api.upstox.com; it is never stored, logged or returned. A stock updated recently is skipped, so a stopped run carries on."""
import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from jobs import upstox
from lib import storage
from premium import directory, history

logger = logging.getLogger(__name__)

MIN_STOCKS = 500  # fewer than this means the file changed shape: save nothing rather than a broken list
PAUSE_SECONDS = 0.35  # between Upstox requests, well inside its rate limit
TOKEN_ENV = "UPSTOX_ACCESS_TOKEN"
KB_PER_STOCK_YEAR = 17  # measured: 250 daily candles stored as parallel arrays take about 16.6 KB
SPACE_CHECK_EVERY = 25  # stocks between looks at how full the database is


class LoaderError(RuntimeError):
    """A problem worth showing to the owner as it is written."""


def stop_percent() -> float:
    """The loader stops once the database is this full (LOADER_STOP_PERCENT, default 75), well before writes would start failing."""
    try:
        return min(max(float(os.environ.get("LOADER_STOP_PERCENT", 75)), 20.0), 95.0)
    except ValueError:
        return 75.0


def space_guard(handles: dict[str, Any]) -> Callable[[], Awaitable[str | None]]:
    """A check that returns a plain-words reason to stop when the database is too full, else None (also None if it cannot be measured)."""
    async def check() -> str | None:
        usage = await storage.measure(handles)
        if usage is None or usage["used_mb"] < usage["limit_mb"] * stop_percent() / 100:
            return None
        return (f"Stopped at {usage['used_mb']:.0f} MB of {usage['limit_mb']:.0f} MB used ({usage['percent']}%) so the database does not fill up and block "
                "sign-in. The stocks saved so far keep their history. Free some space, then press Start again to carry on.")

    return check


async def fresh_symbols(db: Any, hours: float) -> set[str]:
    """Symbols whose stored daily history was written in the last `hours` hours (one small query, no candle data transferred)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    done: set[str] = set()
    async for doc in db[history.COLLECTION].find({"interval": "1d"}, {"symbol": 1, "updated_at": 1}):
        try:
            if datetime.fromisoformat(doc["updated_at"]) >= cutoff:
                done.add(doc["symbol"])
        except (KeyError, ValueError):
            continue
    return done


async def load_list(db: Any, client: httpx.AsyncClient) -> list[dict[str, str]]:
    """Download Upstox's list of NSE company shares and save the searchable directory. Returns the items (symbol, name, key)."""
    items = await upstox.stream_directory(client)
    if len(items) < MIN_STOCKS:
        raise LoaderError(f"Upstox listed only {len(items)} stocks, far fewer than expected, so nothing was saved. The file may have changed.")
    await directory.save(db, items, source="upstox")
    return items


async def load_history(
    db: Any, client: httpx.AsyncClient, token: str, items: list[dict[str, str]], *, years: float = 1.0, chunk_days: int = 365,
    fresh_hours: float = 20.0, limit: int = 0, force: bool = False, pause: float = PAUSE_SECONDS,
    progress: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None, stop: Callable[[], bool] | None = None,
    guard: Callable[[], Awaitable[str | None]] | None = None,
) -> dict[str, Any]:
    """Daily candles for each stock into index_history (`SYMBOL:1d`). Raises upstox.UpstoxError when the token is rejected (401); any
    other failure counts that one stock as failed and carries on. `guard` is looked at before the first download and then every
    SPACE_CHECK_EVERY stocks; a reason from it ends the run. Returns {total, skipped, done, saved, failed, stopped, reason}."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=int(365 * years))
    skip = set() if force else await fresh_symbols(db, fresh_hours)
    todo = [i for i in items if i["symbol"] not in skip]
    if limit:
        todo = todo[:limit]
    result = {"total": len(todo), "skipped": len(items) - len(todo), "done": 0, "saved": 0, "failed": 0, "stopped": False, "reason": None}

    async def report(last: str | None) -> None:
        if progress:
            out = progress({**result, "last": last})
            if out is not None:
                await out

    await report(None)
    for item in todo:
        if stop and stop():
            result["stopped"] = True
            break
        if guard and result["done"] % SPACE_CHECK_EVERY == 0:
            reason = await guard()
            if reason:
                result.update(stopped=True, reason=reason)
                break
        bars: list[dict[str, Any]] = []
        try:
            for a, b in upstox.windows(start, end, chunk_days):
                bars.extend(upstox.parse_candles(await upstox.fetch_range(client, token, item["key"], a, b, "day"), session_only=False))
                await asyncio.sleep(pause)
            if bars:
                await history.merge_save(db, item["symbol"], "1d", bars)
                result["saved"] += 1
        except upstox.UpstoxError as exc:
            if "401" in str(exc):
                raise
            result["failed"] += 1
            logger.warning("STOCK_LOADER_FAILED symbol=%s", item["symbol"])
        result["done"] += 1
        if result["done"] % 10 == 0 or result["done"] == result["total"]:
            await report(item["symbol"])
    return result


# ------------------------------------------------------------------ the owner's button: one background job at a time
class Loader:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.stop_requested = False
        self.state: dict[str, Any] = {"phase": "idle", "message": "", "total": 0, "done": 0, "saved": 0, "failed": 0, "started_at": None, "finished_at": None}

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def snapshot(self) -> dict[str, Any]:
        return {**self.state, "running": self.running, "token_set": bool(os.environ.get(TOKEN_ENV, "").strip()), "stop_requested": self.stop_requested and self.running}

    def _begin(self, phase: str, message: str) -> None:
        self.stop_requested = False
        self.state = {"phase": phase, "message": message, "total": 0, "done": 0, "saved": 0, "failed": 0, "started_at": time.time(), "finished_at": None}

    def _end(self, phase: str, message: str) -> None:
        self.state.update(phase=phase, message=message, finished_at=time.time())

    def spawn(self, coro: Awaitable[None]) -> None:
        self.task = asyncio.ensure_future(coro)

    def start(self, db: Any, kind: str, years: float = 1.0, handles: dict[str, Any] | None = None) -> None:
        """Begin the list-only or the list-plus-history job. Raises LoaderError if one is already running or the token is missing."""
        if self.running:
            raise LoaderError("A load is already running. Wait for it to finish or press Stop.")
        if kind == "history" and not os.environ.get(TOKEN_ENV, "").strip():
            raise LoaderError("No Upstox token is set on the server. Add UPSTOX_ACCESS_TOKEN in Render (Environment), save, and try again. The token expires every day.")
        self._begin("list", "Downloading the list of NSE stocks from Upstox…")
        self.spawn(self._run(db, kind, min(max(years, 0.1), 2.0), handles or {"app": db}))

    def stop(self) -> None:
        if self.running:
            self.stop_requested = True

    async def _run(self, db: Any, kind: str, years: float, handles: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                items = await load_list(db, client)
                if kind == "list":
                    self._end("done", f"Done: {len(items):,} NSE stocks are now searchable. Their charts need the daily history step.")
                    return
                self.state.update(phase="history", message="Downloading daily candles…")

                def on_progress(p: dict[str, Any]) -> None:
                    self.state.update(total=p["total"], done=p["done"], saved=p["saved"], failed=p["failed"])

                out = await load_history(db, client, os.environ.get(TOKEN_ENV, "").strip(), items, years=years, progress=on_progress, stop=lambda: self.stop_requested, guard=space_guard(handles))
            if out["reason"]:
                self._end("stopped", f"{out['reason']} ({out['saved']:,} stocks saved.)")
                return
            tail = f"{out['saved']:,} stocks saved" + (f", {out['failed']} failed (press Start again to retry them)" if out["failed"] else "") + (f", {out['skipped']:,} were already up to date" if out["skipped"] else "")
            self._end("stopped" if out["stopped"] else "done", ("Stopped: " if out["stopped"] else "Done: ") + tail + (". Press Start to carry on." if out["stopped"] else "."))
        except upstox.UpstoxError as exc:
            if "401" in str(exc):
                self._end("error", "Upstox rejected the token (it expires every day). Put a new UPSTOX_ACCESS_TOKEN in Render, save, then press Start again. Stocks already saved are skipped.")
            else:
                self._end("error", "Upstox could not be reached properly. Try again in a few minutes.")
        except LoaderError as exc:
            self._end("error", str(exc))
        except asyncio.CancelledError:
            self._end("stopped", "Stopped because the server restarted. Press Start to carry on.")
            raise
        except Exception as exc:  # noqa: BLE001  a loader problem must never disturb the app; the kind of error is enough
            logger.warning("STOCK_LOADER_ERROR kind=%s", type(exc).__name__)
            self._end("error", f"The load stopped unexpectedly ({type(exc).__name__}). Press Start to try again; finished stocks are skipped.")


loader = Loader()
