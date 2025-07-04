import pytest
import pytest
from fastapi import HTTPException
from pytest_httpx import HTTPXMock

@pytest.mark.httpx_mock()
def test_failover_key_rotation(client, httpx_mock: HTTPXMock):
    # create route
    payload = {
        "model": "dummy",
        "messages": [{"role": "user", "content": "!/create-failover-route(name=r,policy=k)"}],
    }
    client.post("/v1/chat/completions", json=payload)
    payload = {
        "model": "dummy",
        "messages": [{"role": "user", "content": "!/route-append(name=r,openrouter:model-x)"}],
    }
    client.post("/v1/chat/completions", json=payload)

    # Mock the OpenRouter responses
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=429,
        json={"detail": "limit"}
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=200,
        json={"choices": [{"message": {"content": "ok"}}]}
    )

    payload2 = {"model": "r", "messages": [{"role": "user", "content": "hi"}]}
    resp = client.post("/v1/chat/completions", json=payload2)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"].endswith("ok")
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.httpx_mock()
def test_failover_missing_keys(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "G")
    monkeypatch.setenv("LLM_BACKEND", "gemini")

    from src import main as app_main
    from fastapi.testclient import TestClient

    app = app_main.build_app()
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        client.post(
            "/v1/chat/completions",
            json={
                "model": "d",
                "messages": [
                    {"role": "user", "content": "!/create-failover-route(name=r,policy=m)"}
                ],
            },
        )
        client.post(
            "/v1/chat/completions",
            json={
                "model": "d",
                "messages": [
                    {"role": "user", "content": "!/route-append(name=r,openrouter:model-x)"}
                ],
            },
        )
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "r", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 503 # Expect 503 when keys are missing for a configured route

        response_json = resp.json()
        assert "detail" in response_json
        error_detail_obj = response_json["detail"] # The actual OpenAI-like error is nested here

        assert error_detail_obj["object"] == "chat.completion"
        assert error_detail_obj["choices"][0]["finish_reason"] == "error"

        error_message_in_choice = error_detail_obj["choices"][0]["message"]["content"]
        # Check for specific parts of the expected error message
        assert "No API keys configured for the backend: openrouter" in error_message_in_choice or \
               "All backend attempts failed" in error_message_in_choice

        # The 'error' field within the custom OpenAI-like error structure
        assert "error" in error_detail_obj
        custom_error_field = error_detail_obj["error"]
        expected_message_part1 = "No API keys configured for the backend: openrouter"
        expected_message_part2 = "All backend attempts failed." # Corrected capitalization

        assert expected_message_part1 in error_message_in_choice or \
               expected_message_part2 in error_message_in_choice

        if isinstance(custom_error_field, dict):
            assert expected_message_part1 in custom_error_field.get("message", "") or \
                   expected_message_part2 in custom_error_field.get("message", "")
        else:
            assert expected_message_part1 in custom_error_field or \
                   expected_message_part2 in custom_error_field
