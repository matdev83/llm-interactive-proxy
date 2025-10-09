"""
Tests for Gemini translation utilities.

This module tests the translation between Gemini API format and other formats.
"""

from src.core.domain.gemini_translation import (
    canonical_response_to_gemini_response,
    gemini_content_to_chat_messages,
    gemini_request_to_canonical_request,
)
from src.core.domain.translation import Translation


class TestGeminiContentToMessages:
    """Tests for converting Gemini content to ChatMessage objects."""

    def test_simple_text_content(self) -> None:
        """Test conversion of simple text content."""
        contents = [
            {"role": "user", "parts": [{"text": "Hello, how are you?"}]},
            {
                "role": "model",
                "parts": [{"text": "I'm doing well, how can I help you today?"}],
            },
        ]

        messages = gemini_content_to_chat_messages(contents)

        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello, how are you?"
        assert messages[1].role == "model"
        assert messages[1].content == "I'm doing well, how can I help you today?"

    def test_multimodal_content(self) -> None:
        """Test conversion of multimodal content."""
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": "What's in this image?"},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": "https://example.com/image.jpg",
                        }
                    },
                ],
            }
        ]

        messages = gemini_content_to_chat_messages(contents)

        assert len(messages) == 1
        assert messages[0].role == "user"
        assert isinstance(messages[0].content, list)
        assert len(messages[0].content) == 2
        assert messages[0].content[0].type == "text"
        assert messages[0].content[0].text == "What's in this image?"
        assert messages[0].content[1].type == "image_url"
        assert messages[0].content[1].image_url.url == "https://example.com/image.jpg"


class TestGeminiRequestToCanonical:
    """Tests for converting Gemini requests to canonical requests."""

    def test_simple_request(self) -> None:
        """Test conversion of a simple Gemini request."""
        request = {
            "model": "gemini-1.5-pro",
            "contents": [{"role": "user", "parts": [{"text": "Hello, how are you?"}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "maxOutputTokens": 1000,
                "stopSequences": ["END"],
            },
        }

        canonical = gemini_request_to_canonical_request(request)

        assert canonical.model == "gemini-1.5-pro"
        assert len(canonical.messages) == 1
        assert canonical.messages[0].role == "user"
        assert canonical.messages[0].content == "Hello, how are you?"
        assert canonical.temperature == 0.7
        assert canonical.top_p == 0.9
        assert canonical.max_tokens == 1000
        assert canonical.stop == ["END"]

    def test_request_with_system_instruction(self) -> None:
        """Test conversion of a Gemini request with system instruction."""
        request = {
            "model": "gemini-1.5-pro",
            "contents": [{"role": "user", "parts": [{"text": "Hello, how are you?"}]}],
            "systemInstruction": {"parts": [{"text": "You are a helpful assistant."}]},
        }

        canonical = gemini_request_to_canonical_request(request)

        assert len(canonical.messages) == 2
        assert canonical.messages[0].role == "system"
        assert canonical.messages[0].content == "You are a helpful assistant."
        assert canonical.messages[1].role == "user"
        assert canonical.messages[1].content == "Hello, how are you?"

    def test_request_with_tools(self) -> None:
        """Test conversion of a Gemini request with tools."""
        request = {
            "model": "gemini-1.5-pro",
            "contents": [
                {"role": "user", "parts": [{"text": "What's the weather in Paris?"}]}
            ],
            "tools": [
                {
                    "function_declarations": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather in a given location",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "location": {
                                        "type": "string",
                                        "description": "The city and state, e.g. San Francisco, CA",
                                    }
                                },
                                "required": ["location"],
                            },
                        }
                    ]
                }
            ],
        }

        canonical = gemini_request_to_canonical_request(request)

        assert canonical.tools is not None
        assert len(canonical.tools) == 1
        assert canonical.tools[0]["type"] == "function"  # type: ignore
        assert canonical.tools[0]["function"]["name"] == "get_weather"  # type: ignore
        assert "parameters" in canonical.tools[0]["function"]  # type: ignore
        assert "location" in canonical.tools[0]["function"]["parameters"]["properties"]  # type: ignore


