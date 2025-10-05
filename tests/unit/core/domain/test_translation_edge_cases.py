import json
from unittest.mock import AsyncMock

import pytest
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware
from src.tool_call_loop.tracker import ToolCallSignature


def test_tool_call_signature_with_malformed_json_arguments():
    """
    Verify that ToolCallSignature.from_tool_call handles malformed JSON
    in arguments gracefully by repairing it.
    """
    tool_name = "test_tool"
    # Malformed JSON with a trailing comma and missing value
    malformed_json_args = '{"param1": "value1", "param2":}'
    # json-repair will fix the missing value with an empty string
    repaired_json = {"param1": "value1", "param2": ""}
    canonical_repaired_json = json.dumps(repaired_json, sort_keys=True)

    # This should not raise an exception
    signature = ToolCallSignature.from_tool_call(
        tool_name=tool_name, arguments=malformed_json_args
    )

    # The canonical arguments should be based on the REPAIRED json
    assert signature.arguments_signature == canonical_repaired_json
    assert signature.raw_arguments == malformed_json_args
    assert signature.tool_name == tool_name


@pytest.mark.asyncio
async def test_tool_call_reactor_middleware_with_malformed_json_arguments():
    """
    Verify that ToolCallReactorMiddleware handles malformed JSON in tool call
    arguments by repairing it before passing it to the reactor.
    """
    # 1. Setup
    mock_reactor = AsyncMock()
    middleware = ToolCallReactorMiddleware(tool_call_reactor=mock_reactor)

    tool_name = "repair_test_tool"
    malformed_json_args = '{"key": "value",}'  # Malformed JSON with trailing comma
    repaired_args = {"key": "value"}

    # 2. Create a response with a tool call containing malformed JSON
    response_content = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": malformed_json_args,
                            },
                        }
                    ]
                }
            }
        ]
    }
    response = ProcessedResponse(content=json.dumps(response_content))

    # 3. Process the response through the middleware
    await middleware.process(response=response, session_id="test_session", context={})

    # 4. Assert that the reactor received the REPAIRED arguments
    mock_reactor.process_tool_call.assert_called_once()
    call_context: ToolCallContext = mock_reactor.process_tool_call.call_args[0][0]

    assert call_context.tool_name == tool_name
    assert call_context.tool_arguments == repaired_args


def test_malformed_base64_data_url():
    """
    Test that a malformed base64 data URL is handled gracefully.
    """
    # This is not a valid data URL because it's missing the 'base64,' part
    malformed_url = "data:image/png;iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    from src.core.domain.multimodal import ContentPart

    with pytest.raises(ValueError, match="Invalid data URL format"):
        ContentPart.from_data_url(malformed_url)
