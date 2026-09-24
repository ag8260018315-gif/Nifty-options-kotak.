"""Acceptance criteria:
- Automatic closing export manifest is prepared (after 15:31 IST, current trading day, non-null
  prepared_at, exactly NIFTY/BANKNIFTY/FINNIFTY items).
- Export archive accurately describes verified data (NIFTY/BANKNIFTY available with
  snapshot_count>=1, row_count>=21 and filenames; FINNIFTY unavailable with no filename).
"""

import datetime as dt


def _current_ist_trading_day() -> str:
    now_utc = dt.datetime.now(dt.timezone.utc)
    ist = now_utc + dt.timedelta(hours=5, minutes=30)
    return ist.date().isoformat()


def test_export_archive_manifest_prepared_after_close(client):
    response = client.get("/market-data/export-archive")
    assert response.status_code == 200, response.text
    body = response.json()

    expected_day = _current_ist_trading_day()
    assert body["trading_day"] == expected_day, body

    assert body["prepared_at"] is not None, "manifest should be auto-prepared after 15:31 IST close"

    symbols = {item["symbol"] for item in body["items"]}
    assert symbols == {"NIFTY", "BANKNIFTY", "FINNIFTY"}, symbols
    assert len(body["items"]) == 3


def test_export_archive_accurately_describes_verified_data(client):
    response = client.get("/market-data/export-archive")
    assert response.status_code == 200, response.text
    items = {item["symbol"]: item for item in response.json()["items"]}

    for symbol in ("NIFTY", "BANKNIFTY"):
        item = items[symbol]
        assert item["available"] is True, item
        assert item["snapshot_count"] >= 1, item
        assert item["row_count"] >= 21, item
        assert item["filename"] == f"{symbol}-{response.json()['trading_day']}-kotak-live.csv", item

    finnifty = items["FINNIFTY"]
    assert finnifty["available"] is False, finnifty
    assert finnifty["filename"] is None, finnifty
    assert finnifty["snapshot_count"] == 0, finnifty