class TestCanonicalResponseToGemini:
    """Tests for converting canonical responses to Gemini format."""

    def test_simple_response(self) -> None:
        """Test conversion of a simple response."""
        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hello, how can I help you today?",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
        }

        gemini_response = canonical_response_to_gemini_response(response)

        assert "candidates" in gemini_response
        assert len(gemini_response["candidates"]) == 1
        assert (
            gemini_response["candidates"][0]["content"]["parts"][0]["text"]
            == "Hello, how can I help you today?"
        )
        assert gemini_response["candidates"][0]["content"]["role"] == "model"
        assert gemini_response["candidates"][0]["finishReason"] == "STOP"
        assert "usageMetadata" in gemini_response
        assert gemini_response["usageMetadata"]["promptTokenCount"] == 10
        assert gemini_response["usageMetadata"]["candidatesTokenCount"] == 15
        assert gemini_response["usageMetadata"]["totalTokenCount"] == 25

    def test_response_with_tool_calls(self) -> None:
        """Test conversion of a response with tool calls."""
        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "I'll check the weather for you.",
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"location": "Paris"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

        gemini_response = canonical_response_to_gemini_response(response)

        assert "candidates" in gemini_response
        assert len(gemini_response["candidates"]) == 1

        # Check text content
        assert (
            gemini_response["candidates"][0]["content"]["parts"][0]["text"]
            == "I'll check the weather for you."
        )

        # Check function call
        assert len(gemini_response["candidates"]) > 0
        assert "content" in gemini_response["candidates"][0]
        assert "parts" in gemini_response["candidates"][0]["content"]
        assert len(gemini_response["candidates"][0]["content"]["parts"]) > 1

        function_part = gemini_response["candidates"][0]["content"]["parts"][1]
        assert "functionCall" in function_part
        assert function_part["functionCall"]["name"] == "get_weather"
        assert function_part["functionCall"]["args"] == '{"location": "Paris"}'

        # Check finish reason
        assert gemini_response["candidates"][0]["finishReason"] == "TOOL_CALLS"

    def test_response_with_missing_finish_reason(self) -> None:
        """Test conversion when finish_reason is missing or None."""
        response = {
            "id": "chatcmpl-456",
            "object": "chat.completion",
            "created": 1677652299,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Partial response without finish reason.",
                    },
                    "finish_reason": None,
                }
            ],
        }

        gemini_response = canonical_response_to_gemini_response(response)

        assert gemini_response["candidates"][0]["finishReason"] == "STOP"


class TestTranslationIntegration:
    """Integration tests for the Translation class."""

    def test_gemini_to_domain_request(self) -> None:
        """Test the gemini_to_domain_request method."""
        request = {
            "model": "gemini-1.5-pro",
            "contents": [{"role": "user", "parts": [{"text": "Hello, how are you?"}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "maxOutputTokens": 1000,
            },
        }

        domain_request = Translation.gemini_to_domain_request(request)

        assert domain_request.model == "gemini-1.5-pro"
        assert len(domain_request.messages) == 1
        assert domain_request.messages[0].role == "user"
        assert domain_request.messages[0].content == "Hello, how are you?"
        assert domain_request.temperature == 0.7
        assert domain_request.top_p == 0.9
        assert domain_request.max_tokens == 1000

    def test_gemini_to_domain_response(self) -> None:
        """Test the gemini_to_domain_response method."""
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Hello, I'm doing well. How can I help you today?"}
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 15,
                "totalTokenCount": 25,
            },
        }

        domain_response = Translation.gemini_to_domain_response(response)

        assert domain_response.object == "chat.completion"
        assert len(domain_response.choices) == 1
        assert domain_response.choices[0].message.role == "assistant"
        assert (
            domain_response.choices[0].message.content
            == "Hello, I'm doing well. How can I help you today?"
        )
        assert domain_response.choices[0].finish_reason == "stop"

        # Check usage metadata
        assert domain_response.usage is not None
        assert "prompt_tokens" in domain_response.usage
        assert domain_response.usage["prompt_tokens"] == 10
        assert "completion_tokens" in domain_response.usage
        assert domain_response.usage["completion_tokens"] == 15
        assert "total_tokens" in domain_response.usage
        assert domain_response.usage["total_tokens"] == 25
