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
