"""Unit tests for TranslationService Responses API extensions.

This module tests the Responses API specific methods in the TranslationService,
including request/response translation, schema validation, and structured output
parsing and repair functionality.
"""

import json
import time
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
)
from src.core.domain.responses_api import (
    JsonSchema,
    ResponseFormat,
    ResponsesRequest,
)
from src.core.services.translation_service import TranslationService


class TestResponsesApiTranslation:
    """Test class for Responses API translation methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = TranslationService()

        # Sample JSON schema for testing
        self.sample_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string"},
            },
            "required": ["name", "age"],
        }

        # Sample Responses API request
        self.sample_responses_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person profile"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person_profile",
                    "description": "A person's profile information",
                    "schema": self.sample_schema,
                    "strict": True,
                },
            },
            "max_tokens": 100,
            "temperature": 0.7,
        }

    def test_responses_to_domain_request_dict_input(self):
        """Test converting a Responses API request dict to CanonicalChatRequest."""
        domain_request = self.service.to_domain_request(
            self.sample_responses_request, "responses"
        )

        assert isinstance(domain_request, CanonicalChatRequest)
        assert domain_request.model == "gpt-4"
        assert len(domain_request.messages) == 1
        assert domain_request.messages[0].content == "Generate a person profile"
        assert domain_request.max_tokens == 100
        assert domain_request.temperature == 0.7

        # Check that response_format is preserved in extra_body
        assert domain_request.extra_body is not None
        assert "response_format" in domain_request.extra_body
        response_format = domain_request.extra_body["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "person_profile"

    def test_responses_to_domain_request_pydantic_input(self):
        """Test converting a ResponsesRequest Pydantic model to CanonicalChatRequest."""
        json_schema = JsonSchema(
            name="person_profile",
            description="A person's profile information",
            schema=self.sample_schema,
            strict=True,
        )
        response_format = ResponseFormat(type="json_schema", json_schema=json_schema)
        responses_request = ResponsesRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Generate a person profile")],
            response_format=response_format,
            max_tokens=100,
            temperature=0.7,
        )

        domain_request = self.service.to_domain_request(responses_request, "responses")

        assert isinstance(domain_request, CanonicalChatRequest)
        assert domain_request.model == "gpt-4"
        assert len(domain_request.messages) == 1
        assert domain_request.messages[0].content == "Generate a person profile"
        assert domain_request.max_tokens == 100
        assert domain_request.temperature == 0.7

        # Check that response_format is preserved in extra_body
        assert domain_request.extra_body is not None
        assert "response_format" in domain_request.extra_body

    def test_responses_to_domain_request_object_input(self):
        """Test converting an object with attributes to CanonicalChatRequest."""

        class MockRequest:
            def __init__(self):
                self.model = "gpt-4"
                self.messages = [{"role": "user", "content": "Test"}]
                self.response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "test_schema",
                        "schema": {"type": "object"},
                    },
                }
                self.max_tokens = 50
                self.temperature = None
                self.top_p = None
                self.n = None
                self.stream = None
                self.stop = None
                self.presence_penalty = None
                self.frequency_penalty = None
                self.logit_bias = None
                self.user = None
                self.seed = None
                self.session_id = None
                self.agent = None
                self.extra_body = None

        mock_request = MockRequest()
        domain_request = self.service.to_domain_request(mock_request, "responses")

        assert isinstance(domain_request, CanonicalChatRequest)
        assert domain_request.model == "gpt-4"
        assert len(domain_request.messages) == 1

    def test_to_domain_stream_chunk_responses_sse_input(self):
        """Test translating SSE-formatted Responses API streaming chunks."""

        sse_chunk = (
            'data: {"id": "resp-123", "object": "response.chunk", '
            '"choices": [{"delta": {"content": "partial"}}]}\n\n'
        )

        domain_chunk = self.service.to_domain_stream_chunk(
            sse_chunk, "openai-responses"
        )

        assert isinstance(domain_chunk, dict)
        assert domain_chunk["choices"][0]["delta"]["content"] == "partial"

    def test_to_domain_stream_chunk_responses_done_marker(self):
        """Test translating the [DONE] marker from Responses API streaming."""

        done_chunk = "data: [DONE]\n\n"

        domain_chunk = self.service.to_domain_stream_chunk(
            done_chunk, "openai-responses"
        )

        assert isinstance(domain_chunk, dict)
        assert domain_chunk["choices"][0]["finish_reason"] == "stop"
        assert domain_chunk["choices"][0]["delta"] == {}

    def test_from_domain_to_responses_response_basic(self):
        """Test converting a ChatResponse to Responses API response format."""
        # Create a sample ChatResponse
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant",
                content='{"name": "John Doe", "age": 30, "email": "john@example.com"}',
            ),
            finish_reason="stop",
        )

        chat_response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        responses_response = self.service.from_domain_to_responses_response(
            chat_response
        )

        assert responses_response["id"] == "resp-123"
        assert responses_response["object"] == "response"
        assert responses_response["model"] == "gpt-4"
        assert len(responses_response["choices"]) == 1

        choice_data = responses_response["choices"][0]
        assert choice_data["index"] == 0
        assert choice_data["message"]["role"] == "assistant"
        assert (
            choice_data["message"]["content"]
            == '{"name": "John Doe", "age": 30, "email": "john@example.com"}'
        )
        assert choice_data["message"]["parsed"] == {
            "name": "John Doe",
            "age": 30,
            "email": "john@example.com",
        }
        assert choice_data["finish_reason"] == "stop"

        assert responses_response["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }

    def test_from_domain_to_responses_response_with_markdown_json(self):
        """Test converting a response with JSON wrapped in markdown code blocks."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant",
                content='```json\n{"name": "Jane Doe", "age": 25}\n```',
            ),
            finish_reason="stop",
        )

        chat_response = CanonicalChatResponse(
            id="resp-456",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        responses_response = self.service.from_domain_to_responses_response(
            chat_response
        )

        choice_data = responses_response["choices"][0]
        assert choice_data["message"]["content"] == '{"name": "Jane Doe", "age": 25}'
        assert choice_data["message"]["parsed"] == {"name": "Jane Doe", "age": 25}

    def test_from_domain_to_responses_response_invalid_json(self):
        """Test converting a response with invalid JSON content."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content="This is not valid JSON content"
            ),
            finish_reason="stop",
        )

        chat_response = CanonicalChatResponse(
            id="resp-789",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        responses_response = self.service.from_domain_to_responses_response(
            chat_response
        )

        choice_data = responses_response["choices"][0]
        assert choice_data["message"]["content"] == "This is not valid JSON content"
        assert choice_data["message"]["parsed"] is None

    def test_from_domain_to_responses_response_json_in_text(self):
        """Test extracting JSON from mixed text content."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant",
                content='Here is the result: {"name": "Bob", "age": 35} - that\'s the answer.',
            ),
            finish_reason="stop",
        )

        chat_response = CanonicalChatResponse(
            id="resp-101",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        responses_response = self.service.from_domain_to_responses_response(
            chat_response
        )

        choice_data = responses_response["choices"][0]
        assert choice_data["message"]["content"] == '{"name": "Bob", "age": 35}'
        assert choice_data["message"]["parsed"] == {"name": "Bob", "age": 35}

    def test_from_domain_to_responses_request_basic(self):
        """Test converting a CanonicalChatRequest to Responses API request format."""
        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "test_schema", "schema": self.sample_schema},
            }
        }

        canonical_request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Test message")],
            max_tokens=100,
            temperature=0.5,
            extra_body=extra_body,
        )

        responses_request = self.service.from_domain_to_responses_request(
            canonical_request
        )

        assert responses_request["model"] == "gpt-4"
        assert len(responses_request["messages"]) == 1
        assert responses_request["messages"][0]["content"] == "Test message"
        assert responses_request["max_tokens"] == 100
        assert responses_request["temperature"] == 0.5

        # Check response_format is properly extracted
        assert "response_format" in responses_request
        assert responses_request["response_format"]["type"] == "json_schema"
        assert (
            responses_request["response_format"]["json_schema"]["name"] == "test_schema"
        )

    def test_from_domain_to_responses_request_no_response_format(self):
        """Test converting a request without response_format."""
        canonical_request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Test message")],
            max_tokens=100,
        )

        responses_request = self.service.from_domain_to_responses_request(
            canonical_request
        )

        assert responses_request["model"] == "gpt-4"
        assert "response_format" not in responses_request

    def test_validate_json_against_schema_valid(self):
        """Test JSON schema validation with valid data."""
        json_data = {"name": "John", "age": 30, "email": "john@example.com"}

        is_valid, error_msg = self.service.validate_json_against_schema(
            json_data, self.sample_schema
        )

        assert is_valid is True
        assert error_msg is None

    def test_validate_json_against_schema_missing_required(self):
        """Test JSON schema validation with missing required field."""
        json_data = {"name": "John"}  # Missing required 'age' field

        is_valid, error_msg = self.service.validate_json_against_schema(
            json_data, self.sample_schema
        )

        assert is_valid is False
        assert error_msg is not None
        assert "age" in error_msg or "required" in error_msg.lower()

    def test_validate_json_against_schema_wrong_type(self):
        """Test JSON schema validation with wrong data type."""
        json_data = {"name": "John", "age": "thirty"}  # age should be integer

        is_valid, error_msg = self.service.validate_json_against_schema(
            json_data, self.sample_schema
        )

        assert is_valid is False
        assert error_msg is not None

    def test_validate_json_against_schema_fallback_valid(self):
        """Test basic schema validation fallback when jsonschema is not available."""
        json_data = {"name": "John", "age": 30}

        # Mock the import to simulate jsonschema not being available
        def mock_import(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("No module named 'jsonschema'")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            is_valid, error_msg = self.service.validate_json_against_schema(
                json_data, self.sample_schema
            )

        assert is_valid is True
        assert error_msg is None

    def test_validate_json_against_schema_fallback_missing_required(self):
        """Test basic schema validation fallback with missing required field."""
        json_data = {"name": "John"}  # Missing required 'age' field

        # Mock the import to simulate jsonschema not being available
        def mock_import(name, *args, **kwargs):
            if name == "jsonschema":
                raise ImportError("No module named 'jsonschema'")
            return __import__(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            is_valid, error_msg = self.service.validate_json_against_schema(
                json_data, self.sample_schema
            )

        assert is_valid is False
        assert "age" in error_msg

    def test_enhance_structured_output_response_valid_json(self):
        """Test enhancing a response with valid structured output."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content='{"name": "John", "age": 30}'
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        original_request_extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "person", "schema": self.sample_schema},
            }
        }

        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        # Should return the same response since JSON is valid
        assert enhanced_response.id == response.id
        assert (
            enhanced_response.choices[0].message.content
            == '{"name": "John", "age": 30}'
        )

    def test_enhance_structured_output_response_invalid_json_repairable(self):
        """Test enhancing a response with invalid but repairable JSON."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant",
                content='{"name": "John"}',  # Missing required 'age' field
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        original_request_extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "person", "schema": self.sample_schema},
            }
        }

        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        # Should have repaired JSON with default age value
        enhanced_content = enhanced_response.choices[0].message.content
        parsed_content = json.loads(enhanced_content)
        assert "name" in parsed_content
        assert "age" in parsed_content
        assert parsed_content["age"] == 0  # Default integer value

    def test_enhance_structured_output_response_malformed_json(self):
        """Test enhancing a response with malformed JSON that can be extracted."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant",
                content='Here is the data: {"name": "John"} - hope this helps!',
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        original_request_extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "person", "schema": self.sample_schema},
            }
        }

        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        # Should have extracted and repaired JSON
        enhanced_content = enhanced_response.choices[0].message.content
        parsed_content = json.loads(enhanced_content)
        assert "name" in parsed_content
        assert "age" in parsed_content

    def test_enhance_structured_output_response_no_schema(self):
        """Test enhancing a response when no schema is provided."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content="Regular text response"
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        # No extra_body provided
        enhanced_response = self.service.enhance_structured_output_response(
            response, None
        )

        # Should return the same response unchanged
        assert enhanced_response.id == response.id
        assert enhanced_response.choices[0].message.content == "Regular text response"

    def test_enhance_structured_output_response_non_json_schema_format(self):
        """Test enhancing a response with non-json_schema response format."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content="Regular text response"
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        original_request_extra_body = {
            "response_format": {"type": "text"}  # Not json_schema
        }

        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        # Should return the same response unchanged
        assert enhanced_response.id == response.id
        assert enhanced_response.choices[0].message.content == "Regular text response"

    def test_enhance_structured_output_response_unrepairable_json(self):
        """Test enhancing a response with completely unrepairable content."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant",
                content="This is completely non-JSON text with no extractable data",
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        original_request_extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "person", "schema": self.sample_schema},
            }
        }

        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        # Should return the original response unchanged since repair failed
        assert enhanced_response.id == response.id
        assert (
            enhanced_response.choices[0].message.content
            == "This is completely non-JSON text with no extractable data"
        )


