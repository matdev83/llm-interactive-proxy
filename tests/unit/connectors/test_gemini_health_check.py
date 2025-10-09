from types import SimpleNamespace

import pytest
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector


class _MockAsyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get(self, url: str, headers=None, timeout: float | int = 10.0):  # type: ignore[no-untyped-def]
        self.calls.append(("GET", url))

        class _Resp:
            status_code = 404

        return _Resp()

    async def post(self, url: str, headers=None, json=None, timeout: float | int = 10.0):  # type: ignore[no-untyped-def]
        self.calls.append(("POST", url))

        class _Resp:
            status_code = 200

        return _Resp()


@pytest.mark.asyncio
async def test_health_check_uses_load_code_assist_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = GeminiOAuthPersonalConnector(client=_MockAsyncClient(), config=SimpleNamespace(), translation_service=SimpleNamespace())  # type: ignore[arg-type]
    # Inject minimal state for OAuth
    backend._oauth_credentials = {"access_token": "token"}  # type: ignore[attr-defined]
    backend.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"  # type: ignore[attr-defined]

    mock_client = _MockAsyncClient()
    backend.client = mock_client  # type: ignore[assignment]

    ok = await backend._perform_health_check()
    assert ok is True
    assert mock_client.calls, "Health check did not invoke HTTP client"
    # The fallback should issue a POST to loadCodeAssist after initial GET fails
    methods = [method for method, _ in mock_client.calls]
    assert "POST" in methods
    post_calls = [url for method, url in mock_client.calls if method == "POST"]
    assert post_calls and post_calls[-1].endswith("/v1internal:loadCodeAssist")
