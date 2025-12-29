"""Best-effort decoding of captured traffic into canonical contracts.

This module provides utilities to decode raw bytes from capture entries
into typed canonical contracts (CanonicalChatRequest, ResponseEnvelope, etc.)
for simulation and replay workflows.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from pydantic import ValidationError

from src.core.common.json_validation import JSONValidationError, validate_json_structure
from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry, CaptureMetadata
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class DecodeError:
    """Error information for decode failures."""

    message: str
    details: dict[str, object] | None = None

    def __str__(self) -> str:
        return self.message


@dataclass
class DecodeResult(Generic[T]):
    """Typed result container for decode operations.

    Represents either a successful decode (with value) or a failure
    (with error and diagnostics). Best-effort decoding means failures
    don't raise exceptions but return failure results.
    """

    _value: T | None = None
    _error: DecodeError | None = None
    _diagnostics: dict[str, object] | None = None

    @classmethod
    def success(cls, value: T) -> DecodeResult[T]:
        """Create a successful decode result."""
        return cls(_value=value, _error=None, _diagnostics=None)

    @classmethod
    def failure(
        cls,
        error: DecodeError,
        diagnostics: dict[str, object] | None = None,
    ) -> DecodeResult[T]:
        """Create a failed decode result."""
        merged_diagnostics = error.details.copy() if error.details else {}
        if diagnostics:
            merged_diagnostics.update(diagnostics)
        return cls(
            _value=None,
            _error=error,
            _diagnostics=merged_diagnostics if merged_diagnostics else None,
        )

    @property
    def is_success(self) -> bool:
        """Check if decode was successful."""
        return self._error is None

    @property
    def is_failure(self) -> bool:
        """Check if decode failed."""
        return self._error is not None

    @property
    def value(self) -> T:
        """Get the decoded value (raises if failure)."""
        if self._error is not None:
            raise ValueError(f"Cannot get value from failed result: {self._error}")
        assert self._value is not None
        return self._value

    @property
    def error(self) -> DecodeError | None:
        """Get the decode error (None if success)."""
        return self._error

    @property
    def diagnostics(self) -> dict[str, object] | None:
        """Get additional diagnostics (None if success)."""
        return self._diagnostics


class CaptureDecoder:
    """Best-effort decoder for capture entries into canonical contracts.

    Treats raw bytes as source-of-truth and provides typed views when possible.
    Failures are non-blocking and return DecodeResult with error details.
    """

    def decode_inbound_request(
        self, entry: CaptureEntry
    ) -> DecodeResult[CanonicalChatRequest]:
        """Decode inbound request from client (CLIENT_TO_PROXY).

        Args:
            entry: Capture entry with CLIENT_TO_PROXY direction

        Returns:
            DecodeResult with CanonicalChatRequest on success, error on failure
        """
        if entry.direction != CaptureDirection.CLIENT_TO_PROXY:
            return DecodeResult.failure(
                DecodeError(
                    f"Expected CLIENT_TO_PROXY direction, got {entry.direction}",
                    details={"direction": int(entry.direction)},
                )
            )

        return self._decode_request_bytes(entry.data, entry.metadata)

    def decode_outbound_request(
        self, entry: CaptureEntry
    ) -> DecodeResult[CanonicalChatRequest]:
        """Decode outbound request to backend (PROXY_TO_BACKEND).

        Args:
            entry: Capture entry with PROXY_TO_BACKEND direction

        Returns:
            DecodeResult with CanonicalChatRequest on success, error on failure
        """
        if entry.direction != CaptureDirection.PROXY_TO_BACKEND:
            return DecodeResult.failure(
                DecodeError(
                    f"Expected PROXY_TO_BACKEND direction, got {entry.direction}",
                    details={"direction": int(entry.direction)},
                )
            )

        return self._decode_request_bytes(entry.data, entry.metadata)

    def decode_response(
        self, entry: CaptureEntry
    ) -> DecodeResult[ResponseEnvelope | StreamingResponseEnvelope]:
        """Decode response from backend or to client.

        Args:
            entry: Capture entry with BACKEND_TO_PROXY or PROXY_TO_CLIENT direction

        Returns:
            DecodeResult with ResponseEnvelope or StreamingResponseEnvelope on success
        """
        if entry.direction not in (
            CaptureDirection.BACKEND_TO_PROXY,
            CaptureDirection.PROXY_TO_CLIENT,
        ):
            return DecodeResult.failure(
                DecodeError(
                    f"Expected BACKEND_TO_PROXY or PROXY_TO_CLIENT, got {entry.direction}",
                    details={"direction": int(entry.direction)},
                )
            )

        # Check if this is a streaming response based on metadata or content
        is_streaming = (
            entry.metadata.is_stream_start
            or entry.metadata.chunk_index is not None
            or self._looks_like_sse(entry.data)
        )

        if is_streaming:
            # Cast to union type for mypy compatibility
            return cast(
                DecodeResult[ResponseEnvelope | StreamingResponseEnvelope],
                self._decode_streaming_response(entry),
            )
        else:
            # Cast to union type for mypy compatibility
            return cast(
                DecodeResult[ResponseEnvelope | StreamingResponseEnvelope],
                self._decode_non_streaming_response(entry),
            )

    def _decode_request_bytes(
        self, data: bytes, metadata: CaptureMetadata | None = None
    ) -> DecodeResult[CanonicalChatRequest]:
        """Decode request bytes into CanonicalChatRequest."""
        if not data:
            return DecodeResult.failure(
                DecodeError("Empty request data", details={"data_length": 0})
            )

        # Parse JSON
        try:
            decoded_str = data.decode("utf-8")
        except UnicodeDecodeError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"Failed to decode bytes as UTF-8: {e}",
                    details={"data_preview": data[:100] if len(data) > 100 else data},
                )
            )

        try:
            request_dict = json.loads(decoded_str)
        except json.JSONDecodeError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"Failed to parse JSON: {e}",
                    details={
                        "json_error": str(e),
                        "data_preview": (
                            decoded_str[:200] if len(decoded_str) > 200 else decoded_str
                        ),
                    },
                ),
                diagnostics={"raw_bytes": data, "attempted_format": "json"},
            )

        # DoS protection: Validate JSON structure (depth and array size)
        try:
            validate_json_structure(request_dict)
        except JSONValidationError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"JSON structure validation failed: {e}",
                    details={"validation_error": str(e)},
                ),
                diagnostics={"raw_bytes": data, "attempted_format": "json"},
            )

        # Validate and construct CanonicalChatRequest
        try:
            request = CanonicalChatRequest.model_validate(request_dict)
            return DecodeResult.success(request)
        except ValidationError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"Failed to validate request: {e}",
                    details={"validation_errors": str(e)},
                ),
                diagnostics={"parsed_dict": request_dict},
            )

    def _decode_non_streaming_response(
        self, entry: CaptureEntry
    ) -> DecodeResult[ResponseEnvelope]:
        """Decode non-streaming response into ResponseEnvelope."""
        if not entry.data:
            return DecodeResult.failure(
                DecodeError("Empty response data", details={"data_length": 0})
            )

        # Parse JSON
        try:
            decoded_str = entry.data.decode("utf-8")
        except UnicodeDecodeError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"Failed to decode bytes as UTF-8: {e}",
                    details={"data_preview": entry.data[:100]},
                )
            )

        try:
            response_dict = json.loads(decoded_str)
        except json.JSONDecodeError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"Failed to parse JSON: {e}",
                    details={"json_error": str(e)},
                ),
                diagnostics={"raw_bytes": entry.data, "attempted_format": "json"},
            )

        # DoS protection: Validate JSON structure (depth and array size)
        try:
            validate_json_structure(response_dict)
        except JSONValidationError as e:
            return DecodeResult.failure(
                DecodeError(
                    f"JSON structure validation failed: {e}",
                    details={"validation_error": str(e)},
                ),
                diagnostics={"raw_bytes": entry.data, "attempted_format": "json"},
            )

        # Construct ResponseEnvelope with parsed content
        envelope = ResponseEnvelope(
            content=response_dict,
            media_type="application/json",
            status_code=200,
        )

        return DecodeResult.success(envelope)

    def _decode_streaming_response(
        self, entry: CaptureEntry
    ) -> DecodeResult[StreamingResponseEnvelope]:
        """Decode streaming response into StreamingResponseEnvelope.

        Note: Full streaming reconstruction requires multiple entries.
        This method handles individual chunks best-effort.
        """
        # For streaming, we create an envelope but full reconstruction
        # would happen at a higher level (e.g., CaptureReader.get_stream_chunks)

        # Extract JSON from SSE format if present
        if self._looks_like_sse(entry.data):
            with contextlib.suppress(UnicodeDecodeError):
                decoded = entry.data.decode("utf-8")
                # Extract JSON from "data: {...}" format
                if decoded.startswith("data: "):
                    json_part = decoded[6:].strip()
                    if json_part == "[DONE]":
                        # Stream end marker
                        envelope = StreamingResponseEnvelope(
                            content=None,
                            media_type="text/event-stream",
                        )
                        return DecodeResult.success(envelope)
                    # Try to parse JSON, but ignore if invalid (best-effort)
                    with contextlib.suppress(json.JSONDecodeError):
                        _ = json.loads(json_part)  # Parsed but not used in this context

        # Create streaming envelope
        # Note: In practice, streaming responses are reconstructed from multiple entries
        # This is a best-effort single-entry decode
        envelope = StreamingResponseEnvelope(
            content=None,  # Would be populated from stream reconstruction
            media_type="text/event-stream",
        )

        return DecodeResult.success(envelope)

    def _looks_like_sse(self, data: bytes) -> bool:
        """Check if data looks like SSE (Server-Sent Events) format."""
        try:
            decoded = data.decode("utf-8", errors="ignore")
            return decoded.startswith("data: ") or decoded.strip() == "[DONE]"
        except (MemoryError, RecursionError) as exc:
            # System-level exceptions from string operations (memory issues, recursion errors)
            # Log with context and return False (best-effort decoding)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to check if data looks like SSE due to system error: data_length=%d",
                    len(data),
                    exc_info=True,
                )
            return False
        except Exception as exc:
            # Unexpected errors during SSE format detection (defensive guard)
            # Log with context and return False (best-effort decoding)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to check if data looks like SSE: data_length=%d",
                    len(data),
                    exc_info=True,
                )
            return False
