"""
Middleware for processing structured outputs in Responses API.

This middleware integrates with the existing response processing pipeline
to handle JSON schema validation and repair for structured outputs.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.common.exceptions import JSONParsingError, ValidationError
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.json_repair_service import JsonRepairService

logger = logging.getLogger(__name__)


class StructuredOutputMiddleware(IResponseMiddleware):
    """
    Middleware to handle structured output validation and repair for Responses API.

    This middleware integrates with the existing response processing pipeline
    and uses the JsonRepairService to validate and repair JSON responses
    against provided schemas.
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
            logger.debug(
                f"Skipping structured output validation for streaming response in session {session_id}"
            )
            return response

        # Extract content from the response
        content = self._extract_content(response)
        if not content:
            logger.debug(f"No content to validate in session {session_id}")
            return response

        # Determine strictness from context
        strict_validation = context.get("strict_schema_validation", True)

        try:
            # Process the structured response
            processed_content, parsed_object = (
                self._json_repair_service.process_structured_response(
                    content=content,
                    schema=schema,
                    session_id=session_id,
                    strict=strict_validation,
                )
            )

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

            logger.debug(
                f"Structured output processing completed for session {session_id}"
            )
            return updated_response

        except (ValidationError, JSONParsingError) as e:
            logger.error(
                f"Structured output validation failed for session {session_id}: {e}"
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
            logger.warning(
                f"Unable to extract content from response type: {type(response)}"
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
                metadata=metadata,
            )
