import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic.types import JsonValue

from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.model_bases import InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse


@dataclass
class ResponseEnvelope(InternalDTO):
    """Transport-agnostic response container for non-streaming responses.

    Decouples backend connectors from FastAPI/Starlette Response.
    Adapters in controller layers are responsible for mapping this to the
    appropriate transport-specific response types.
    """

    content: (
        dict[str, Any] | str | bytes | None
    )  # Response content (JSON dict, string, bytes, or None)
    headers: dict[str, str] | None = None
    status_code: int = 200
    media_type: str = "application/json"
    usage: UsageSummary | None = None
    metadata: dict[str, JsonValue] | None = None
    canonical_usage: CanonicalUsageRecord | None = None


@dataclass
class StreamingResponseEnvelope(InternalDTO):
    """Transport-agnostic streaming response container.

    Decouples backend connectors from FastAPI/Starlette StreamingResponse.
    Adapters in controller layers are responsible for mapping this to the
    appropriate transport-specific response types.
    """

    # Iterator of raw bytes to be sent to clients. Tests expect bytes.
    content: AsyncIterator[ProcessedResponse] | None = None
    media_type: str = "text/event-stream"
    headers: dict[str, str] | None = None
    status_code: int = 200
    cancel_callback: Callable[[], Awaitable[None]] | None = None
    metadata: dict[str, JsonValue] | None = None
    canonical_usage: CanonicalUsageRecord | None = None

    @property
    def body_iterator(self) -> AsyncIterator[bytes]:
        """Backward-compatible alias used by tests and adapters for the
        streaming iterator (previously provided by Starlette's
        StreamingResponse.body_iterator).

        When media_type is "text/event-stream", applies SSE framing (data: ...\n\n)
        to ensure consistency regardless of which adapter is used. Content that
        already contains SSE line types (data:, event:, id:, retry:, or :) is
        passed through unchanged to avoid double-framing. Multi-line payloads are
        properly split into multiple data: lines per SSE specification.
        """

        def _is_already_sse_formatted(text: str) -> bool:
            """Check if text content is already SSE-formatted.
            
            SSE lines can start with: data:, event:, id:, retry:, or : (comment).
            Only the first non-empty line is checked, and it must start at column 0
            (no leading whitespace) to be considered SSE-formatted.
            
            This prevents false positives from indented data: or data: appearing
            on later lines.
            """
            for line in text.splitlines():
                if line == "":
                    continue
                # Check if first non-empty line starts with SSE prefix at column 0
                return line.startswith(("data:", "event:", "id:", "retry:", ":"))
            # No non-empty lines found
            return False

        def _frame_as_sse(payload: str) -> bytes:
            """Frame a payload as SSE with proper multi-line handling.
            
            Per SSE spec, multi-line payloads should be split and each line
            prefixed with "data: ". The event ends with \\n\\n.
            """
            lines = payload.splitlines()
            if not lines:
                return b"data: \n\n"
            
            # Prefix each line with "data: " and join with newlines
            framed_lines = [f"data: {line}" for line in lines]
            return "\n".join(framed_lines).encode("utf-8") + b"\n\n"

        iterator = self.content
        is_sse = (
            self.media_type.startswith("text/event-stream")
            if self.media_type
            else False
        )

        async def _byte_iterator() -> AsyncIterator[bytes]:
            if iterator is None:
                return
            async for item in iterator:
                chunk = item.content
                if isinstance(chunk, bytes):
                    # If SSE is expected, check if already formatted
                    if is_sse:
                        try:
                            text_content = chunk.decode("utf-8", errors="replace")
                        except UnicodeDecodeError:
                            # If not valid UTF-8, use base64 encoding for SSE
                            import base64
                            text_content = base64.b64encode(chunk).decode("ascii")
                            yield _frame_as_sse(text_content)
                        else:
                            if _is_already_sse_formatted(text_content):
                                # Already SSE-formatted, pass through unchanged
                                yield chunk
                            else:
                                # Apply SSE framing to bytes that aren't already framed
                                yield _frame_as_sse(text_content)
                    else:
                        yield chunk
                elif isinstance(chunk, dict):
                    # Serialize dict content as JSON instead of Python repr
                    json_str = json.dumps(chunk)
                    if is_sse:
                        # Apply SSE framing for SSE media type
                        yield _frame_as_sse(json_str)
                    else:
                        yield json_str.encode("utf-8")
                else:
                    # Convert other types to string
                    str_content = str(chunk)
                    if is_sse:
                        # Check if string is already SSE-formatted to prevent double-framing
                        if _is_already_sse_formatted(str_content):
                            # Already SSE-formatted, emit unchanged
                            yield str_content.encode("utf-8")
                        else:
                            # Apply SSE framing for SSE media type
                            yield _frame_as_sse(str_content)
                    else:
                        yield str_content.encode("utf-8")

        return _byte_iterator()


@dataclass
class StreamingResponseHandle:
    """Wrapper for streaming iterator and protocol-specific cancellation callback."""

    iterator: AsyncIterator[ProcessedResponse]
    cancel_callback: Callable[[], Awaitable[None]]
    headers: dict[str, str] | None = None


# SECURITY: Removed builtins injection to prevent test/production contamination
# Previously, these classes were injected into builtins for test convenience,
# but this created dangerous global state that allowed test data to leak
# into production code execution. All imports must now be explicit.
