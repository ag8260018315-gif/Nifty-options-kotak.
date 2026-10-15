"""Database space guard for the free 512 MB Atlas plan. Atlas counts the "Data size" of every database on the cluster
(the app, live and research databases together); once it is over the limit every write fails, sign-in codes included."""
import logging
import os
from typing import Any

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

FULL_MESSAGE = "EdgeDesk's database is full right now, so this couldn't be saved. Please try again in a little while."
DOWN_MESSAGE = "The database isn't responding right now. Try again shortly."


def limit_mb() -> float:
    try:
        return float(os.environ.get("DB_LIMIT_MB", 512))
    except ValueError:
        return 512.0


def warn_ratio() -> float:
    try:
        return min(max(float(os.environ.get("DB_WARN_PERCENT", 85)), 10.0), 99.0) / 100
    except ValueError:
        return 0.85


def is_storage_full(exc: BaseException) -> bool:
    """Atlas answers a write over the quota with code 8000, "you are over your space quota"."""
    text = str(exc).lower()
    return getattr(exc, "code", None) == 8000 or "space quota" in text


def explain_db_error(exc: PyMongoError) -> str:
    return FULL_MESSAGE if is_storage_full(exc) else DOWN_MESSAGE


async def measure(handles: dict[str, Any]) -> dict[str, Any] | None:
    """`handles` maps a label to a database. Returns data size per database in MB and the total, or None if it can't be read."""
    sizes: dict[str, float] = {}
    seen: set[str] = set()
    try:
        for label, handle in handles.items():
            if handle.name in seen:  # the app and live databases can be the same one; count it once
                continue
            seen.add(handle.name)
            stats = await handle.command("dbStats")
            sizes[handle.name] = round(float(stats.get("dataSize", 0)) / 1_048_576, 1)
    except Exception as exc:  # noqa: BLE001  measuring must never disturb the app
        logger.warning("STORAGE_MEASURE_ERROR kind=%s", type(exc).__name__)
        return None
    used = round(sum(sizes.values()), 1)
    limit = limit_mb()
    percent = round(used / limit * 100) if limit else 0
    status = "FULL" if used >= limit else "HIGH" if used >= limit * warn_ratio() else "OK"
    return {"limit_mb": limit, "used_mb": used, "percent": percent, "status": status, "databases": sizes}
