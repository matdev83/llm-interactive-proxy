import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_request_counter_incremented_on_request(
    gemini_oauth_personal_connector: GeminiOAuthPersonalConnector,
    tmp_path: Path,
) -> None:
    persistence_path = tmp_path / "request_count.json"

    assert gemini_oauth_personal_connector._request_counter is not None
    gemini_oauth_personal_connector._request_counter.persistence_path = persistence_path
    gemini_oauth_personal_connector._request_counter.count = 0
    gemini_oauth_personal_connector._request_counter._save_state()

    # Set mock credentials to prevent AuthenticationError
    gemini_oauth_personal_connector._oauth_credentials = {"access_token": "test-token"}
    gemini_oauth_personal_connector.gemini_api_base_url = "https://mock.googleapis.com"

    # Mock the actual request call to avoid network access and threading issues with respx
    mock_response = requests.Response()
    mock_response.status_code = 200
    mock_response._content = b'data: {"candidates": [{"content": {"parts": [{"text": "response"}]}}]}\n\ndata: [DONE]\n\n'

    # Mock other dependencies
    with (
        patch(
            "google.auth.transport.requests.AuthorizedSession.request",
            return_value=mock_response,
        ),
        patch.object(
            gemini_oauth_personal_connector,
            "_refresh_token_if_needed",
            return_value=True,
        ),
        patch.object(
            gemini_oauth_personal_connector,
            "_discover_project_id",
            new_callable=AsyncMock,
            return_value="test-project",
        ),
        patch.object(
            gemini_oauth_personal_connector.translation_service,
            "to_domain_request",
            return_value=MagicMock(),
        ),
        patch.object(
            gemini_oauth_personal_connector.translation_service,
            "from_domain_to_gemini_request",
            return_value={
                "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
                "generationConfig": {},
            },
        ),
        patch.object(
            gemini_oauth_personal_connector.translation_service,
            "to_domain_stream_chunk",
            return_value={"choices": [{"delta": {"content": "response"}}]},
        ),
    ):
        request_data = {
            "model": "gemini-1.5-pro-latest",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        processed_messages = [{"role": "user", "parts": [{"text": "Hello"}]}]
        effective_model = "models/gemini-1.5-pro-latest"

        await gemini_oauth_personal_connector.chat_completions(
            request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
        )

    # Verify that the counter was incremented and saved
    assert gemini_oauth_personal_connector._request_counter.count == 1
    with open(persistence_path, encoding="utf-8") as f:
        data = json.load(f)
        assert data["count"] == 1
