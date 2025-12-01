"""
Unit tests for Codebuff Message Router.

These tests verify the functionality of message parsing, validation,
routing, and error handling.
"""

import json

import pytest

from src.codebuff.exceptions import CodebuffMessageError, CodebuffValidationError
from src.codebuff.message_router import MessageRouter
from src.codebuff.schemas import (
    ActionMessage,
    IdentifyMessage,
    InitAction,
    PingMessage,
    PromptAction,
    SubscribeMessage,
    UnsubscribeMessage,
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
        json_str = '[1, 2, 3]'

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
    # Message Validation Tests
    # ========================================================================

    def test_validate_identify_message(self):
        """Test validating identify message."""
        router = MessageRouter()
        message_data = {
            "type": "identify",
            "txid": 123,
            "clientSessionId": "session-123",
        }

        result = router.validate_message(message_data)

        assert isinstance(result, IdentifyMessage)
        assert result.type == "identify"
        assert result.txid == 123
        assert result.clientSessionId == "session-123"

    def test_validate_ping_message(self):
        """Test validating ping message."""
        router = MessageRouter()
        message_data = {"type": "ping", "txid": 456}

        result = router.validate_message(message_data)

        assert isinstance(result, PingMessage)
        assert result.type == "ping"
        assert result.txid == 456

    def test_validate_subscribe_message(self):
        """Test validating subscribe message."""
        router = MessageRouter()
        message_data = {
            "type": "subscribe",
            "txid": 789,
            "topics": ["topic1", "topic2"],
        }

        result = router.validate_message(message_data)

        assert isinstance(result, SubscribeMessage)
        assert result.type == "subscribe"
        assert result.txid == 789
        assert result.topics == ["topic1", "topic2"]

    def test_validate_unsubscribe_message(self):
        """Test validating unsubscribe message."""
        router = MessageRouter()
        message_data = {
            "type": "unsubscribe",
            "txid": 101,
            "topics": ["topic3"],
        }

        result = router.validate_message(message_data)

        assert isinstance(result, UnsubscribeMessage)
        assert result.type == "unsubscribe"
        assert result.txid == 101
        assert result.topics == ["topic3"]

    def test_validate_action_message_with_prompt(self):
        """Test validating action message with prompt action."""
        router = MessageRouter()
        message_data = {
            "type": "action",
            "txid": 202,
            "data": {
                "type": "prompt",
                "promptId": "prompt-123",
                "fingerprintId": "fingerprint-456",
                "sessionState": {},
                "toolResults": [],
            },
        }

        result = router.validate_message(message_data)

        assert isinstance(result, ActionMessage)
        assert result.type == "action"
        assert result.txid == 202
        assert isinstance(result.data, PromptAction)
        assert result.data.type == "prompt"
        assert result.data.promptId == "prompt-123"

    def test_validate_action_message_with_init(self):
        """Test validating action message with init action."""
        router = MessageRouter()
        message_data = {
            "type": "action",
            "txid": 303,
            "data": {
                "type": "init",
                "fingerprintId": "fingerprint-789",
                "fileContext": {"file1": "content1"},
            },
        }

        result = router.validate_message(message_data)

        assert isinstance(result, ActionMessage)
        assert result.type == "action"
        assert result.txid == 303
        assert isinstance(result.data, InitAction)
        assert result.data.type == "init"
        assert result.data.fingerprintId == "fingerprint-789"

    def test_validate_message_missing_type_raises_error(self):
        """Test that message missing type field raises error."""
        router = MessageRouter()
        message_data = {"txid": 123}

        with pytest.raises(CodebuffValidationError) as exc_info:
            router.validate_message(message_data)

        assert "missing 'type' field" in str(exc_info.value).lower()

    def test_validate_message_unknown_type_raises_error(self):
        """Test that message with unknown type raises error."""
        router = MessageRouter()
        message_data = {"type": "unknown", "txid": 123}

        with pytest.raises(CodebuffValidationError) as exc_info:
            router.validate_message(message_data)

        assert "Unknown message type" in str(exc_info.value)

    def test_validate_message_missing_required_field_raises_error(self):
        """Test that message missing required field raises error."""
        router = MessageRouter()
        message_data = {"type": "identify", "txid": 123}  # Missing clientSessionId

        with pytest.raises(CodebuffValidationError) as exc_info:
            router.validate_message(message_data)

        assert "validation failed" in str(exc_info.value).lower()

    def test_validate_message_invalid_field_type_raises_error(self):
        """Test that message with invalid field type raises error."""
        router = MessageRouter()
        message_data = {
            "type": "ping",
            "txid": "not-an-integer",  # Should be int
        }

        with pytest.raises(CodebuffValidationError) as exc_info:
            router.validate_message(message_data)

        assert "validation failed" in str(exc_info.value).lower()

    # ========================================================================
    # Acknowledgment Creation Tests
    # ========================================================================

    def test_create_ack_success(self):
        """Test creating success acknowledgment."""
        router = MessageRouter()

        ack = router.create_ack(txid=123, success=True)

        assert ack.type == "ack"
        assert ack.txid == 123
        assert ack.success is True
        assert ack.error is None

    def test_create_ack_failure(self):
        """Test creating failure acknowledgment."""
        router = MessageRouter()

        ack = router.create_ack(txid=456, success=False, error="Test error")

        assert ack.type == "ack"
        assert ack.txid == 456
        assert ack.success is False
        assert ack.error == "Test error"

    def test_create_ack_no_txid(self):
        """Test creating acknowledgment without txid."""
        router = MessageRouter()

        ack = router.create_ack(txid=None, success=True)

        assert ack.type == "ack"
        assert ack.txid is None
        assert ack.success is True

    # ========================================================================
    # Message Routing Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_route_message_valid_identify(self):
        """Test routing valid identify message."""
        router = MessageRouter()
        message_json = json.dumps(
            {"type": "identify", "txid": 123, "clientSessionId": "session-123"}
        )

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is not None
        assert isinstance(validated_message, IdentifyMessage)
        assert validated_message.type == "identify"
        assert ack.success is True
        assert ack.txid == 123

    @pytest.mark.asyncio
    async def test_route_message_valid_ping(self):
        """Test routing valid ping message."""
        router = MessageRouter()
        message_json = json.dumps({"type": "ping", "txid": 456})

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is not None
        assert isinstance(validated_message, PingMessage)
        assert validated_message.type == "ping"
        assert ack.success is True
        assert ack.txid == 456

    @pytest.mark.asyncio
    async def test_route_message_valid_subscribe(self):
        """Test routing valid subscribe message."""
        router = MessageRouter()
        message_json = json.dumps(
            {"type": "subscribe", "txid": 789, "topics": ["topic1", "topic2"]}
        )

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is not None
        assert isinstance(validated_message, SubscribeMessage)
        assert validated_message.type == "subscribe"
        assert ack.success is True
        assert ack.txid == 789

    @pytest.mark.asyncio
    async def test_route_message_invalid_json(self):
        """Test routing invalid JSON."""
        router = MessageRouter()
        invalid_json = "{invalid json}"

        validated_message, ack = await router.route_message(invalid_json)

        assert validated_message is None
        assert ack.success is False
        assert ack.error is not None
        assert "Invalid JSON" in ack.error

    @pytest.mark.asyncio
    async def test_route_message_unknown_type(self):
        """Test routing message with unknown type."""
        router = MessageRouter()
        message_json = json.dumps({"type": "unknown", "txid": 999})

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is None
        assert ack.success is False
        assert ack.error is not None
        assert "Unknown message type" in ack.error
        assert ack.txid == 999

    @pytest.mark.asyncio
    async def test_route_message_validation_error(self):
        """Test routing message with validation error."""
        router = MessageRouter()
        message_json = json.dumps({"type": "identify", "txid": 123})  # Missing field

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is None
        assert ack.success is False
        assert ack.error is not None
        assert ack.txid == 123

    @pytest.mark.asyncio
    async def test_route_message_preserves_txid_on_error(self):
        """Test that txid is preserved in ack even on error."""
        router = MessageRouter()
        message_json = json.dumps({"type": "unknown", "txid": 12345})

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is None
        assert ack.success is False
        assert ack.txid == 12345

    @pytest.mark.asyncio
    async def test_route_message_handles_missing_txid(self):
        """Test routing message without txid."""
        router = MessageRouter()
        message_json = json.dumps({"type": "unknown"})  # No txid

        validated_message, ack = await router.route_message(message_json)

        assert validated_message is None
        assert ack.success is False
        assert ack.txid is None

    @pytest.mark.asyncio
    async def test_route_message_does_not_raise_exceptions(self):
        """Test that route_message never raises exceptions."""
        router = MessageRouter()

        # Try various invalid inputs
        invalid_inputs = [
            "{invalid}",
            '{"type": "unknown"}',
            '{"type": "ping"}',  # Missing txid
            "",
            "not json at all",
        ]

        for invalid_input in invalid_inputs:
            # Should not raise
            validated_message, ack = await router.route_message(invalid_input)

            # Should always return an ack
            assert ack is not None
            assert ack.type == "ack"
