"""
Message router for Codebuff WebSocket protocol.

This module handles parsing, validation, and routing of incoming messages
to appropriate handlers.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from pydantic import ValidationError

from src.codebuff.exceptions import (
    CodebuffMessageError,
    CodebuffValidationError,
    format_error_response,
)
from src.codebuff.schemas import (
    AckMessage,
    ActionMessage,
    ClientMessage,
    IdentifyMessage,
    PingMessage,
    SubscribeMessage,
    UnsubscribeMessage,
)

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes incoming messages to appropriate handlers.

    The MessageRouter is responsible for:
    - Parsing JSON messages
    - Validating messages against schemas
    - Routing messages to appropriate handlers
    - Generating acknowledgment responses
    """

    def __init__(self) -> None:
        """Initialize the message router."""

    def parse_json(self, raw_message: str) -> dict[str, Any]:
        """Parse a JSON message string.

        Args:
            raw_message: Raw JSON string from WebSocket

        Returns:
            Parsed message as dictionary

        Raises:
            CodebuffMessageError: If JSON parsing fails
        """
        try:
            return cast(dict[str, Any], json.loads(raw_message))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON message: {e}")
            raise CodebuffMessageError(
                message=f"Invalid JSON: {e!s}",
                message_type="unknown",
                details={"raw_message": raw_message[:100]},
            ) from e

    def validate_message(self, message_data: dict[str, Any]) -> ClientMessage:
        """Validate a message against the appropriate schema.

        Args:
            message_data: Parsed message dictionary

        Returns:
            Validated message object

        Raises:
            CodebuffValidationError: If validation fails
        """
        message_type = message_data.get("type")

        if not message_type:
            raise CodebuffValidationError(
                message="Message missing 'type' field",
                message_type="unknown",
                details={"message_data": message_data},
            )

        try:
            # Route to appropriate schema based on type
            if message_type == "identify":
                return IdentifyMessage(**message_data)
            elif message_type == "ping":
                return PingMessage(**message_data)
            elif message_type == "subscribe":
                return SubscribeMessage(**message_data)
            elif message_type == "unsubscribe":
                return UnsubscribeMessage(**message_data)
            elif message_type == "action":
                return ActionMessage(**message_data)
            else:
                raise CodebuffValidationError(
                    message=f"Unknown message type: {message_type}",
                    message_type=message_type,
                    details={"message_data": message_data},
                )

        except ValidationError as e:
            logger.error(f"Message validation failed for type '{message_type}': {e}")
            raise CodebuffValidationError(
                message=f"Message validation failed: {e!s}",
                message_type=message_type,
                validation_errors=e.errors(),
                details={"message_data": message_data},
            ) from e

    def create_ack(
        self, txid: int | None, success: bool, error: str | None = None
    ) -> AckMessage:
        """Create an acknowledgment message.

        Args:
            txid: Transaction ID from the original message
            success: Whether the message was processed successfully
            error: Error message if success is False

        Returns:
            AckMessage object
        """
        return AckMessage(type="ack", txid=txid, success=success, error=error)

    async def route_message(
        self, raw_message: str
    ) -> tuple[ClientMessage | None, AckMessage]:
        """Parse, validate, and route a message.

        This is the main entry point for processing incoming messages.
        It handles parsing, validation, and generates appropriate acknowledgments.

        Args:
            raw_message: Raw JSON string from WebSocket

        Returns:
            Tuple of (validated_message, ack_message)
            - validated_message is None if parsing/validation failed
            - ack_message contains success status and any errors

        Note:
            This method does not raise exceptions. All errors are captured
            in the returned AckMessage.
        """
        txid = None

        try:
            # Parse JSON
            message_data = self.parse_json(raw_message)

            # Extract txid if present (for ack response)
            txid = message_data.get("txid")

            # Validate message
            validated_message = self.validate_message(message_data)

            # Create success ack
            ack = self.create_ack(txid=txid, success=True)

            return validated_message, ack

        except (CodebuffMessageError, CodebuffValidationError) as e:
            # Create error ack using format_error_response
            error_response = format_error_response(e, txid=txid)
            ack = AckMessage(**error_response)
            return None, ack

        except Exception as e:
            # Catch any unexpected errors
            logger.error(f"Unexpected error routing message: {e}", exc_info=True)
            error_response = format_error_response(
                Exception(f"Internal error: {e!s}"), txid=txid
            )
            ack = AckMessage(**error_response)
            return None, ack
