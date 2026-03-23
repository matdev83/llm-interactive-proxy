"""Wrap ``ProcessedResponse`` streams with periodic keepalives (connector-safe path).

Lives under ``src.core.services.streaming`` so connectors may import it per
architectural boundaries (``src.core.services.streaming_keepalive`` is not).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from typing import Any, cast

from pydantic.types import JsonValue

from src.core.interfaces.response_processor_interface import ProcessedResponse


def _keepalive_processed_response(
    *,
    completion_id: str,
    model: str,
    session_id: str | None,
    stream_id: str | None,
) -> ProcessedResponse:
    created = int(time.time())
    metadata: dict[str, JsonValue] = {
        "_keepalive": True,
        "id": completion_id,
        "model": model,
        "created": created,
    }
    if session_id:
        metadata["session_id"] = session_id
    if stream_id:
        metadata["stream_id"] = stream_id
    return ProcessedResponse(content="", metadata=metadata)


async def wrap_processed_stream_with_idle_keepalive(
    stream: AsyncIterator[ProcessedResponse],
    *,
    keepalive_interval: float,
    idle_timeout: float | None,
    stream_id: str | None,
    model_name: str | None,
    on_idle_timeout: Callable[[], Awaitable[ProcessedResponse]] | None = None,
) -> AsyncIterator[ProcessedResponse]:
    """Yield upstream chunks, emitting keepalive ``ProcessedResponse``s while waiting.

    While blocked on the next upstream chunk (e.g. NIM reasoning without SSE bytes),
    periodic keepalives keep the **client-facing** connection busy so browsers,
    reverse proxies, and SDKs do not treat the stream as hung and close it.

    If ``idle_timeout`` is set and ``on_idle_timeout`` is provided, exceeding the
    idle budget yields that chunk once and ends the wrapper (OpenRouter pattern).
    """

    iterator = stream.__aiter__()
    pending: asyncio.Task[ProcessedResponse] | None = asyncio.create_task(
        cast(Coroutine[Any, Any, ProcessedResponse], anext(iterator))
    )
    last_activity = time.monotonic()
    keepalive_id = f"chatcmpl-keepalive-{uuid.uuid4().hex}"

    try:
        while True:
            if pending is None:
                break

            done, _ = await asyncio.wait({pending}, timeout=keepalive_interval)
            if pending in done:
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    break
                last_activity = time.monotonic()
                yield chunk
                pending = asyncio.create_task(
                    cast(Coroutine[Any, Any, ProcessedResponse], anext(iterator))
                )
                continue

            elapsed = time.monotonic() - last_activity
            if (
                idle_timeout is not None
                and idle_timeout > 0
                and elapsed >= idle_timeout
                and on_idle_timeout is not None
            ):
                yield await on_idle_timeout()
                break

            yield _keepalive_processed_response(
                completion_id=keepalive_id,
                model=model_name or "keepalive",
                session_id=stream_id,
                stream_id=stream_id,
            )
    except asyncio.CancelledError:
        if pending is not None:
            pending.cancel()
        raise
    finally:
        if pending is not None and not pending.done():
            pending.cancel()


__all__ = ["wrap_processed_stream_with_idle_keepalive"]
