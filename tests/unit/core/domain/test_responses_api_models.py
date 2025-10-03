"""
Unit tests for Responses API domain models.

This module tests the domain models for the OpenAI Responses API,
including validation, serialization/deserialization, and integration
with the TranslationService.
"""

import json
import time

import pytest
from pydantic import ValidationError
from src.core.domain.chat import ChatMessage
from src.core.domain.responses_api import (
    JsonSchema,
    ResponseChoice,
    ResponseFormat,
    ResponseMessage,
    ResponsesRequest,
    ResponsesResponse,
    StreamingResponsesChoice,
    StreamingResponsesResponse,
)


class TestJsonSchema:
    """Test cases for JsonSchema domain model."""

    def test_valid_json_schema_creation(self) -> None:
        """Test creating a valid JsonSchema instance."""
        schema_dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0},
            },
            "required": ["name"],
        }

        json_schema = JsonSchema(
            name="person_schema",
            description="Schema for a person object",
            schema=schema_dict,
            strict=True,
        )

        assert json_schema.name == "person_schema"
        assert json_schema.description == "Schema for a person object"
        assert json_schema.schema == schema_dict
        assert json_schema.strict is True

    def test_json_schema_minimal_creation(self) -> None:
        """Test creating JsonSchema with minimal required fields."""
        schema_dict = {"type": "string"}

        json_schema = JsonSchema(name="simple_string", schema=schema_dict)

        assert json_schema.name == "simple_string"
        assert json_schema.description is None
        assert json_schema.schema == schema_dict
        assert json_schema.strict is True  # Default value

    def test_json_schema_invalid_schema_type(self) -> None:
        """Test that non-dict schema raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            JsonSchema(name="invalid_schema", schema="not a dict")  # type: ignore

        # Pydantic provides its own validation error message for dict type
        assert "Input should be a valid dictionary" in str(exc_info.value)

    def test_json_schema_missing_type_field(self) -> None:
        """Test that schema without 'type' field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            JsonSchema(
                name="no_type_schema",
                schema={"properties": {"name": {"type": "string"}}},
            )

        assert "Schema must have a 'type' field" in str(exc_info.value)

    def test_json_schema_serialization(self) -> None:
        """Test JsonSchema serialization to dict."""
        schema_dict = {"type": "object", "properties": {"id": {"type": "integer"}}}
        json_schema = JsonSchema(
            name="test_schema", description="Test description", schema=schema_dict
        )

        serialized = json_schema.model_dump()

        assert serialized["name"] == "test_schema"
        assert serialized["description"] == "Test description"
        assert serialized["schema"] == schema_dict
        assert serialized["strict"] is True

    def test_json_schema_deserialization(self) -> None:
        """Test JsonSchema deserialization from dict."""
        data = {
            "name": "test_schema",
            "description": "Test description",
            "schema": {"type": "boolean"},
            "strict": False,
        }

        json_schema = JsonSchema(**data)

        assert json_schema.name == "test_schema"
        assert json_schema.description == "Test description"
        assert json_schema.schema == {"type": "boolean"}
        assert json_schema.strict is False


class TestResponseFormat:
    """Test cases for ResponseFormat domain model."""

    def test_valid_response_format_creation(self) -> None:
        """Test creating a valid ResponseFormat instance."""
        json_schema = JsonSchema(name="test_schema", schema={"type": "string"})

        response_format = ResponseFormat(type="json_schema", json_schema=json_schema)

        assert response_format.type == "json_schema"
        assert response_format.json_schema == json_schema

    def test_response_format_default_type(self) -> None:
        """Test ResponseFormat with default type."""
        json_schema = JsonSchema(name="test_schema", schema={"type": "number"})

        response_format = ResponseFormat(json_schema=json_schema)

        assert response_format.type == "json_schema"  # Default value

    def test_response_format_invalid_type(self) -> None:
        """Test that invalid response format type raises ValidationError."""
        json_schema = JsonSchema(name="test_schema", schema={"type": "string"})

        with pytest.raises(ValidationError) as exc_info:
            ResponseFormat(type="invalid_type", json_schema=json_schema)

        assert "Only 'json_schema' response format type is currently supported" in str(
            exc_info.value
        )

    def test_response_format_serialization(self) -> None:
        """Test ResponseFormat serialization."""
        json_schema = JsonSchema(
            name="test_schema", schema={"type": "array", "items": {"type": "string"}}
        )
        response_format = ResponseFormat(json_schema=json_schema)

        serialized = response_format.model_dump()

        assert serialized["type"] == "json_schema"
        assert "json_schema" in serialized
        assert serialized["json_schema"]["name"] == "test_schema"