class TestResponsesApiErrorHandling:
    """Test class for error handling in Responses API translation methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = TranslationService()

    def test_responses_to_domain_request_invalid_input(self):
        """Test error handling for invalid Responses API request input."""
        with pytest.raises(ValidationError):  # Should raise validation error
            self.service.to_domain_request({}, "responses")

    def test_responses_to_domain_request_missing_model(self):
        """Test error handling for missing model in request."""
        invalid_request = {
            "messages": [{"role": "user", "content": "Test"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "test", "schema": {"type": "object"}},
            },
        }

        with pytest.raises(
            ValidationError
        ):  # Should raise validation error for missing model
            self.service.to_domain_request(invalid_request, "responses")

    def test_responses_to_domain_request_missing_response_format(self):
        """Test error handling for missing response_format in request."""
        invalid_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Test"}],
        }

        with pytest.raises(
            ValidationError
        ):  # Should raise validation error for missing response_format
            self.service.to_domain_request(invalid_request, "responses")

    def test_validate_json_against_schema_exception_handling(self):
        """Test error handling in schema validation when exceptions occur."""
        # Test with invalid schema that might cause exceptions
        invalid_schema = {"type": "invalid_type"}
        json_data = {"test": "data"}

        is_valid, error_msg = self.service.validate_json_against_schema(
            json_data, invalid_schema
        )

        # Should handle the exception gracefully
        assert is_valid is False
        assert error_msg is not None

    def test_enhance_structured_output_response_exception_handling(self):
        """Test error handling in response enhancement when exceptions occur."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content='{"invalid": json}'  # Malformed JSON
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        # Malformed schema that might cause exceptions
        original_request_extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "test", "schema": None},  # Invalid schema
            }
        }

        # Should handle exceptions gracefully and return original response
        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        assert enhanced_response.id == response.id


