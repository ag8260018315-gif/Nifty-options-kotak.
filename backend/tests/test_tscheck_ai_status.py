"""Criterion: Claude Haiku 4.5 integration is available server-side.

GET /api/ai/status must report configured=true, anthropic provider, the exact
Haiku 4.5 model id, all four capabilities, and must never leak any API key or secret.
"""


def test_ai_status_reports_claude_haiku_configuration(client):
    response = client.get("/ai/status")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["configured"] is True
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert set(body["capabilities"]) == {"explain", "chat", "summary", "alert"}

    raw = response.text.lower()
    for leak_marker in ["api_key", "apikey", "secret", "emergent_llm_key", "sk-"]:
        assert leak_marker not in raw, f"response leaked a credential marker: {leak_marker}"
