"""Move one person's saved data from one email to another (for example when the owner switches to a new sign-in email).

Everything per-user is keyed by the lowercase email: watchlists, chart layouts, alerts and their notifications, Trader's Exchange profile,
listings and conversations, and a paid subscription. Nothing is deleted from the old email unless `apply` is true, and nothing in the new
email is overwritten: if both have data, lists and layouts are merged and the new email's own entries win.
"""
from typing import Any


async def move_owner_data(db: Any, old: str, new: str, apply: bool) -> dict[str, int]:
    old, new = old.strip().lower(), new.strip().lower()
    if not old or not new or old == new:
        raise ValueError("Give two different email addresses.")
    report: dict[str, int] = {}

    async def merge_keyed(collection: str, field: str) -> None:
        """One document per email holding a dict of named things (watchlists / layouts)."""
        src = await db[collection].find_one({"_id": old})
        if not src:
            return
        dst = await db[collection].find_one({"_id": new}) or {"_id": new, field: {}}
        merged = {**src.get(field, {}), **dst.get(field, {})}
        report[collection] = len(src.get(field, {}))
        if apply:
            await db[collection].replace_one({"_id": new}, {**{k: v for k, v in dst.items() if k != field}, "_id": new, field: merged}, upsert=True)
            await db[collection].delete_one({"_id": old})

    async def rename_id(collection: str) -> None:
        """One document per email, nothing to merge: move it only if the new email has none."""
        src = await db[collection].find_one({"_id": old})
        if not src or await db[collection].find_one({"_id": new}):
            return
        report[collection] = 1
        if apply:
            await db[collection].replace_one({"_id": new}, {**src, "_id": new}, upsert=True)
            await db[collection].delete_one({"_id": old})

    async def retag(collection: str, field: str) -> None:
        count = await db[collection].count_documents({field: old})
        if count:
            report[f"{collection}.{field}"] = count
            if apply:
                await db[collection].update_many({field: old}, {"$set": {field: new}})

    await merge_keyed("premium_watchlists", "lists")
    await merge_keyed("premium_layouts", "layouts")
    await rename_id("exchange_profiles")
    await rename_id("billing_subscriptions")
    for collection, field in (("premium_alerts", "owner"), ("premium_alert_events", "owner"), ("exchange_listings", "owner"),
                              ("exchange_threads", "buyer"), ("exchange_threads", "seller"), ("billing_orders", "email")):
        await retag(collection, field)
    return report
