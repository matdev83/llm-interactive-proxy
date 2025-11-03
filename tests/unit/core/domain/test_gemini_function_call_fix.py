"""Tests for Gemini function call/response matching fix."""

from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.translation import Translation


class TestGeminiFunctionCallResponseMatching:
    """Tests to verify function call and response parts are properly matched."""

    def test_assistant_with_tool_calls_excludes_text_content(self) -> None:
        """
        Test that assistant messages with tool_calls do NOT include text content.

        This prevents the Gemini API error:
        "Please ensure that the number of function response parts is equal
        to the number of function call parts"
        """
        request = ChatRequest(
            model="gemini-1.5-pro",
            messages=[
                ChatMessage(role="user", content="What's the weather in Paris?"),
                ChatMessage(
                    role="assistant",
                    content="Let me check the weather for you.",  # This should be excluded
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

        # Find the assistant message (role="model" in Gemini)
        assistant_msg = None
        for content in contents:
            if content["role"] == "model":
                assistant_msg = content
                break

        assert assistant_msg is not None, "Assistant message not found"

        # Verify it has functionCall parts
        parts = assistant_msg["parts"]
        function_call_parts = [p for p in parts if "functionCall" in p]
        text_parts = [p for p in parts if "text" in p]

        assert len(function_call_parts) == 1, "Should have exactly 1 functionCall part"
        assert (
            len(text_parts) == 0
        ), "Should have NO text parts when tool_calls are present"

        # Verify the functionCall structure
        assert function_call_parts[0]["functionCall"]["name"] == "get_weather"

    def test_multiple_tool_responses_grouped_in_single_message(self) -> None:
        """
        Test that multiple consecutive tool responses are grouped into a single user message.

        This ensures the number of functionResponse parts matches the number of
        functionCall parts from the previous assistant message.
        """
        request = ChatRequest(
            model="gemini-1.5-pro",
            messages=[
                ChatMessage(
                    role="user", content="What's the weather in Paris and London?"
                ),
                ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            id="call_123",
                            type="function",
                            function=FunctionCall(
                                name="get_weather", arguments='{"location": "Paris"}'
                            ),
                        ),
                        ToolCall(
                            id="call_456",
                            type="function",
                            function=FunctionCall(
                                name="get_weather", arguments='{"location": "London"}'
                            ),
                        ),
                    ],
                ),
                ChatMessage(
                    role="tool",
                    tool_call_id="call_123",
                    content='{"temperature": 20, "condition": "sunny"}',
                ),
                ChatMessage(
                    role="tool",
                    tool_call_id="call_456",
                    content='{"temperature": 15, "condition": "cloudy"}',
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

        # Find the assistant message with tool calls
        assistant_msg = None
        for content in contents:
            if content["role"] == "model":
                assistant_msg = content
                break

        assert assistant_msg is not None
        function_call_parts = [p for p in assistant_msg["parts"] if "functionCall" in p]
        assert len(function_call_parts) == 2, "Should have 2 functionCall parts"

        # Find the user message with tool responses (should be after assistant)
        tool_response_msg = None
        found_assistant = False
        for content in contents:
            if content["role"] == "model" and not found_assistant:
                found_assistant = True
            elif content["role"] == "user" and found_assistant:
                tool_response_msg = content
                break

        assert tool_response_msg is not None, "Tool response message not found"

        # Verify all tool responses are in a SINGLE message
        function_response_parts = [
            p for p in tool_response_msg["parts"] if "functionResponse" in p
        ]
        assert (
            len(function_response_parts) == 2
        ), "Should have 2 functionResponse parts in ONE message"

        # Verify the responses match the calls
        assert function_response_parts[0]["functionResponse"]["name"] == "get_weather"
        assert function_response_parts[1]["functionResponse"]["name"] == "get_weather"

    def test_single_tool_call_and_response(self) -> None:
        """Test the simple case of one tool call and one tool response."""
        request = ChatRequest(
            model="gemini-1.5-pro",
            messages=[
                ChatMessage(role="user", content="What's 2+2?"),
                ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            id="call_calc",
                            type="function",
                            function=FunctionCall(
                                name="calculate", arguments='{"expression": "2+2"}'
                            ),
                        )
                    ],
                ),
                ChatMessage(
                    role="tool", tool_call_id="call_calc", content='{"result": 4}'
                ),
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "calculate",
                        "description": "Calculate",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)
        contents = gemini_request["contents"]

        # Count functionCall and functionResponse parts
        total_function_calls = 0
        total_function_responses = 0

        for content in contents:
            for part in content["parts"]:
                if "functionCall" in part:
                    total_function_calls += 1
                if "functionResponse" in part:
                    total_function_responses += 1

        assert total_function_calls == 1, "Should have exactly 1 functionCall"
        assert total_function_responses == 1, "Should have exactly 1 functionResponse"
        assert (
            total_function_calls == total_function_responses
        ), "Number of functionCall parts must equal functionResponse parts"

    def test_assistant_without_tool_calls_includes_text(self) -> None:
        """Test that regular assistant messages (without tool calls) still include text."""
        request = ChatRequest(
            model="gemini-1.5-pro",
            messages=[
                ChatMessage(role="user", content="Hello"),
                ChatMessage(role="assistant", content="Hi there! How can I help?"),
            ],
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)
        contents = gemini_request["contents"]

        assistant_msg = None
        for content in contents:
            if content["role"] == "model":
                assistant_msg = content
                break

        assert assistant_msg is not None
        parts = assistant_msg["parts"]
        text_parts = [p for p in parts if "text" in p]

        assert len(text_parts) == 1, "Regular assistant message should have text"
        assert text_parts[0]["text"] == "Hi there! How can I help?"
