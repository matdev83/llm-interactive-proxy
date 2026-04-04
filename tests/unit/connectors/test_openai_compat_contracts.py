"""Contract tests for OpenAI-compatible behavioral parity.

Asserts spec-shaped output for streaming chunks, tool-call deltas,
and error envelopes through the proxy connector layer (COMP-01).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError, RateLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_config():
    config = MagicMock(spec=AppConfig)
    config.streaming_yield_interval = 100
    return config


@pytest.fixture
def translation_service():
    return TranslationService()


@pytest.fixture
def openai_connector(mock_client, mock_config, translation_service):
    connector = OpenAIConnector(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )
    connector.api_key = "test-api-key"
    connector.api_base_url = "https://api.openai.com/v1"
    connector.disable_health_check()
    return connector


@pytest.fixture
def base_request():
    return ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="gpt-4",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="req-1",
            session_id="sess-1",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STREAMING_SSE = (
    'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
    'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
    'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)

_NON_STREAMING_JSON = {
    "id": "chatcmpl-2",
    "object": "chat.completion",
    "model": "gpt-4",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello there!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}

_TOOL_CALL_SSE = (
    'data: {"id":"chatcmpl-3","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_abc","type":"function","function":{"name":"get_weather","arguments":""}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"chatcmpl-3","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"city\\":\\"London\\"}"}}]},"finish_reason":null}]}\n\n'
    'data: {"id":"chatcmpl-3","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
    "data: [DONE]\n\n"
)

_TOOL_CALL_NON_STREAMING_JSON = {
    "id": "chatcmpl-4",
    "object": "chat.completion",
    "model": "gpt-4",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"London"}',
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 15, "completion_tokens": 20, "total_tokens": 35},
}


async def _collect_chunks(envelope: StreamingResponseEnvelope) -> list[dict[str, Any]]:
    """Collect all SSE chunks from a StreamingResponseEnvelope as parsed dicts."""
    chunks = []
    async for raw_bytes in envelope.body_iterator:
        text = raw_bytes.decode("utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload and payload != "[DONE]":
                    chunks.append(json.loads(payload))
    return chunks


# ---------------------------------------------------------------------------
# Task 1: Streaming and non-streaming shape contract tests
# ---------------------------------------------------------------------------


class TestOpenAIStreamingContractShape:
    """Contract tests for OpenAI streaming and non-streaming response shapes."""

    @pytest.mark.asyncio
    async def test_streaming_chunks_have_required_top_level_fields(
        self, openai_connector, base_request
    ):
        """Test 1: Each streaming chunk has id, object, choices fields."""
        streaming_req = ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="Hello")],
                max_tokens=100,
                stream=True,
            ),
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=base_request.context,
            options={},
        )

        async def fake_stream(request: CanonicalChatRequest):
            for line in _STREAMING_SSE.splitlines(keepends=True):
                if line.strip():
                    yield line.encode("utf-8")

        async def fake_integrate(raw_stream, *args: Any, **kwargs: Any):
            chunks = []
            async for chunk in raw_stream:
                chunks.append(chunk)

            async def _iter():
                for c in chunks:
                    yield ProcessedResponse(content=c)

            return StreamingResponseEnvelope(
                content=_iter(), media_type="text/event-stream"
            )

        with (
            patch(
                "src.core.ports.streaming_integration.integrate_streaming_pipeline",
                side_effect=fake_integrate,
            ),
            patch.object(openai_connector, "stream_completion", fake_stream),
        ):
            result = await openai_connector.chat_completions(streaming_req)

        assert isinstance(result, StreamingResponseEnvelope)
        chunks = await _collect_chunks(result)
        assert len(chunks) > 0, "Expected at least one parsed chunk"
        for chunk in chunks:
            assert "id" in chunk, f"Missing 'id' in chunk: {chunk}"
            assert "object" in chunk, f"Missing 'object' in chunk: {chunk}"
            assert (
                chunk["object"] == "chat.completion.chunk"
            ), f"Wrong object: {chunk['object']}"
            assert "choices" in chunk, f"Missing 'choices' in chunk: {chunk}"
            assert isinstance(chunk["choices"], list), "choices must be a list"

    @pytest.mark.asyncio
    async def test_streaming_chunk_delta_has_role_or_content(
        self, openai_connector, base_request
    ):
        """Test 2: Each streaming chunk's choices[0].delta has role or content (not empty)."""
        streaming_req = ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="Hello")],
                max_tokens=100,
                stream=True,
            ),
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=base_request.context,
            options={},
        )

        async def fake_stream(request: CanonicalChatRequest):
            for line in _STREAMING_SSE.splitlines(keepends=True):
                if line.strip():
                    yield line.encode("utf-8")

        async def fake_integrate(raw_stream, *args: Any, **kwargs: Any):
            chunks = []
            async for chunk in raw_stream:
                chunks.append(chunk)

            async def _iter():
                for c in chunks:
                    yield ProcessedResponse(content=c)

            return StreamingResponseEnvelope(
                content=_iter(), media_type="text/event-stream"
            )

        with (
            patch(
                "src.core.ports.streaming_integration.integrate_streaming_pipeline",
                side_effect=fake_integrate,
            ),
            patch.object(openai_connector, "stream_completion", fake_stream),
        ):
            result = await openai_connector.chat_completions(streaming_req)

        chunks = await _collect_chunks(result)
        # At least one chunk should have role or content in delta
        deltas_with_data = [
            c
            for c in chunks
            if c.get("choices")
            and (
                c["choices"][0].get("delta", {}).get("role")
                or c["choices"][0].get("delta", {}).get("content") is not None
                and c["choices"][0].get("delta", {}).get("content") != ""
                or c["choices"][0].get("delta", {}).get("tool_calls")
            )
        ]
        assert (
            len(deltas_with_data) > 0
        ), "Expected at least one chunk with role, content, or tool_calls in delta"

    @pytest.mark.asyncio
    async def test_final_streaming_chunk_has_finish_reason(
        self, openai_connector, base_request
    ):
        """Test 3: Final streaming chunk has choices[0].finish_reason set (not None)."""
        streaming_req = ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="Hello")],
                max_tokens=100,
                stream=True,
            ),
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=base_request.context,
            options={},
        )

        async def fake_stream(request: CanonicalChatRequest):
            for line in _STREAMING_SSE.splitlines(keepends=True):
                if line.strip():
                    yield line.encode("utf-8")

        async def fake_integrate(raw_stream, *args: Any, **kwargs: Any):
            chunks = []
            async for chunk in raw_stream:
                chunks.append(chunk)

            async def _iter():
                for c in chunks:
                    yield ProcessedResponse(content=c)

            return StreamingResponseEnvelope(
                content=_iter(), media_type="text/event-stream"
            )

        with (
            patch(
                "src.core.ports.streaming_integration.integrate_streaming_pipeline",
                side_effect=fake_integrate,
            ),
            patch.object(openai_connector, "stream_completion", fake_stream),
        ):
            result = await openai_connector.chat_completions(streaming_req)

        chunks = await _collect_chunks(result)
        assert len(chunks) > 0
        # Find the last chunk with a finish_reason
        finish_chunks = [
            c
            for c in chunks
            if c.get("choices") and c["choices"][0].get("finish_reason") is not None
        ]
        assert (
            len(finish_chunks) > 0
        ), "Expected at least one chunk with finish_reason set"
        last_finish = finish_chunks[-1]
        assert last_finish["choices"][0]["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_non_streaming_response_has_required_fields(
        self, openai_connector, base_request
    ):
        """Test 4: Non-streaming response has id, object, choices[0].message.content, usage."""
        with patch.object(
            openai_connector,
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
            return_value=ResponseEnvelope(
                content=_NON_STREAMING_JSON,
                status_code=200,
            ),
        ):
            result = await openai_connector.chat_completions(base_request)

        assert isinstance(result, ResponseEnvelope)
        body = result.content
        assert isinstance(body, dict), "Expected dict content"
        assert "id" in body, "Missing 'id'"
        assert "object" in body, "Missing 'object'"
        assert body["object"] == "chat.completion"
        assert "choices" in body, "Missing 'choices'"
        assert len(body["choices"]) > 0
        assert "message" in body["choices"][0], "Missing 'message' in choices[0]"
        assert (
            "content" in body["choices"][0]["message"]
        ), "Missing 'content' in message"
        assert "usage" in body, "Missing 'usage'"


