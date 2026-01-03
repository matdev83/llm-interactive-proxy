"""
Middleware for processing structured outputs in Responses API.

This middleware integrates with the existing response processing pipeline
to handle JSON schema validation and repair for structured outputs.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

from cachetools import TTLCache
from pydantic.types import JsonValue

from src.core.common.exceptions import JSONParsingError, ValidationError
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.json_repair_service import JsonRepairService

logger = logging.getLogger(__name__)


# ============================================================================
# New IResponseFeature implementation with enforced parity
# ============================================================================


class StructuredOutputFeature(IResponseFeature):
    """Feature for structured output validation with enforced streaming/non-streaming parity.

    This is the IResponseFeature version of StructuredOutputMiddleware that
    explicitly implements both streaming and non-streaming paths with shared
    validation logic.

    For streaming responses, this feature accumulates content across chunks
    and validates the complete response at stream end.
    """

    def __init__(
        self,
        json_repair_service: JsonRepairService,
        priority: int = 10,
    ) -> None:
        """Initialize the structured output feature.

        Args:
            json_repair_service: Service for JSON repair and validation
            priority: Feature priority (higher numbers run first)
        """
        super().__init__(priority)
        self._json_repair_service = json_repair_service
        # Streaming state: accumulate content per stream for validation
        self._stream_content: MutableMapping[str, str] = TTLCache(
            maxsize=10000, ttl=3600
        )
        self._stream_schemas: MutableMapping[str, Any] = TTLCache(
            maxsize=10000, ttl=3600
        )

    def _get_stream_key(self, session_id: str, context: dict[str, Any]) -> str:
        """Get unique key for tracking stream content."""
        stream_id = context.get("stream_id", "")
        return f"{session_id}:{stream_id}" if stream_id else session_id

    def _extract_content(self, response: Any) -> str | None:
        """Extract content from a response object."""
        if hasattr(response, "content"):
            return str(response.content) if response.content is not None else None
        elif isinstance(response, dict) and "content" in response:
            return str(response["content"]) if response["content"] is not None else None
        elif isinstance(response, str):
            return response
        else:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unable to extract content from response type: %s", type(response)
                )
            return None

    def _update_response(
        self,
        response: Any,
        processed_content: str,
        parsed_object: dict[str, Any] | None,
    ) -> Any:
        """Update a response object with processed content and parsed object."""
        if isinstance(response, ProcessedResponse):
            metadata = response.metadata or {}
            if parsed_object is not None:
                metadata["parsed_object"] = parsed_object

            return ProcessedResponse(
                content=processed_content,
                usage=response.usage,
                metadata=metadata,
            )
        elif hasattr(response, "content"):
            response.content = processed_content
            if parsed_object is not None:
                if not hasattr(response, "metadata") or response.metadata is None:
                    response.metadata = {}
                response.metadata["parsed_object"] = parsed_object
            return response
        elif isinstance(response, dict):
            updated_response = response.copy()
            updated_response["content"] = processed_content
            if parsed_object is not None:
                updated_response["parsed_object"] = parsed_object
            return updated_response
        else:
            metadata = (
                {"parsed_object": parsed_object} if parsed_object is not None else {}
            )
            return ProcessedResponse(
                content=processed_content,
                usage=None,
                metadata=metadata,  # type: ignore[arg-type]
            )

    def _validate_content(
        self,
        content: str,
        schema: Any,
        session_id: str,
        strict: bool,
        response: Any,
    ) -> Any:
        """Shared validation logic for both paths."""
        try:
            result = (
                self._json_repair_service.process_structured_response(
                    content=content,
                    schema=schema,
                    session_id=session_id,
                    strict=strict,
                )
            )
            processed_content: str = result.content
            parsed_object: dict[str, Any] | None = result.parsed_object

            updated_response = self._update_response(
                response, processed_content, parsed_object
            )

            # Add metadata about the validation
            if (
                hasattr(updated_response, "metadata")
                and updated_response.metadata is not None
            ):
                updated_response.metadata.update(
                    {
                        "structured_output_validated": parsed_object is not None,
                        "schema_validation_attempted": True,
                    }
                )
            elif isinstance(updated_response, ProcessedResponse):
                metadata = updated_response.metadata or {}
                metadata.update(
                    {
                        "structured_output_validated": parsed_object is not None,
                        "schema_validation_attempted": True,
                    }
                )
                updated_response = ProcessedResponse(
                    content=updated_response.content,
                    usage=updated_response.usage,
                    metadata=metadata,
                )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Structured output processing completed for session %s", session_id
                )
            return updated_response

        except (ValidationError, JSONParsingError) as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Structured output validation failed for session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )

            self._add_error_metadata(response, str(e))

            if strict:
                raise

            return response

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error in structured output for session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )

            self._add_error_metadata(response, f"Unexpected error: {e}")

            if strict:
                raise

            return response

    def _add_error_metadata(self, response: Any, error_msg: str) -> None:
        """Add error metadata to response."""
        error_info: dict[str, JsonValue] = {
            "structured_output_error": error_msg,
            "schema_validation_attempted": True,
            "structured_output_validated": False,
        }

        if (
            hasattr(response, "metadata") and response.metadata is not None
        ) or isinstance(response, ProcessedResponse):
            response.metadata.update(error_info)

    def _is_stream_end(self, context: dict[str, Any]) -> bool:
        """Check if this is the end of a stream."""
        if context.get("is_final_chunk"):
            return True
        if context.get("done"):
            return True
        return bool(context.get("finish_reason"))

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Validate non-streaming response against schema."""
        schema = context.get("response_schema")
        if not schema:
            return response

        content = self._extract_content(response)
        if not content:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("No content to validate in session %s", session_id)
            return response

        strict_validation = context.get("strict_schema_validation", True)
        return self._validate_content(
            content, schema, session_id, strict_validation, response
        )

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Accumulate streaming content and validate at stream end.

        For streaming, we accumulate content across chunks and validate
        the complete response when we detect the end of the stream.
        """
        schema = context.get("response_schema")
        if not schema:
            return chunk

        stream_key = self._get_stream_key(session_id, context)

        # Store schema for this stream
        if stream_key not in self._stream_schemas:
            self._stream_schemas[stream_key] = schema

        # Accumulate content
        content = self._extract_content(chunk)
        if content:
            if stream_key not in self._stream_content:
                self._stream_content[stream_key] = ""
            self._stream_content[stream_key] += content

        # Check if this is the end of the stream
        if self._is_stream_end(context):
            accumulated_content = self._stream_content.pop(stream_key, "")
            stream_schema = self._stream_schemas.pop(stream_key, schema)

            if accumulated_content:
                strict_validation = context.get("strict_schema_validation", True)

                # Validate the accumulated content
                return self._validate_content(
                    accumulated_content,
                    stream_schema,
                    session_id,
                    strict_validation,
                    chunk,
                )
            else:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "No accumulated content to validate at stream end for %s",
                        session_id,
                    )

        return chunk

    def reset_session(self, session_id: str) -> None:
        """Reset streaming state for a session."""
        keys_to_remove = [
            k for k in self._stream_content if k.startswith(f"{session_id}:")
        ]
        for key in keys_to_remove:
            self._stream_content.pop(key, None)
            self._stream_schemas.pop(key, None)
        self._stream_content.pop(session_id, None)
        self._stream_schemas.pop(session_id, None)


# ============================================================================
# Legacy IResponseMiddleware implementation (kept for backward compatibility)
# DEPRECATED: Use StructuredOutputFeature instead
# ============================================================================


class StructuredOutputMiddleware(IResponseMiddleware):
    """DEPRECATED: Use StructuredOutputFeature instead.

    Legacy middleware to handle structured output validation.
    This class is kept for backward compatibility only.
    """

    def __init__(
        self, json_repair_service: JsonRepairService, priority: int = 10
    ) -> None:
        """
        Initialize the structured output middleware.

        Args:
            json_repair_service: Service for JSON repair and validation
            priority: Middleware priority (higher numbers run first)
        """
        logger.error(
            "DEPRECATED: StructuredOutputMiddleware instantiated. "
            "Use StructuredOutputFeature instead for proper streaming/non-streaming parity."
        )
        self._json_repair_service = json_repair_service
        self._priority = priority

    @property
    def priority(self) -> int:
        """Get the middleware priority."""
        return self._priority

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """
        Process a response for structured output validation.

        Args:
            response: The response object to process
            session_id: Session identifier
            context: Processing context containing schema information
            is_streaming: Whether this is a streaming response
            stop_event: Optional stop event for streaming

        Returns:
            Processed response with validated structured output
        """
        # Only process if we have schema information in the context
        schema = context.get("response_schema")
        if not schema:
            # No schema provided, pass through unchanged
            return response

        # Skip processing for streaming responses in this implementation
        # Streaming structured output validation would require more complex handling
        if is_streaming:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping structured output validation for streaming response in session %s",
                    session_id,
                )
            return response

        # Extract content from the response
        content = self._extract_content(response)
        if not content:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("No content to validate in session %s", session_id)
            return response

        # Determine strictness from context
        strict_validation = context.get("strict_schema_validation", True)

        try:
            # Process the structured response
            result = (
                self._json_repair_service.process_structured_response(
                    content=content,
                    schema=schema,
                    session_id=session_id,
                    strict=strict_validation,
                )
            )
            processed_content: str = result.content
            parsed_object: dict[str, Any] | None = result.parsed_object

            # Update the response with processed content and parsed object
            updated_response = self._update_response(
                response, processed_content, parsed_object
            )

            # Add metadata about the validation
            if (
                hasattr(updated_response, "metadata")
                and updated_response.metadata is not None
            ):
                updated_response.metadata.update(
                    {
                        "structured_output_validated": parsed_object is not None,
                        "schema_validation_attempted": True,
                    }
                )
            elif isinstance(updated_response, ProcessedResponse):
                metadata = updated_response.metadata or {}
                metadata.update(
                    {
                        "structured_output_validated": parsed_object is not None,
                        "schema_validation_attempted": True,
                    }
                )
                updated_response = ProcessedResponse(
                    content=updated_response.content,
                    usage=updated_response.usage,
                    metadata=metadata,
                )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Structured output processing completed for session %s", session_id
                )
            return updated_response

        except (ValidationError, JSONParsingError) as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Structured output validation failed for session {session_id}: {e}",
                    exc_info=True,
                )

            # Add error information to the response metadata
            if hasattr(response, "metadata") and response.metadata is not None:
                response.metadata.update(
                    {
                        "structured_output_error": str(e),
                        "schema_validation_attempted": True,
                        "structured_output_validated": False,
                    }
                )
            elif isinstance(response, ProcessedResponse):
                metadata = response.metadata or {}
                metadata.update(
                    {
                        "structured_output_error": str(e),
                        "schema_validation_attempted": True,
                        "structured_output_validated": False,
                    }
                )
                response = ProcessedResponse(
                    content=response.content,
                    usage=response.usage,
                    metadata=metadata,
                )

            # In strict mode, re-raise the exception
            if strict_validation:
                raise

            # In non-strict mode, return the original response with error metadata
            return response

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error in structured output middleware for session {session_id}: {e}",
                    exc_info=True,
                )

            # Add error information to the response metadata
            if hasattr(response, "metadata") and response.metadata is not None:
                response.metadata.update(
                    {
                        "structured_output_error": f"Unexpected error: {e}",
                        "schema_validation_attempted": True,
                        "structured_output_validated": False,
                    }
                )
            elif isinstance(response, ProcessedResponse):
                metadata = response.metadata or {}
                metadata.update(
                    {
                        "structured_output_error": f"Unexpected error: {e}",
                        "schema_validation_attempted": True,
                        "structured_output_validated": False,
                    }
                )
                response = ProcessedResponse(
                    content=response.content,
                    usage=response.usage,
                    metadata=metadata,
                )

            if strict_validation:
                raise

            # Always return the original response for unexpected errors in non-strict mode
            return response

    def _extract_content(self, response: Any) -> str | None:
        """
        Extract content from a response object.

        Args:
            response: The response object

        Returns:
            The content string, or None if no content found
        """
        if hasattr(response, "content"):
            return str(response.content) if response.content is not None else None
        elif isinstance(response, dict) and "content" in response:
            return str(response["content"]) if response["content"] is not None else None
        elif isinstance(response, str):
            return response
        else:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unable to extract content from response type: %s", type(response)
                )
            return None

    def _update_response(
        self,
        response: Any,
        processed_content: str,
        parsed_object: dict[str, Any] | None,
    ) -> Any:
        """
        Update a response object with processed content and parsed object.

        Args:
            response: The original response object
            processed_content: The processed content string
            parsed_object: The parsed JSON object (if validation succeeded)

        Returns:
            Updated response object
        """
        if isinstance(response, ProcessedResponse):
            # For ProcessedResponse, create a new instance with updated content
            metadata = response.metadata or {}
            if parsed_object is not None:
                metadata["parsed_object"] = parsed_object

            return ProcessedResponse(
                content=processed_content,
                usage=response.usage,
                metadata=metadata,
            )
        elif hasattr(response, "content"):
            # For objects with content attribute, update it directly
            response.content = processed_content
            if parsed_object is not None:
                # Ensure metadata exists
                if not hasattr(response, "metadata") or response.metadata is None:
                    response.metadata = {}
                response.metadata["parsed_object"] = parsed_object
            return response
        elif isinstance(response, dict):
            # For dictionary responses, update the content key
            updated_response = response.copy()
            updated_response["content"] = processed_content
            if parsed_object is not None:
                updated_response["parsed_object"] = parsed_object
            return updated_response
        else:
            # For other types, return as ProcessedResponse
            metadata = (
                {"parsed_object": parsed_object} if parsed_object is not None else {}
            )
            return ProcessedResponse(
                content=processed_content,
                usage=None,
                metadata=metadata,  # type: ignore[arg-type]
            )