class TestResponsesApiIntegration:
    """Integration tests for Responses API translation methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.service = TranslationService()

    def test_full_request_response_cycle(self):
        """Test a complete request-response translation cycle."""
        # Start with a Responses API request
        responses_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person profile"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person_profile",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                        "required": ["name", "age"],
                    },
                },
            },
        }

        # Convert to domain request
        domain_request = self.service.to_domain_request(responses_request, "responses")
        assert isinstance(domain_request, CanonicalChatRequest)

        # Convert back to Responses API request
        converted_request = self.service.from_domain_to_responses_request(
            domain_request
        )
        assert converted_request["model"] == "gpt-4"
        assert "response_format" in converted_request

        # Create a mock response
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content='{"name": "John Doe", "age": 30}'
            ),
            finish_reason="stop",
        )

        domain_response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        # Convert to Responses API response
        responses_response = self.service.from_domain_to_responses_response(
            domain_response
        )
        assert responses_response["object"] == "response"
        assert responses_response["choices"][0]["message"]["parsed"] == {
            "name": "John Doe",
            "age": 30,
        }

    def test_structured_output_enhancement_integration(self):
        """Test integration of structured output enhancement with translation."""
        # Create a response with invalid JSON that needs repair
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(
                role="assistant", content='{"name": "John"}'  # Missing required age
            ),
            finish_reason="stop",
        )

        response = CanonicalChatResponse(
            id="resp-123",
            object="chat.completion",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
        )

        original_request_extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                        "required": ["name", "age"],
                    },
                },
            }
        }

        # Enhance the response
        enhanced_response = self.service.enhance_structured_output_response(
            response, original_request_extra_body
        )

        # Convert to Responses API format
        responses_response = self.service.from_domain_to_responses_response(
            enhanced_response
        )

        # Should have valid parsed JSON with repaired data
        parsed = responses_response["choices"][0]["message"]["parsed"]
        assert "name" in parsed
        assert "age" in parsed
        assert isinstance(parsed["age"], int)
