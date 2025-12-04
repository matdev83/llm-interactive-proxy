"""Tests for OpenAI Responses API translation methods."""

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
)
from src.core.domain.responses_api import JsonSchema, ResponseFormat, ResponsesRequest
from src.core.domain.translation import Translation


class TestOpenAIResponsesTranslation:
    """Test OpenAI Responses API translation methods."""

    def test_responses_to_domain_request_dict_input(self):
        """Test converting a Responses API request dict to domain request."""
        request_dict = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test_schema",
                    "description": "A test schema",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                    "strict": True,
                },
            },
            "max_tokens": 100,
            "temperature": 0.7,
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.model == "gpt-4"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.max_tokens == 100
        assert result.temperature == 0.7
        assert result.extra_body is not None
        assert "response_format" in result.extra_body

    def test_responses_to_domain_request_pydantic_input(self):
        """Test converting a Responses API request object to domain request."""
        json_schema = JsonSchema(
            name="test_schema",
            description="A test schema",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
            strict=True,
        )
        response_format = ResponseFormat(type="json_schema", json_schema=json_schema)

        request_obj = ResponsesRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            response_format=response_format,
            max_tokens=100,
            temperature=0.7,
        )

        result = Translation.responses_to_domain_request(request_obj)

        assert isinstance(result, CanonicalChatRequest)
        assert result.model == "gpt-4"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "Hello"
        assert result.max_tokens == 100
        assert result.temperature == 0.7
        assert result.extra_body is not None
        assert "response_format" in result.extra_body

    def test_responses_to_domain_request_without_response_format(self):
        """Requests without response_format should still translate successfully."""

        request_dict = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.model == "gpt-4o-mini"
        assert result.extra_body == {}

    def test_from_domain_to_responses_request(self):
        """Test converting a domain request to Responses API request format."""
        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test_schema",
                    "description": "A test schema",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                    "strict": True,
                },
            }
        }

        domain_request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            temperature=0.7,
            extra_body=extra_body,
        )

        result = Translation.from_domain_to_responses_request(domain_request)

        assert isinstance(result, dict)
        assert result["model"] == "gpt-4"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "Hello"
        assert result["max_tokens"] == 100
        assert result["temperature"] == 0.7
        assert "response_format" in result
        assert result["response_format"]["type"] == "json_schema"

    def test_from_domain_to_responses_request_without_response_format(self):
        """Test converting a domain request without response_format."""
        domain_request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            temperature=0.7,
            extra_body={"metadata": {"foo": "bar"}},
        )

        result = Translation.from_domain_to_responses_request(domain_request)

        assert isinstance(result, dict)
        assert result["model"] == "gpt-4"
        assert "response_format" not in result
        assert result.get("metadata") == {"foo": "bar"}

    def test_from_domain_to_responses_request_preserves_extra_body_fields(self):
        """Ensure arbitrary extra_body fields are included in the Responses payload."""
        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test_schema",
                    "description": "A test schema",
                    "schema": {"type": "object"},
                    "strict": True,
                },
            },
            "metadata": {"foo": "bar"},
            "experimental_flag": True,
            "session_id": "should-be-filtered",
        }

        domain_request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            extra_body=extra_body,
        )

        result = Translation.from_domain_to_responses_request(domain_request)

        assert result["response_format"]["type"] == "json_schema"
        assert result.get("metadata") == {"foo": "bar"}
        assert "experimental_flag" not in result
        assert "session_id" not in result

    def test_from_domain_to_responses_response(self):
        """Test converting a domain response to Responses API response format."""
        domain_response = ChatResponse(
            id="resp-123",
            object="chat.completion",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content='{"name": "John Doe"}'
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        result = Translation.from_domain_to_responses_response(domain_response)

        assert isinstance(result, dict)
        assert result["id"] == "resp-123"
        assert result["object"] == "response"
        assert result["created"] == 1234567890
        assert result["model"] == "gpt-4"
        assert len(result["choices"]) == 1
        assert "output" in result
        assert len(result["output"]) == 1

        choice = result["choices"][0]
        assert choice["index"] == 0
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == '{"name": "John Doe"}'
        assert choice["message"]["parsed"] == {"name": "John Doe"}
        assert choice["finish_reason"] == "stop"

        output_item = result["output"][0]
        assert output_item["role"] == "assistant"
        assert output_item["status"] == "completed"
        assert output_item["content"] == [
            {"type": "output_text", "text": '{"name": "John Doe"}'}
        ]
        assert result["output_text"] == ['{"name": "John Doe"}']

        assert result["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }

    def test_from_domain_to_responses_response_with_markdown_json(self):
        """Test converting a domain response with JSON wrapped in markdown."""
        domain_response = ChatResponse(
            id="resp-123",
            object="chat.completion",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content='```json\n{"name": "John Doe"}\n```'
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        result = Translation.from_domain_to_responses_response(domain_response)

        choice = result["choices"][0]
        assert choice["message"]["content"] == '{"name": "John Doe"}'
        assert choice["message"]["parsed"] == {"name": "John Doe"}

        output_item = result["output"][0]
        assert output_item["content"][0]["text"] == '{"name": "John Doe"}'
        assert result["output_text"] == ['{"name": "John Doe"}']

    def test_from_domain_to_responses_response_with_invalid_json(self):
        """Test converting a domain response with invalid JSON content."""
        domain_response = ChatResponse(
            id="resp-123",
            object="chat.completion",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content="This is not JSON content"
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        result = Translation.from_domain_to_responses_response(domain_response)

        choice = result["choices"][0]
        assert choice["message"]["content"] == "This is not JSON content"
        assert choice["message"]["parsed"] is None

        output_item = result["output"][0]
        assert output_item["content"][0]["text"] == "This is not JSON content"
        assert result["output_text"] == ["This is not JSON content"]

    def test_from_domain_to_responses_response_with_embedded_json(self):
        """Test converting a domain response with JSON embedded in text."""
        domain_response = ChatResponse(
            id="resp-123",
            object="chat.completion",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content='Here is the result: {"name": "John Doe"} as requested.',
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        result = Translation.from_domain_to_responses_response(domain_response)

        choice = result["choices"][0]
        assert choice["message"]["content"] == '{"name": "John Doe"}'
        assert choice["message"]["parsed"] == {"name": "John Doe"}

        output_item = result["output"][0]
        assert output_item["content"][0]["text"] == '{"name": "John Doe"}'
        assert result["output_text"] == ['{"name": "John Doe"}']

    def test_responses_to_domain_response_output_text_fallback(self):
        """Test handling Responses API payloads that only provide output_text."""
        responses_response = {
            "id": "resp-456",
            "object": "response",
            "created": 1700000000,
            "model": "gpt-4.1",
            "output": [],
            "output_text": ["First part", " second part"],
            "status": "completed",
            "usage": {"input_tokens": 3, "output_tokens": 5},
        }

        result = Translation.responses_to_domain_response(responses_response)

        assert isinstance(result, CanonicalChatResponse)
        assert len(result.choices) == 1
        choice = result.choices[0]
        assert choice.message is not None
        assert choice.message.content == "First part second part"
        assert choice.finish_reason == "stop"
        assert result.usage == {
            "prompt_tokens": 3,
            "completion_tokens": 5,
            "total_tokens": 8,
        }


class TestResponsesApiNewFields:
    """Test new OpenAI Responses API fields added for spec parity."""

    def test_responses_request_with_input_field(self):
        """Test Responses API request with 'input' field instead of messages."""
        request_dict = {
            "model": "gpt-4o",
            "input": "What is the weather today?",
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.model == "gpt-4o"
        assert len(result.messages) == 1
        assert result.messages[0].role == "user"
        assert result.messages[0].content == "What is the weather today?"

    def test_responses_request_with_instructions(self):
        """Test Responses API request with instructions field."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "instructions": "You are a helpful assistant. Be concise.",
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.system_prompt == "You are a helpful assistant. Be concise."

    def test_responses_request_with_max_output_tokens(self):
        """Test Responses API request with max_output_tokens field."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_output_tokens": 1500,
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        # max_output_tokens should be mapped to max_completion_tokens
        assert result.max_completion_tokens == 1500
        # And also max_tokens for backward compatibility
        assert result.max_tokens == 1500

    def test_responses_request_with_tools(self):
        """Test Responses API request with tools array."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Get weather for NYC"}],
            "tools": [
                {
                    "type": "function",
                    "name": "get_weather",
                    "description": "Get weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                }
            ],
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.tools is not None
        assert len(result.tools) == 1
        assert result.tools[0]["name"] == "get_weather"
        assert result.tool_choice == "auto"
        assert result.parallel_tool_calls is True

    def test_responses_request_with_reasoning_config(self):
        """Test Responses API request with reasoning configuration."""
        request_dict = {
            "model": "gpt-5.1",
            "messages": [{"role": "user", "content": "Solve this complex problem"}],
            "reasoning": {"effort": "high", "summary": "detailed"},
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.reasoning is not None
        assert result.reasoning["effort"] == "high"
        assert result.reasoning_effort == "high"

    def test_responses_request_with_service_tier(self):
        """Test Responses API request with service_tier."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "service_tier": "priority",
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.service_tier == "priority"

    def test_responses_request_with_metadata(self):
        """Test Responses API request with metadata."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "metadata": {"user_id": "user123", "session": "session456"},
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.request_metadata == {
            "user_id": "user123",
            "session": "session456",
        }

    def test_responses_request_with_conversation_fields(self):
        """Test Responses API request with multi-turn conversation fields."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Continue our discussion"}],
            "previous_response_id": "resp-abc123",
            "conversation": "conv_xyz789",
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.extra_body is not None
        assert result.extra_body.get("previous_response_id") == "resp-abc123"
        assert result.extra_body.get("conversation") == "conv_xyz789"

    def test_responses_request_with_advanced_options(self):
        """Test Responses API request with advanced options."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Store this for later"}],
            "store": True,
            "background": False,
            "truncation": "auto",
            "include": ["message.output_text.logprobs", "reasoning.encrypted_content"],
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.extra_body is not None
        assert result.extra_body.get("store") is True
        assert result.extra_body.get("background") is False
        assert result.extra_body.get("truncation") == "auto"
        assert result.extra_body.get("include") == [
            "message.output_text.logprobs",
            "reasoning.encrypted_content",
        ]

    def test_responses_request_with_top_logprobs(self):
        """Test Responses API request with top_logprobs."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test"}],
            "top_logprobs": 5,
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.top_logprobs == 5

    def test_responses_request_with_prompt_caching(self):
        """Test Responses API request with prompt caching fields."""
        request_dict = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test"}],
            "prompt_cache_key": "test-cache-key",
            "prompt_cache_retention": "24h",
            "safety_identifier": "test-user-id",
        }

        result = Translation.responses_to_domain_request(request_dict)

        assert isinstance(result, CanonicalChatRequest)
        assert result.extra_body is not None
        assert result.extra_body.get("prompt_cache_key") == "test-cache-key"
        assert result.extra_body.get("prompt_cache_retention") == "24h"
        assert result.extra_body.get("safety_identifier") == "test-user-id"


class TestFilterResponsesExtraBody:
    """Test the _filter_responses_extra_body helper method."""

    def test_filter_allows_metadata(self):
        """Test that metadata is allowed in extra_body."""
        extra_body = {"metadata": {"key": "value"}, "other": "data"}
        result = Translation._filter_responses_extra_body(extra_body)
        assert "metadata" in result
        assert "other" not in result

    def test_filter_allows_responses_api_fields(self):
        """Test that Responses API specific fields are allowed."""
        extra_body = {
            "metadata": {"key": "value"},
            "safety_identifier": "user-123",
            "prompt_cache_key": "cache-key",
            "prompt_cache_retention": "24h",
            "conversation": "conv-123",
            "previous_response_id": "resp-prev",
            "store": True,
            "background": False,
            "truncation": "auto",
            "include": ["reasoning"],
            "reasoning": {"effort": "medium"},
            "text": {"format": {"type": "text"}},
            "service_tier": "default",
            "stream_options": {"include_obfuscation": False},
            # These should be filtered out
            "model": "gpt-4",
            "messages": [],
            "random_field": "value",
        }
        result = Translation._filter_responses_extra_body(extra_body)

        # Allowed fields
        assert result.get("metadata") == {"key": "value"}
        assert result.get("safety_identifier") == "user-123"
        assert result.get("prompt_cache_key") == "cache-key"
        assert result.get("prompt_cache_retention") == "24h"
        assert result.get("conversation") == "conv-123"
        assert result.get("previous_response_id") == "resp-prev"
        assert result.get("store") is True
        assert result.get("background") is False
        assert result.get("truncation") == "auto"
        assert result.get("include") == ["reasoning"]
        assert result.get("reasoning") == {"effort": "medium"}
        assert result.get("text") == {"format": {"type": "text"}}
        assert result.get("service_tier") == "default"
        assert result.get("stream_options") == {"include_obfuscation": False}

        # Filtered out fields
        assert "model" not in result
        assert "messages" not in result
        assert "random_field" not in result

    def test_filter_empty_extra_body(self):
        """Test that empty extra_body returns empty dict."""
        result = Translation._filter_responses_extra_body({})
        assert result == {}

    def test_filter_none_extra_body(self):
        """Test that None extra_body returns empty dict."""
        result = Translation._filter_responses_extra_body(None)
        assert result == {}


class TestResponsesResponseServiceTier:
    """Test service_tier field in Responses API responses."""

    def test_from_domain_to_responses_response_includes_service_tier(self):
        """Test that service_tier is included in Responses API response."""
        response = ChatResponse(
            id="resp-123",
            created=1234567890,
            model="gpt-4o",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content="Hello!",
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            service_tier="default",
            system_fingerprint="fp_abc123",
        )

        result = Translation.from_domain_to_responses_response(response)

        assert result["service_tier"] == "default"
        assert result["system_fingerprint"] == "fp_abc123"

    def test_from_domain_to_responses_response_omits_none_service_tier(self):
        """Test that service_tier is omitted when None."""
        response = ChatResponse(
            id="resp-123",
            created=1234567890,
            model="gpt-4o",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content="Hello!",
                    ),
                    finish_reason="stop",
                )
            ],
            service_tier=None,
        )

        result = Translation.from_domain_to_responses_response(response)

        assert "service_tier" not in result
