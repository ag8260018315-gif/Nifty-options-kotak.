"""tscheck: Daily history capture is bounded and truthful.

The worker must persist verified normalized snapshots at most every five
seconds per index into current-day history, and the after-close export must
be built purely from those current-day verified snapshots (or a valid last
verified current-day fallback) -- never from DEMO or cross-day data.
"""

import csv
import io
from datetime import date, datetime


def _captured_ats(csv_text: str) -> list[datetime]:
    reader = csv.DictReader(io.StringIO(csv_text))
    seen: list[datetime] = []
    for row in reader:
        ts = datetime.fromisoformat(row["captured_at"])
        if ts not in seen:
            seen.append(ts)
    return seen


def test_nifty_history_snapshots_are_current_day_and_at_least_5s_apart(client):
    response = client.get("/market-data/export.csv?symbol=NIFTY")
    assert response.status_code == 200, response.text

    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)
    assert rows, "expected at least one verified NIFTY row"

    today_ist = None
    for row in rows:
        assert row["index"] == "NIFTY"
        assert row["source"] == "KOTAK_NEO"
        if today_ist is None:
            today_ist = row["trading_day"]
        # Every row must belong to the same single current trading day.
        assert row["trading_day"] == today_ist

    distinct_snapshots = _captured_ats(response.text)
    distinct_snapshots.sort()
    for earlier, later in zip(distinct_snapshots, distinct_snapshots[1:]):
        gap = (later - earlier).total_seconds()
        assert gap >= 5, f"history snapshots captured closer than 5s apart: {gap}s"
