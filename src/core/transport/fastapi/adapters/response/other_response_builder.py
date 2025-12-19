"""Other response builder for non-JSON responses."""

from __future__ import annotations

import json

from fastapi.responses import Response

from src.core.domain.responses import ResponseEnvelope
from src.core.transport.fastapi.adapters.protocols import (
    IHeaderSanitizer,
)
from src.core.transport.fastapi.adapters.sanitization.header_sanitizer import (
    HeaderSanitizer,
)


class OtherResponseBuilder:
    """Build FastAPI Response for non-JSON content types.

    Handles binary, text, and other non-JSON response types with
    appropriate header sanitization.
    """

    def __init__(self, header_sanitizer: IHeaderSanitizer | None = None) -> None:
        """Initialize other response builder.

        Args:
            header_sanitizer: Optional header sanitizer. Creates default if not provided.
        """
        self._header_sanitizer = header_sanitizer or HeaderSanitizer()

    def build(self, envelope: ResponseEnvelope) -> Response:
        """Build Response from envelope.

        Args:
            envelope: Response envelope

        Returns:
            FastAPI Response
        """
        # Get content and media type
        content = envelope.content
        media_type = getattr(envelope, "media_type", None) or "application/octet-stream"

        # Sanitize headers
        headers = envelope.headers or {}
        safe_headers = self._header_sanitizer.sanitize(headers)

        # Handle content conversion
        content_bytes: bytes
        if isinstance(content, bytes):
            content_bytes = content
        elif isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            # For iterables and other non-string content, use JSON serialization
            # to ensure consistent formatting (double quotes, proper escaping)
            try:
                content_bytes = json.dumps(content).encode("utf-8")
            except (TypeError, ValueError):
                # Fallback to string if JSON serialization fails
                content_bytes = str(content).encode("utf-8")

        # Create response
        return Response(
            content=content_bytes,
            status_code=envelope.status_code or 200,
            media_type=media_type,
            headers=safe_headers,
        )
