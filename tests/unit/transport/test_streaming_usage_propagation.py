import pytest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.transport.fastapi.response_adapters import (
    to_fastapi_streaming_response,
)


async def _collect_streaming_body(response) -> str:
    """Consume a Starlette StreamingResponse and return the full body as text."""
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="ignore")


@pytest.mark.asyncio
async def test_usage_chunk_is_emitted_to_client_stream() -> None:
    """Ensure usage-only streaming chunks are not dropped before reaching the client."""

    async def usage_stream():
        # Usage-only chunk that previously looked "empty" to the pipeline
        yield ProcessedResponse(
            content={
                "id": "chatcmpl-usage-1",
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
            metadata={"model": "test-model"},
        )
        # Terminal chunk
        yield ProcessedResponse(content=None, metadata={"finish_reason": "stop"})

    envelope = StreamingResponseEnvelope(content=usage_stream())

    response = to_fastapi_streaming_response(envelope)
    body = await _collect_streaming_body(response)

    # Assert that the usage payload and fields are present in the emitted SSE stream
    assert '"usage"' in body
    assert '"prompt_tokens": 10' in body
    assert '"completion_tokens": 5' in body
    assert '"total_tokens": 15' in body
    # Sanity check that the stream still terminates
    assert "[DONE]" in body