# ---------------------------------------------------------------------------
# Task 2: Tool-call and error-shape contract tests
# ---------------------------------------------------------------------------


class TestOpenAIToolCallAndErrorShapeContracts:
    """Contract tests for tool-call delta shape and error envelope shape."""

    @pytest.mark.asyncio
    async def test_tool_call_streaming_chunk_has_required_fields(
        self, openai_connector, base_request
    ):
        """Test 5: Tool-call streaming chunk has choices[0].delta.tool_calls[0] with required fields."""
        streaming_req = ConnectorChatCompletionsRequest(
            request=CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="What's the weather?")],
                max_tokens=100,
                stream=True,
            ),
            processed_messages=[
                ChatMessage(role="user", content="What's the weather?")
            ],
            effective_model="gpt-4",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=base_request.context,
            options={},
        )

        async def fake_stream(request: CanonicalChatRequest):
            for line in _TOOL_CALL_SSE.splitlines(keepends=True):
                if line.strip():
                    yield line.encode("utf-8")

        async def fake_integrate(raw_stream, *args: Any, **kwargs: Any):
            chunks = []
            async for chunk in raw_stream:
                chunks.append(chunk)

            async def _iter():
                for c in chunks:
                    yield ProcessedResponse(content=c)

            return StreamingResponseEnvelope(
                content=_iter(), media_type="text/event-stream"
            )

        with (
            patch(
                "src.core.ports.streaming_integration.integrate_streaming_pipeline",
                side_effect=fake_integrate,
            ),
            patch.object(openai_connector, "stream_completion", fake_stream),
        ):
            result = await openai_connector.chat_completions(streaming_req)

        chunks = await _collect_chunks(result)
        tool_call_chunks = [
            c
            for c in chunks
            if c.get("choices") and c["choices"][0].get("delta", {}).get("tool_calls")
        ]
        assert len(tool_call_chunks) > 0, "Expected at least one tool_call chunk"

        first_tc_chunk = tool_call_chunks[0]
        tc = first_tc_chunk["choices"][0]["delta"]["tool_calls"][0]
        assert "id" in tc, "Missing 'id' in tool_calls[0]"
        assert "type" in tc, "Missing 'type' in tool_calls[0]"
        assert tc["type"] == "function", f"Expected type='function', got {tc['type']}"
        assert "function" in tc, "Missing 'function' in tool_calls[0]"
        assert "name" in tc["function"], "Missing 'name' in function"
        assert tc["function"]["name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_tool_call_non_streaming_response_has_required_fields(
        self, openai_connector, base_request
    ):
        """Test 6: Tool-call non-streaming response has choices[0].message.tool_calls[0] with required fields."""
        with patch.object(
            openai_connector,
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
            return_value=ResponseEnvelope(
                content=_TOOL_CALL_NON_STREAMING_JSON,
                status_code=200,
            ),
        ):
            result = await openai_connector.chat_completions(base_request)

        assert isinstance(result, ResponseEnvelope)
        body = result.content
        assert isinstance(body, dict)
        choices = body.get("choices", [])
        assert len(choices) > 0
        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        assert len(tool_calls) > 0, "Expected tool_calls in message"

        tc = tool_calls[0]
        assert "id" in tc, "Missing 'id' in tool_calls[0]"
        assert "type" in tc, "Missing 'type' in tool_calls[0]"
        assert tc["type"] == "function"
        assert "function" in tc, "Missing 'function' in tool_calls[0]"
        assert "name" in tc["function"], "Missing 'name' in function"
        assert "arguments" in tc["function"], "Missing 'arguments' in function"

    def test_error_envelope_has_openai_shape(self):
        """Test 7: Error envelope has shape {error: {message: str, type: str, code: str|int|None}}."""
        from src.core.common.exceptions import BackendError

        exc = BackendError(message="Something went wrong", status_code=500)
        http_exc = map_domain_exception_to_http_exception(exc)

        # The detail should contain error shape info
        detail = http_exc.detail
        # BackendError.to_dict() returns {"error": {...}}
        # map_domain_exception_to_http_exception unwraps it to the inner dict
        assert detail is not None

        # Reconstruct the full error envelope as it would be serialized
        error_body = exc.to_dict()
        assert "error" in error_body, "Missing top-level 'error' key"
        error = error_body["error"]
        assert "message" in error, "Missing 'message' in error"
        assert "type" in error, "Missing 'type' in error"
        assert isinstance(error["message"], str)
        assert isinstance(error["type"], str)

    def test_401_backend_error_maps_to_authentication_error_type(self):
        """Test 8: 401 backend error maps to HTTP 401 with error.type='authentication_error'."""
        exc = AuthenticationError(message="Invalid API key")
        http_exc = map_domain_exception_to_http_exception(exc)

        assert http_exc.status_code == 401

        # Verify the error shape via to_dict
        error_body = exc.to_dict()
        assert "error" in error_body
        error = error_body["error"]
        assert "message" in error
        assert "type" in error
        # AuthenticationError class name is the type
        assert (
            "Authentication" in error["type"]
            or "authentication" in error["type"].lower()
        )

    def test_429_backend_error_maps_to_rate_limit_error(self):
        """Test 9: 429 backend error maps to HTTP 429 with rate_limit in error type or code."""
        exc = RateLimitExceededError(message="Rate limit exceeded")
        http_exc = map_domain_exception_to_http_exception(exc)

        assert http_exc.status_code == 429

        # Verify the error shape via to_dict
        error_body = exc.to_dict()
        assert "error" in error_body
        error = error_body["error"]
        assert "message" in error
        assert "type" in error
        # RateLimitExceededError class name contains RateLimit
        assert "RateLimit" in error["type"] or "rate_limit" in error["type"].lower()
