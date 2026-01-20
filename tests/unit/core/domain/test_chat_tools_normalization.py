from src.core.domain.chat import ChatMessage, ChatRequest


def test_chat_request_normalizes_properties_list_in_tools() -> None:
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "tool_test",
                    "description": "Test tool",
                    "parameters": {
                        "type": "object",
                        "properties": [
                            {"key": "path", "value": {"type": "string"}},
                            {
                                "key": "options",
                                "value": {
                                    "type": "object",
                                    "properties": [
                                        {
                                            "key": "recursive",
                                            "value": {"type": "boolean"},
                                        }
                                    ],
                                },
                            },
                        ],
                        "required": ["path"],
                    },
                },
            }
        ],
    )

    tools = request.tools
    assert tools is not None
    params = tools[0]["function"]["parameters"]
    assert params["properties"]["path"]["type"] == "string"
    assert (
        params["properties"]["options"]["properties"]["recursive"]["type"] == "boolean"
    )


def test_chat_request_drops_invalid_properties_list() -> None:
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "tool_test",
                    "description": "Test tool",
                    "parameters": {
                        "type": "object",
                        "properties": [{"value": {"type": "string"}}],
                    },
                },
            }
        ],
    )

    tools = request.tools
    assert tools is not None
    params = tools[0]["function"]["parameters"]
    assert params["properties"] == {}
