from __future__ import annotations

import json

import httpx
import pytest
from hypothesis import given
from src.core.common.exceptions import (
    APIConnectionError,
    APITimeoutError,
    BackendError,
    LLMProxyError,
    ParsingError,
    RateLimitExceededError,
)
from src.core.ports.streaming_contracts import (
    StreamingErrorMapper,
    handle_streaming_error,
)
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import (
    error_type_strategy,
    provider_strategy,
    stream_id_strategy,
)


def _build_error(error_type: str) -> Exception:
    request = httpx.Request("GET", "https://example.com")
    if error_type == "timeout":
        return httpx.TimeoutException("timeout", request=request)
    if error_type.startswith("http_error_"):
        status = int(error_type.split("_")[-1])
        response = httpx.Response(status, request=request, text="body")
        return httpx.HTTPStatusError("http error", request=request, response=response)
    if error_type == "connect_error":
        return httpx.ConnectError("connect", request=request)
    if error_type == "json_error":
        return json.JSONDecodeError("bad json", "{}", 0)
    return RuntimeError("generic error")


def _expected_error_type(error_type: str) -> type[LLMProxyError]:
    if error_type == "timeout":
        return APITimeoutError
    if error_type.startswith("http_error_"):
        status = int(error_type.split("_")[-1])
        if status == 429:
            return RateLimitExceededError
        return BackendError
    if error_type == "connect_error":
        return APIConnectionError
    if error_type == "json_error":
        return ParsingError
    return BackendError


@given(
    error_type=error_type_strategy(),
    provider=provider_strategy(),
    stream_id=stream_id_strategy(),
)
@property_test_settings(max_examples=50)
def test_property_11_error_mapping_consistency(
    error_type: str, provider: str, stream_id: str | None
) -> None:
    """
    Property 11: Error mapping consistency.

    Every backend error type must be deterministically mapped to a single
    LLMProxyError subclass by StreamingErrorMapper.
    """

    error = _build_error(error_type)
    mapped = StreamingErrorMapper.map_backend_error(error, provider, stream_id)
    assert isinstance(mapped, _expected_error_type(error_type))
    assert mapped.details.get("provider") == provider
    if stream_id:
        assert mapped.details.get("stream_id") == stream_id


@pytest.mark.asyncio
@given(
    error_type=error_type_strategy(),
    provider=provider_strategy(),
    stream_id=stream_id_strategy(),
)
@property_test_settings(max_examples=50)
async def test_property_10_structured_error_chunks(
    error_type: str, provider: str, stream_id: str | None
) -> None:
    """
    Property 10: Structured error responses.

    Terminal error chunks emitted via handle_streaming_error must contain the
    standardized error metadata envelope expected by transports.
    """

    error = _build_error(error_type)
    chunk = await handle_streaming_error(error, stream_id, provider)
    assert chunk.is_done
    assert chunk.metadata.get("finish_reason") == "error"
    error_payload = chunk.metadata.get("error")
    assert isinstance(error_payload, dict)
    assert {"type", "message", "code", "retryable"} <= set(error_payload)
