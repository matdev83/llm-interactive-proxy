"""
Unit tests for Gemini API converter functions.
Tests the conversion logic between Gemini and OpenAI formats.
"""

import json

from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
    FunctionCall,
    ToolCall,
)
from src.gemini_converters import (
    gemini_to_openai_messages,
    gemini_to_openai_request,
    gemini_to_openai_stream_chunk,
    openai_to_gemini_contents,
    openai_to_gemini_response,
    openai_to_gemini_stream_chunk,
)
from src.gemini_models import (
    Blob,
    Content,
    GenerateContentRequest,
    Part,
)


class TestMessageConversion:
    """Test message conversion between formats."""

    def test_gemini_to_openai_simple_message(self) -> None:
        """Test converting simple Gemini content to OpenAI messages."""
        contents = [
            Content(
                parts=[
                    Part(
                        text="Hello, how are you?",
                        functionCall=None,
                        functionResponse=None,
                    )
                ],
                role="user",
            )
        ]

        messages = gemini_to_openai_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello, how are you?"

    def test_gemini_to_openai_model_role(self) -> None:
        """Test converting Gemini model role to OpenAI assistant role."""
        contents = [
            Content(
                parts=[
                    Part(
                        text="I'm doing well, thank you!",
                        functionCall=None,
                        functionResponse=None,
                    )
                ],
                role="model",
            )
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
                    Part(
                        text="Look at this: ", functionCall=None, functionResponse=None
                    ),
                    Part(
                        inline_data=Blob(mime_type="image/png", data="base64data"),
                        functionCall=None,
                        functionResponse=None,
                    ),
                    Part(
                        text=" What do you think?",
                        functionCall=None,
                        functionResponse=None,
                    ),
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

    def test_extract_model_from_path_with_query_string(self) -> None:
        """Model extraction should ignore query parameters."""
        from src.gemini_converters import extract_model_from_gemini_path

        path = "/v1beta/models/gemini-1.5-pro-latest:generateContent?key=secret"

        model = extract_model_from_gemini_path(path)

        assert model == "gemini-1.5-pro-latest"

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

    def test_gemini_stream_chunk_maps_function_call_finish_reason(self) -> None:
        """Gemini streaming finish reasons should map to OpenAI equivalents."""
        chunk = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Done"}]},
                    "finishReason": "FUNCTION_CALL",
                    "index": 0,
                }
            ]
        }

        converted = gemini_to_openai_stream_chunk(f"data: {json.dumps(chunk)}\n\n")
        assert converted.startswith("data: ")

        payload = converted[6:].strip()
        data = json.loads(payload)

        assert data["choices"][0]["finish_reason"] == "function_call"

    def test_gemini_stream_chunk_maps_safety_finish_reason(self) -> None:
        """Safety stops should map to OpenAI content_filter finish reason."""
        chunk = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Filtered"}]},
                    "finishReason": "SAFETY",
                    "index": 0,
                }
            ]
        }

        converted = gemini_to_openai_stream_chunk(f"data: {json.dumps(chunk)}\n\n")
        payload = converted[6:].strip()
        data = json.loads(payload)

        assert data["choices"][0]["finish_reason"] == "content_filter"

    def test_gemini_request_tools_are_converted(self) -> None:
        """Gemini tool declarations should be translated to OpenAI tool definitions."""

        parameters = {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
            },
            "required": ["location"],
        }

        request = GenerateContentRequest(
            contents=[
                Content(
                    parts=[
                        Part(
                            text="What's the weather?",
                            functionCall=None,
                            functionResponse=None,
                        )
                    ],
                    role="user",
                )
            ],
            tools=[
                {
                    "function_declarations": [
                        {
                            "name": "get_weather",
                            "description": "Fetch the current weather.",
                            "parameters": parameters,
                        }
                    ]
                }
            ],
            toolConfig=None,
            safetySettings=None,
            systemInstruction=None,
            generationConfig=None,
            cachedContent=None,
        )

        chat_request = gemini_to_openai_request(request, model="gpt-4o")

        assert chat_request.tools == [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Fetch the current weather.",
                    "parameters": parameters,
                },
            }
        ]

    def test_openai_to_gemini_response_multiple_tool_calls(self) -> None:
        """Tool calls should be preserved when multiple are present."""
        message = ChatCompletionChoiceMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=FunctionCall(name="first", arguments='{"a": 1}'),
                ),
                ToolCall(
                    id="call_2",
                    function=FunctionCall(name="second", arguments='{"b": 2}'),
                ),
            ],
        )
        response = ChatResponse(
            id="resp_1",
            created=123,
            model="gpt-test",
            choices=[
                ChatCompletionChoice(
                    index=0, message=message, finish_reason="tool_calls"
                ),
            ],
        )

        gemini_response = openai_to_gemini_response(response)

        assert gemini_response.candidates is not None
        candidate = gemini_response.candidates[0]
        assert candidate.content is not None
        assert candidate.content.parts is not None
        assert len(candidate.content.parts) == 2
        for part, expected_name in zip(
            candidate.content.parts,
            ["first", "second"],
            strict=False,
        ):
            assert part.function_call is not None
            assert part.function_call["name"] == expected_name
