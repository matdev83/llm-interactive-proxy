from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.model_bases import InternalDTO
from src.core.interfaces.response_processor_interface import ProcessedResponse


@dataclass
class ResponseEnvelope(InternalDTO):
    """Transport-agnostic response container for non-streaming responses.

    Decouples backend connectors from FastAPI/Starlette Response.
    Adapters in controller layers are responsible for mapping this to the
    appropriate transport-specific response types.
    """

    content: Any  # Response content (dict, string, bytes, etc.)
    headers: dict[str, str] | None = None
    status_code: int = 200
    media_type: str = "application/json"
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


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
    cancel_callback: Callable[[], Awaitable[None]] | None = None

    @property
    def body_iterator(self) -> AsyncIterator[bytes]:
        """Backward-compatible alias used by tests and adapters for the
        streaming iterator (previously provided by Starlette's
        StreamingResponse.body_iterator)."""

        iterator = self.content

        async def _byte_iterator() -> AsyncIterator[bytes]:
            if iterator is None:
                return
            async for item in iterator:
                chunk = item.content
                if isinstance(chunk, bytes):
                    yield chunk
                else:
                    yield str(chunk).encode("utf-8")

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
