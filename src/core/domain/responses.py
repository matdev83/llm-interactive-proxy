from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.model_bases import InternalDTO


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
    content: AsyncIterator[bytes]
    media_type: str = "text/event-stream"
    headers: dict[str, str] | None = None

    @property
    def body_iterator(self) -> AsyncIterator[bytes]:
        """Backward-compatible alias used by tests and adapters for the
        streaming iterator (previously provided by Starlette's
        StreamingResponse.body_iterator)."""

        async def _byte_iterator() -> AsyncIterator[bytes]:
            async for item in self.content:
                # self.content already yields bytes
                yield item

        return _byte_iterator()


# Export envelope classes to builtins for tests that reference them without
# importing (some legacy tests refer to these names directly).
try:
    import builtins

    builtins.ResponseEnvelope = ResponseEnvelope  # type: ignore[attr-defined]
    builtins.StreamingResponseEnvelope = StreamingResponseEnvelope  # type: ignore[attr-defined]
except Exception:
    pass