class TestResponsesRequest:
    """Test cases for ResponsesRequest domain model."""

    def test_valid_responses_request_creation(self) -> None:
        """Test creating a valid ResponsesRequest instance."""
        messages = [ChatMessage(role="user", content="Generate a person object")]
        json_schema = JsonSchema(
            name="person",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        response_format = ResponseFormat(json_schema=json_schema)

        request = ResponsesRequest(
            model="gpt-4",
            messages=messages,
            response_format=response_format,
            max_tokens=100,
            temperature=0.7,
        )

        assert request.model == "gpt-4"
        assert len(request.messages) == 1
        assert request.messages[0].role == "user"
        assert request.response_format == response_format
        assert request.max_tokens == 100
        assert request.temperature == 0.7

    def test_responses_request_minimal_creation(self) -> None:
        """Test creating ResponsesRequest with minimal required fields."""
        messages = [ChatMessage(role="user", content="Test")]
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        request = ResponsesRequest(
            model="gpt-3.5-turbo", messages=messages, response_format=response_format
        )

        assert request.model == "gpt-3.5-turbo"
        assert len(request.messages) == 1
        assert request.max_tokens is None
        assert request.temperature is None

    def test_responses_request_empty_messages_validation(self) -> None:
        """Test that empty messages list raises ValidationError."""
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        with pytest.raises(ValidationError) as exc_info:
            ResponsesRequest(
                model="gpt-4", messages=[], response_format=response_format
            )

        assert "At least one message is required" in str(exc_info.value)

    def test_responses_request_invalid_temperature(self) -> None:
        """Test that invalid temperature raises ValidationError."""
        messages = [ChatMessage(role="user", content="Test")]
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        with pytest.raises(ValidationError):
            ResponsesRequest(
                model="gpt-4",
                messages=messages,
                response_format=response_format,
                temperature=3.0,  # Invalid: > 2.0
            )

    def test_responses_request_invalid_n_value(self) -> None:
        """Test that invalid n value raises ValidationError."""
        messages = [ChatMessage(role="user", content="Test")]
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        with pytest.raises(ValidationError) as exc_info:
            ResponsesRequest(
                model="gpt-4",
                messages=messages,
                response_format=response_format,
                n=0,  # Invalid: must be >= 1
            )

        # Pydantic provides its own validation error message for ge constraint
        assert "Input should be greater than or equal to 1" in str(exc_info.value)

    def test_responses_request_message_conversion(self) -> None:
        """Test that dict messages are converted to ChatMessage objects."""
        message_dict = {"role": "user", "content": "Test message"}
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        request = ResponsesRequest(
            model="gpt-4",
            messages=[message_dict],  # type: ignore
            response_format=response_format,
        )

        assert len(request.messages) == 1
        assert isinstance(request.messages[0], ChatMessage)
        assert request.messages[0].role == "user"
        assert request.messages[0].content == "Test message"

    def test_responses_request_serialization(self) -> None:
        """Test ResponsesRequest serialization."""
        messages = [ChatMessage(role="user", content="Test")]
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        request = ResponsesRequest(
            model="gpt-4",
            messages=messages,
            response_format=response_format,
            temperature=0.5,
            max_tokens=50,
        )

        serialized = request.model_dump()

        assert serialized["model"] == "gpt-4"
        assert len(serialized["messages"]) == 1
        assert serialized["temperature"] == 0.5
        assert serialized["max_tokens"] == 50
        assert "response_format" in serialized


class TestResponseMessage:
    """Test cases for ResponseMessage domain model."""

    def test_valid_response_message_creation(self) -> None:
        """Test creating a valid ResponseMessage instance."""
        parsed_data = {"name": "John", "age": 30}

        message = ResponseMessage(
            role="assistant", content='{"name": "John", "age": 30}', parsed=parsed_data
        )

        assert message.role == "assistant"
        assert message.content == '{"name": "John", "age": 30}'
        assert message.parsed == parsed_data

    def test_response_message_default_role(self) -> None:
        """Test ResponseMessage with default role."""
        message = ResponseMessage(content="Test response")

        assert message.role == "assistant"  # Default value
        assert message.content == "Test response"
        assert message.parsed is None

    def test_response_message_invalid_role(self) -> None:
        """Test that invalid role raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ResponseMessage(role="user", content="Test")  # Invalid: must be "assistant"

        assert "Response message role must be 'assistant'" in str(exc_info.value)

    def test_response_message_serialization(self) -> None:
        """Test ResponseMessage serialization."""
        parsed_data = {"result": "success"}
        message = ResponseMessage(content="Success message", parsed=parsed_data)

        serialized = message.model_dump()

        assert serialized["role"] == "assistant"
        assert serialized["content"] == "Success message"
        assert serialized["parsed"] == parsed_data


class TestResponseChoice:
    """Test cases for ResponseChoice domain model."""

    def test_valid_response_choice_creation(self) -> None:
        """Test creating a valid ResponseChoice instance."""
        message = ResponseMessage(content="Test response")

        choice = ResponseChoice(index=0, message=message, finish_reason="stop")

        assert choice.index == 0
        assert choice.message == message
        assert choice.finish_reason == "stop"

    def test_response_choice_negative_index(self) -> None:
        """Test that negative index raises ValidationError."""
        message = ResponseMessage(content="Test")

        with pytest.raises(ValidationError) as exc_info:
            ResponseChoice(
                index=-1,  # Invalid: must be non-negative
                message=message,
                finish_reason="stop",
            )

        assert "Choice index must be non-negative" in str(exc_info.value)

    def test_response_choice_valid_finish_reasons(self) -> None:
        """Test that valid finish reasons are accepted."""
        message = ResponseMessage(content="Test")
        valid_reasons = [
            "stop",
            "length",
            "content_filter",
            "tool_calls",
            "function_call",
        ]

        for reason in valid_reasons:
            choice = ResponseChoice(index=0, message=message, finish_reason=reason)
            assert choice.finish_reason == reason

    def test_response_choice_custom_finish_reason(self) -> None:
        """Test that custom finish reasons are allowed for backend flexibility."""
        message = ResponseMessage(content="Test")

        # Should not raise an error for custom finish reasons
        choice = ResponseChoice(index=0, message=message, finish_reason="custom_reason")

        assert choice.finish_reason == "custom_reason"

    def test_response_choice_serialization(self) -> None:
        """Test ResponseChoice serialization."""
        message = ResponseMessage(content="Test response")
        choice = ResponseChoice(index=1, message=message, finish_reason="length")

        serialized = choice.model_dump()

        assert serialized["index"] == 1
        assert serialized["finish_reason"] == "length"
        assert "message" in serialized


class TestResponsesResponse:
    """Test cases for ResponsesResponse domain model."""

    def test_valid_responses_response_creation(self) -> None:
        """Test creating a valid ResponsesResponse instance."""
        message = ResponseMessage(content="Test response")
        choice = ResponseChoice(index=0, message=message, finish_reason="stop")
        current_time = int(time.time())

        response = ResponsesResponse(
            id="resp_123",
            created=current_time,
            model="gpt-4",
            choices=[choice],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

        assert response.id == "resp_123"
        assert response.object == "response"  # Default value
        assert response.created == current_time
        assert response.model == "gpt-4"
        assert len(response.choices) == 1
        assert response.usage is not None

    def test_responses_response_minimal_creation(self) -> None:
        """Test creating ResponsesResponse with minimal required fields."""
        message = ResponseMessage(content="Test")
        choice = ResponseChoice(index=0, message=message, finish_reason="stop")

        response = ResponsesResponse(
            id="resp_456", created=1234567890, model="gpt-3.5-turbo", choices=[choice]
        )

        assert response.id == "resp_456"
        assert response.object == "response"
        assert response.usage is None
        assert response.system_fingerprint is None

    def test_responses_response_invalid_object_type(self) -> None:
        """Test that invalid object type raises ValidationError."""
        message = ResponseMessage(content="Test")
        choice = ResponseChoice(index=0, message=message, finish_reason="stop")

        with pytest.raises(ValidationError) as exc_info:
            ResponsesResponse(
                id="resp_789",
                object="invalid_object",  # Invalid: must be "response"
                created=1234567890,
                model="gpt-4",
                choices=[choice],
            )

        assert "Object type must be 'response'" in str(exc_info.value)

    def test_responses_response_empty_choices(self) -> None:
        """Test that empty choices list raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ResponsesResponse(
                id="resp_empty",
                created=1234567890,
                model="gpt-4",
                choices=[],  # Invalid: must have at least one choice
            )

        assert "At least one choice is required" in str(exc_info.value)

    def test_responses_response_invalid_created_timestamp(self) -> None:
        """Test that invalid created timestamp raises ValidationError."""
        message = ResponseMessage(content="Test")
        choice = ResponseChoice(index=0, message=message, finish_reason="stop")

        with pytest.raises(ValidationError) as exc_info:
            ResponsesResponse(
                id="resp_invalid_time",
                created=0,  # Invalid: must be positive
                model="gpt-4",
                choices=[choice],
            )

        assert "Created timestamp must be positive" in str(exc_info.value)

    def test_responses_response_choice_conversion(self) -> None:
        """Test that dict choices are converted to ResponseChoice objects."""
        choice_dict = {
            "index": 0,
            "message": {"content": "Test response"},
            "finish_reason": "stop",
        }

        response = ResponsesResponse(
            id="resp_convert",
            created=1234567890,
            model="gpt-4",
            choices=[choice_dict],  # type: ignore
        )

        assert len(response.choices) == 1
        assert isinstance(response.choices[0], ResponseChoice)
        assert response.choices[0].index == 0
        assert response.choices[0].finish_reason == "stop"

    def test_responses_response_serialization(self) -> None:
        """Test ResponsesResponse serialization."""
        message = ResponseMessage(content="Test response")
        choice = ResponseChoice(index=0, message=message, finish_reason="stop")

        response = ResponsesResponse(
            id="resp_serialize",
            created=1234567890,
            model="gpt-4",
            choices=[choice],
            usage={"total_tokens": 20},
        )

        serialized = response.model_dump()

        assert serialized["id"] == "resp_serialize"
        assert serialized["object"] == "response"
        assert serialized["created"] == 1234567890
        assert serialized["model"] == "gpt-4"
        assert len(serialized["choices"]) == 1
        assert serialized["usage"] == {"total_tokens": 20}


class TestStreamingModels:
    """Test cases for streaming response models."""

    def test_streaming_responses_choice_creation(self) -> None:
        """Test creating a StreamingResponsesChoice instance."""
        choice = StreamingResponsesChoice(
            index=0, delta={"content": "Hello"}, finish_reason=None
        )

        assert choice.index == 0
        assert choice.delta == {"content": "Hello"}
        assert choice.finish_reason is None

    def test_streaming_responses_response_creation(self) -> None:
        """Test creating a StreamingResponsesResponse instance."""
        choice = StreamingResponsesChoice(
            index=0, delta={"content": "Hello"}, finish_reason=None
        )

        response = StreamingResponsesResponse(
            id="resp_stream_123", created=1234567890, model="gpt-4", choices=[choice]
        )

        assert response.id == "resp_stream_123"
        assert response.object == "response.chunk"  # Default for streaming
        assert response.created == 1234567890
        assert response.model == "gpt-4"
        assert len(response.choices) == 1

    def test_streaming_responses_response_invalid_object(self) -> None:
        """Test that invalid streaming object type raises ValidationError."""
        choice = StreamingResponsesChoice(index=0, delta={})

        with pytest.raises(ValidationError) as exc_info:
            StreamingResponsesResponse(
                id="resp_stream_invalid",
                object="response",  # Invalid: must be "response.chunk"
                created=1234567890,
                model="gpt-4",
                choices=[choice],
            )

        assert "Streaming object type must be 'response.chunk'" in str(exc_info.value)


class TestModelIntegration:
    """Test cases for model integration and complex scenarios."""

    def test_complete_request_response_cycle(self) -> None:
        """Test a complete request-response cycle with all models."""
        # Create a complete request
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(
                role="user", content="Generate a person object with name and age."
            ),
        ]

        json_schema = JsonSchema(
            name="person",
            description="A person with name and age",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer", "minimum": 0},
                },
                "required": ["name", "age"],
            },
        )

        response_format = ResponseFormat(json_schema=json_schema)

        request = ResponsesRequest(
            model="gpt-4",
            messages=messages,
            response_format=response_format,
            temperature=0.7,
            max_tokens=100,
        )

        # Create a corresponding response
        parsed_data = {"name": "Alice", "age": 25}
        response_message = ResponseMessage(
            content='{"name": "Alice", "age": 25}', parsed=parsed_data
        )

        choice = ResponseChoice(index=0, message=response_message, finish_reason="stop")

        response = ResponsesResponse(
            id="resp_complete_cycle",
            created=int(time.time()),
            model="gpt-4",
            choices=[choice],
            usage={"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35},
        )

        # Verify the complete cycle
        assert request.model == response.model
        assert len(request.messages) == 2
        assert request.response_format.json_schema.name == "person"
        assert response.choices[0].message.parsed == parsed_data
        assert json.loads(response.choices[0].message.content) == parsed_data

    def test_model_serialization_deserialization_roundtrip(self) -> None:
        """Test that models can be serialized and deserialized without data loss."""
        # Create original models
        json_schema = JsonSchema(
            name="test_schema",
            description="Test schema for roundtrip",
            schema={"type": "object", "properties": {"id": {"type": "string"}}},
            strict=False,
        )

        response_format = ResponseFormat(json_schema=json_schema)

        messages = [ChatMessage(role="user", content="Test message")]

        original_request = ResponsesRequest(
            model="gpt-4",
            messages=messages,
            response_format=response_format,
            temperature=0.8,
            max_tokens=150,
            n=2,
        )

        # Serialize to dict
        serialized = original_request.model_dump()

        # Deserialize back to model
        deserialized_request = ResponsesRequest(**serialized)

        # Verify data integrity
        assert deserialized_request.model == original_request.model
        assert len(deserialized_request.messages) == len(original_request.messages)
        assert (
            deserialized_request.messages[0].content
            == original_request.messages[0].content
        )
        assert (
            deserialized_request.response_format.json_schema.name
            == original_request.response_format.json_schema.name
        )
        assert deserialized_request.temperature == original_request.temperature
        assert deserialized_request.max_tokens == original_request.max_tokens
        assert deserialized_request.n == original_request.n

    def test_model_validation_edge_cases(self) -> None:
        """Test edge cases in model validation."""
        # Test with complex nested schema
        complex_schema = {
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "profile": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "settings": {
                                        "type": "object",
                                        "additionalProperties": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                }
            },
        }

        json_schema = JsonSchema(name="complex_nested", schema=complex_schema)

        # Should not raise validation errors
        response_format = ResponseFormat(json_schema=json_schema)
        assert response_format.json_schema.schema == complex_schema

    def test_model_immutability(self) -> None:
        """Test that ValueObject models are immutable."""
        messages = [ChatMessage(role="user", content="Test")]
        json_schema = JsonSchema(name="test", schema={"type": "string"})
        response_format = ResponseFormat(json_schema=json_schema)

        request = ResponsesRequest(
            model="gpt-4", messages=messages, response_format=response_format
        )

        # Attempt to modify should raise an error (frozen model)
        with pytest.raises(ValidationError):
            request.model = "gpt-3.5-turbo"  # type: ignore

        # Create response and test immutability
        message = ResponseMessage(content="Test response")
        choice = ResponseChoice(index=0, message=message, finish_reason="stop")
        response = ResponsesResponse(
            id="resp_immutable", created=1234567890, model="gpt-4", choices=[choice]
        )

        with pytest.raises(ValidationError):
            response.model = "different-model"  # type: ignore


if __name__ == "__main__":
    pytest.main([__file__])
