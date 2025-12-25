"""
Unit tests for Codebuff Message Router.

These tests verify functionality of message parsing, validation,
routing, and error handling.
"""

import pytest
from src.codebuff.exceptions import CodebuffMessageError
from src.codebuff.message_router import MAX_MESSAGE_SIZE, MessageRouter
from src.codebuff.schemas import (
    PingMessage,
)


class TestMessageRouter:
    """Test suite for MessageRouter."""

    # ========================================================================
    # JSON Parsing Tests
    # ========================================================================

    def test_parse_json_valid_object(self):
        """Test parsing valid JSON object."""
        router = MessageRouter()
        json_str = '{"type": "ping", "txid": 123}'

        result = router.parse_json(json_str)

        assert result == {"type": "ping", "txid": 123}

    def test_parse_json_valid_array(self):
        """Test parsing valid JSON array."""
        router = MessageRouter()
        json_str = "[1, 2, 3]"

        result = router.parse_json(json_str)

        assert result == [1, 2, 3]

    def test_parse_json_valid_nested(self):
        """Test parsing valid nested JSON."""
        router = MessageRouter()
        json_str = '{"data": {"nested": "value"}, "array": [1, 2]}'

        result = router.parse_json(json_str)

        assert result == {"data": {"nested": "value"}, "array": [1, 2]}

    def test_parse_json_invalid_raises_error(self):
        """Test that invalid JSON raises CodebuffMessageError."""
        router = MessageRouter()
        invalid_json = "{invalid json}"

        with pytest.raises(CodebuffMessageError) as exc_info:
            router.parse_json(invalid_json)

        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_json_oversized_message_raises_error(self):
        """Test that oversized JSON raises CodebuffMessageError."""
        router = MessageRouter()

        # Create a message larger than MAX_MESSAGE_SIZE
        large_data = "x" * (MAX_MESSAGE_SIZE + 1000)
        oversized_json = f'{{"type": "ping", "data": "{large_data}"}}'

        with pytest.raises(CodebuffMessageError) as exc_info:
            router.parse_json(oversized_json)

        assert "Message too large" in str(exc_info.value)
        assert "limit" in str(exc_info.value).lower()

        # Check error details
        error_details = (
            exc_info.value.details if hasattr(exc_info.value, "details") else {}
        )
        assert "message_size" in error_details
        assert "size_limit" in error_details

    def test_parse_json_sized_at_limit_works(self):
        """Test that message exactly at size limit works."""
        router = MessageRouter()

        # Create a message exactly at limit
        large_data = "x" * (MAX_MESSAGE_SIZE - 50)  # Leave room for JSON structure
        limit_json = f'{{"type": "ping", "data": "{large_data}"}}'

        # Should not raise an error
        result = router.parse_json(limit_json)

        assert result["type"] == "ping"
        assert result["data"] == large_data

    def test_parse_json_malformed_raises_error(self):
        """Test that malformed JSON raises CodebuffMessageError."""
        router = MessageRouter()
        malformed_json = '{"key": "value"'  # Missing closing brace

        with pytest.raises(CodebuffMessageError) as exc_info:
            router.parse_json(malformed_json)

        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_json_empty_string_raises_error(self):
        """Test that empty string raises CodebuffMessageError."""
        router = MessageRouter()
        empty_json = ""

        with pytest.raises(CodebuffMessageError) as exc_info:
            router.parse_json(empty_json)

        assert "Invalid JSON" in str(exc_info.value)

    # ========================================================================
    # DoS Protection Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_route_message_oversized_json_rejected(self):
        """Test that oversized JSON messages are rejected with proper error."""
        router = MessageRouter()

        # Create oversized message
        large_data = "x" * (MAX_MESSAGE_SIZE + 1000)
        oversized_json = f'{{"type": "ping", "txid": 123, "data": "{large_data}"}}'

        routed = await router.route_message(oversized_json)
        validated_message = routed.validated_message
        ack = routed.ack

        assert validated_message is None
        assert ack.success is False
        assert ack.error is not None
        assert "too large" in ack.error.lower()
        assert "limit" in ack.error.lower()

    @pytest.mark.asyncio
    async def test_route_message_normal_size_works(self):
        """Test that normal-sized messages still work after DoS protection."""
        router = MessageRouter()

        # Create normal-sized message
        normal_json = '{"type": "ping", "txid": 456, "data": "hello world"}'

        routed = await router.route_message(normal_json)
        validated_message = routed.validated_message
        ack = routed.ack

        assert validated_message is not None
        assert isinstance(validated_message, PingMessage)
        assert validated_message.type == "ping"
        assert validated_message.txid == 456
        assert ack.success is True
