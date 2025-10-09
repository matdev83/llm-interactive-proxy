"""
Unit tests for Gemini API converter functions.
Tests the conversion logic between Gemini and OpenAI formats.
"""

import json

from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.gemini_converters import (
    gemini_to_openai_messages,
    openai_to_gemini_contents,
    openai_to_gemini_stream_chunk,
)
from src.gemini_models import (
    Blob,
    Content,
    Part,
)


class TestMessageConversion:
    """Test message conversion between formats."""

    def test_gemini_to_openai_simple_message(self) -> None:
        """Test converting simple Gemini content to OpenAI messages."""
        contents = [Content(parts=[Part(text="Hello, how are you?")], role="user")]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello, how are you?"

    def test_gemini_to_openai_model_role(self) -> None:
        """Test converting Gemini model role to OpenAI assistant role."""
        contents = [
            Content(parts=[Part(text="I'm doing well, thank you!")], role="model")
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].content == "I'm doing well, thank you!"

    def test_gemini_to_openai_multiple_parts(self) -> None:
        """Test converting Gemini content with multiple parts."""
        contents = [
            Content(
                parts=[
                    Part(text="Look at this: "),
                    Part(inline_data=Blob(mime_type="image/png", data="base64data")),
                    Part(text=" What do you think?"),
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "user"
        expected_content = (
            "Look at this: \n[Attachment: image/png]\n What do you think?"
        )
        assert messages[0].content == expected_content

    def test_openai_to_gemini_simple_message(self) -> None:
        """Test converting OpenAI message to Gemini content."""
        messages = [ChatMessage(role="user", content="Hello!")]

        contents = openai_to_gemini_contents(messages)

        assert len(contents) == 1
        assert contents[0].role == "user"
        assert len(contents[0].parts) == 1
        assert contents[0].parts[0].text == "Hello!"

    def test_openai_to_gemini_assistant_role(self) -> None:
        """Test converting OpenAI assistant role to Gemini model role."""
        messages = [ChatMessage(role="assistant", content="Hello there!")]

        contents = openai_to_gemini_contents(messages)

        assert len(contents) == 1
        assert contents[0].role == "model"
        assert contents[0].parts[0].text == "Hello there!"

    def test_openai_to_gemini_system_role(self) -> None:
        """Test that system messages are filtered out."""
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello!"),
        ]

        contents = openai_to_gemini_contents(messages)

        # Only user message should remain, system message filtered out
        assert len(contents) == 1
        assert contents[0].role == "user"
        assert contents[0].parts[0].text == "Hello!"

    def test_openai_to_gemini_tool_call(self) -> None:
        """Ensure assistant tool calls translate to Gemini functionCall parts."""
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="lookup_weather", arguments='{"city": "Paris"}'),
        )
        messages = [
            ChatMessage(role="assistant", content=None, tool_calls=[tool_call])
        ]

        contents = openai_to_gemini_contents(messages)

        assert len(contents) == 1
        content = contents[0]
        assert content.role == "model"
        assert len(content.parts) == 1
        assert content.parts[0].function_call == {
            "name": "lookup_weather",
            "args": {"city": "Paris"},
        }

    def test_openai_to_gemini_tool_response(self) -> None:
        """Ensure tool responses become Gemini functionResponse parts."""
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="lookup_weather", arguments="{}"),
        )
        messages = [
            ChatMessage(role="assistant", content=None, tool_calls=[tool_call]),
            ChatMessage(
                role="tool",
                tool_call_id="call_1",
                content='{"result": "Sunny"}',
            ),
        ]

        contents = openai_to_gemini_contents(messages)

        assert len(contents) == 2
        response_content = contents[1]
        assert response_content.role == "function"
        assert len(response_content.parts) == 1
        assert response_content.parts[0].function_response == {
            "name": "lookup_weather",
            "response": {"result": "Sunny"},
        }

    def test_openai_stream_chunk_with_structured_content(self) -> None:
        """Ensure streaming conversion handles list-based delta content."""
        chunk = (
            'data: {"choices": [{"index": 0, "delta": {'
            '"content": [{"type": "text", "text": "Hello"}]}}]}\n\n'
        )

        gemini_chunk = openai_to_gemini_stream_chunk(chunk)
        assert gemini_chunk.startswith("data: ")

        payload = gemini_chunk[6:].strip()
        data = json.loads(payload)

        assert data["candidates"][0]["content"]["parts"][0]["text"] == "Hello"
