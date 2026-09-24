"""tscheck: Unverified FINNIFTY data cannot be exported.

Until a real verified FINNIFTY spot plus 21 paired CE/PE rows exist, the
export endpoint must return 404 rather than a DEMO/waiting/short chain CSV.
"""


def test_finnifty_export_returns_404_when_unverified(client):
    response = client.get("/market-data/export.csv?symbol=FINNIFTY")
    assert response.status_code == 404, response.text
    detail = response.json().get("detail", "")
    assert "verified" in detail.lower()
