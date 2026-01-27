from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.translation import Translation


def test_debug_gemini_request():
    request = ChatRequest(
        model="gemini-1.5-pro",
        messages=[
            ChatMessage(role="user", content="What's the weather in Paris?"),
            ChatMessage(
                role="assistant",
                content="Let me check the weather for you.",
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        type="function",
                        function=FunctionCall(
                            name="get_weather", arguments='{"location": "Paris"}'
                        ),
                    )
                ],
            ),
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    gemini_request = Translation.from_domain_to_gemini_request(request)
    contents = gemini_request["contents"]
    for content in contents:
        if content["role"] == "model":
            print(f"\nModel parts: {content['parts']}")
            break


if __name__ == "__main__":
    test_debug_gemini_request()
