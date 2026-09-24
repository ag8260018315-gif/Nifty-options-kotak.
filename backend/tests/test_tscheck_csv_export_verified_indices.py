"""tscheck: Current-day CSV export works for verified live data + is allow-listed/safe.

NIFTY and BANKNIFTY export endpoints must return downloadable text/csv files
for the current IST trading day with metadata, spot, structure, signal, and
21 paired CE/PE option rows. The CSV must only contain normalized KOTAK_NEO
fields, exclude credentials/session URLs, and set safe download headers.
"""

import csv
import io

EXPECTED_COLUMNS = [
    "captured_at", "trading_day", "index", "source", "feed_state", "expiry",
    "spot_ltp", "spot_change", "spot_change_pct", "spot_high", "spot_low",
    "pcr", "max_pain", "bias", "signal", "signal_confidence", "strike", "is_atm",
    "call_ltp", "call_change", "call_oi", "call_oi_change", "call_iv", "call_delta",
    "put_ltp", "put_change", "put_oi", "put_oi_change", "put_iv", "put_delta",
]

FORBIDDEN_MARKERS = (
    "baseurl", "feedurl", "sid", "access_token", "totp_secret",
    "consumer_secret", "mpin", "password", "raw_packet",
)


def _assert_safe_csv(response, symbol):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert f'attachment; filename="{symbol}' in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    text = response.text.lower()
    for marker in FORBIDDEN_MARKERS:
        assert marker not in text, f"forbidden marker '{marker}' leaked into {symbol} CSV"

    reader = csv.reader(io.StringIO(response.text))
    rows = list(reader)
    header = rows[0]
    assert header == EXPECTED_COLUMNS
    data_rows = rows[1:]
    assert len(data_rows) == 21, f"{symbol} CSV expected 21 paired CE/PE rows, got {len(data_rows)}"
    for row in data_rows:
        assert row[2] == symbol
        assert row[3] == "KOTAK_NEO"


def test_nifty_export_returns_21_rows_with_safe_headers(client):
    _assert_safe_csv(client.get("/market-data/export.csv?symbol=NIFTY"), "NIFTY")


def test_banknifty_export_returns_21_rows_with_safe_headers(client):
    _assert_safe_csv(client.get("/market-data/export.csv?symbol=BANKNIFTY"), "BANKNIFTY")


def test_export_rejects_invalid_symbol(client):
    response = client.get("/market-data/export.csv?symbol=NOTREAL")
    assert response.status_code == 422, response.text
