"""Criterion: AI persistence and validation contracts are safe.

POST /api/ai/stream must reject invalid action/symbol/session_id payloads with 422,
and must stream a valid request over SSE without leaking any broker or LLM credential.
"""

import uuid

VALID_SESSION_ID = f"tscheck-ai-validation-{uuid.uuid4().hex}"


def test_stream_rejects_invalid_action(client):
    response = client.post(
        "/ai/stream",
        json={"action": "not-a-real-action", "symbol": "NIFTY", "session_id": VALID_SESSION_ID},
    )
    assert response.status_code == 422, response.text


def test_stream_rejects_invalid_symbol(client):
    response = client.post(
        "/ai/stream",
        json={"action": "explain", "symbol": "DOWJONES", "session_id": VALID_SESSION_ID},
    )
    assert response.status_code == 422, response.text


def test_stream_rejects_short_session_id(client):
    response = client.post(
        "/ai/stream",
        json={"action": "explain", "symbol": "NIFTY", "session_id": "short"},
    )
    assert response.status_code == 422, response.text


def test_stream_valid_request_emits_sse_without_credentials(client):
    session_id = f"tscheck-ai-validation-ok-{uuid.uuid4().hex}"
    with client.stream(
        "POST",
        "/ai/stream",
        json={"action": "explain", "symbol": "NIFTY", "session_id": session_id},
        timeout=60.0,
    ) as response:
        assert response.status_code == 200, response.text
        assert "text/event-stream" in response.headers.get("content-type", "")

        collected = ""
        for chunk in response.iter_text():
            collected += chunk
            if '"done": true' in collected or len(collected) > 6000:
                break

    assert "data:" in collected
    lowered = collected.lower()
    for leak_marker in ["api_key", "apikey", "emergent_llm_key", "sk-ant", "secret"]:
        assert leak_marker not in lowered, f"SSE stream leaked a credential marker: {leak_marker}"
