"""Criterion: Kotak authenticated session restores without repeated after-hours logins.

GET /api/auth/status must keep reporting mode LIVE, configured true, connected true
across at least 35 seconds while the market is closed, and the backend log must not
show a fresh tradeApiLogin call fired during that same window (the encrypted session
should be restored/reused, not re-logged-in on every poll).
"""

import re
import time
from pathlib import Path

BACKEND_LOG = Path("/var/log/supervisor/backend.err.log")


def _tradeapi_login_count() -> int:
    if not BACKEND_LOG.exists():
        return -1
    text = BACKEND_LOG.read_text(errors="ignore")
    return len(re.findall(r"tradeApiLogin\b", text))


def test_auth_status_stays_live_configured_connected_across_35_seconds(client):
    checks = []
    logins_before = _tradeapi_login_count()

    deadline = time.monotonic() + 35
    poll_index = 0
    while time.monotonic() < deadline:
        response = client.get("/auth/status")
        assert response.status_code == 200, response.text
        body = response.json()
        checks.append(body)
        poll_index += 1
        time.sleep(7)

    assert len(checks) >= 4, f"expected multiple polls across 35s, got {len(checks)}"
    for body in checks:
        assert body["mode"] == "LIVE", body
        assert body["configured"] is True, body
        assert body["connected"] is True, body

    logins_after = _tradeapi_login_count()
    if logins_before >= 0 and logins_after >= 0:
        new_logins = logins_after - logins_before
        assert new_logins == 0, (
            f"backend called tradeApiLogin {new_logins} time(s) during a 35s window while "
            "auth/status reported an already-configured, connected LIVE session; the "
            "encrypted session should have been restored/reused instead of re-logging in"
        )
