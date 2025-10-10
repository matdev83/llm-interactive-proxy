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
