from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.openai import OpenAIConnector
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend


@pytest.mark.asyncio
async def test_temperature_from_request_data_is_applied(mocker):
    """
    Verify that the 'temperature' from request_data is correctly applied in the payload.
    """
    # 1. Mock dependencies for the constructor
    mock_client = AsyncMock()
    mock_config = MagicMock()

    # 2. Mock parent's _prepare_payload and other methods to isolate the test
    mocker.patch.object(
        OpenAIConnector,
        "_prepare_payload",
        new_callable=AsyncMock,
        return_value={"messages": []},
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_select_model", return_value="test-model"
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_extract_mcp_tool_calls_from_messages", return_value=[]
    )

    # 3. Instantiate the backend with mocks
    backend = ZaiCodingPlanBackend(
        client=mock_client, config=mock_config, translation_service=MagicMock()
    )
    # Disable model refresh for this unit test
    backend.available_models = ["test-model"]

    # 4. Create a mock request_data object with the desired temperature
    temperature_value = 1.0
    mock_request_data = MagicMock()
    mock_request_data.temperature = temperature_value
    mock_request_data.stream = False
    mock_request_data.max_tokens = None
    mock_request_data.top_p = None
    mock_request_data.tools = None
    mock_request_data.tool_choice = None
    mock_request_data.model = "test-model"
    # Add a messages attribute to the mock
    mock_request_data.messages = []

    # 5. Call the method under test
    payload = await backend._prepare_payload(
        request_data=mock_request_data, processed_messages=[]
    )

    # 6. Assert that the temperature in the payload is the one from request_data
    assert "temperature" in payload
    assert payload["temperature"] == temperature_value


@pytest.mark.asyncio
async def test_sensitive_headers_are_redacted_in_logs(mocker, caplog):
    """
    Verify that sensitive headers (Authorization, Set-Cookie, etc.) are redacted when logged.
    This test prevents secret leakage in production logs.
    """
    # 1. Mock dependencies
    mock_client = AsyncMock()
    mock_config = MagicMock()

    # 2. Mock parent's _prepare_payload and other methods to isolate the test
    mocker.patch.object(
        OpenAIConnector,
        "_prepare_payload",
        new_callable=AsyncMock,
        return_value={"messages": []},
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_select_model", return_value="test-model"
    )
    mocker.patch.object(
        ZaiCodingPlanBackend, "_extract_mcp_tool_calls_from_messages", return_value=[]
    )

    # 3. Mock parent's _handle_non_streaming_response to avoid actual HTTP calls
    mock_response = MagicMock()
    mock_response.status_code = 200
    mocker.patch.object(
        OpenAIConnector,
        "_handle_non_streaming_response",
        new_callable=AsyncMock,
        return_value=mock_response,
    )

    # 4. Instantiate the backend with a test API key
    mocker.patch.dict(
        "os.environ",
        {"ZAI_API_KEY": "NOT-A-REAL-KEY-just-for-testing"},
    )
    backend = ZaiCodingPlanBackend(
        client=mock_client,
        config=mock_config,
        translation_service=MagicMock(),
    )
    backend.available_models = ["test-model"]

    # 5. Create mock request data
    mock_request_data = MagicMock()
    mock_request_data.model = "test-model"
    mock_request_data.stream = False
    mock_request_data.messages = []

    # 6. Set API base URL
    backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"

    # 7. Enable logging capture for INFO level
    import logging
    caplog.set_level(logging.INFO)

    # 8. Call the method that triggers header logging
    import contextlib
    with contextlib.suppress(Exception):
        # We expect this to fail due to mocking, we just care about log output
        await backend._handle_non_streaming_response(
            url="https://api.z.ai/api/coding/paas/v4/chat/completions",
            payload={"model": "test-model", "messages": []},
            headers={"Authorization": "Bearer NOT-A-REAL-KEY-just-for-testing"},
            session_id="test-session",
        )

    # 9. Verify that sensitive headers are redacted in logs
    info_logs = [record.message for record in caplog.records if record.levelno == logging.INFO]
    header_logs = [log for log in info_logs if "Headers" in log]

    # At least one header log should exist
    assert len(header_logs) > 0, "Expected header logging to occur"

    # Verify the API key is NOT logged in plain text
    for log in header_logs:
        assert "NOT-A-REAL-KEY-just-for-testing" not in log, \
            f"Full API key should not appear in logs. Found in: {log}"
        assert "***" in log or "[REDACTED]" in log, \
            f"Expected redaction marker in header log: {log}"
