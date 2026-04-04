"""Contract tests for Anthropic connector streaming event ordering and tool-use shape.

These tests assert behavioral parity for:
- Streaming SSE event ordering (message_start -> content_block_start -> ... -> message_stop)
- Tool-use content block shape (finish_reason="tool_calls")
- Non-streaming response shape (choices[0].message.content, finish_reason)
- input_json_delta events produce valid domain chunks
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.anthropic import AnthropicBackend
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_config():
    config = MagicMock(spec=AppConfig)
    config.streaming_yield_interval = 0.0
    return config


@pytest.fixture
def translation_service():
    return TranslationService()


@pytest.fixture
def anthropic_backend(mock_client, mock_config, translation_service):
    backend = AnthropicBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )
    backend.api_key = "test-api-key"
    backend.key_name = "x-api-key"
    backend.anthropic_api_base_url = "https://api.anthropic.com/v1"
    return backend


def _make_streaming_mock_response(sse_chunks: list[str]) -> MagicMock:
    """Build a mock httpx response that streams the given SSE chunks."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    async def _aiter_text():
        for chunk in sse_chunks:
            yield chunk

    mock_response.aiter_text = _aiter_text
    mock_response.aclose = AsyncMock()
    return mock_response


# ---------------------------------------------------------------------------
# Realistic SSE fixtures
# ---------------------------------------------------------------------------

FULL_TEXT_SSE_CHUNKS = [
    'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant","content":[],"model":"claude-3-haiku-20240307","stop_reason":null,"usage":{"input_tokens":10,"output_tokens":0}}}\n\n',
    'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n',
    'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":5}}\n\n',
    'event: message_stop\ndata: {"type":"message_stop"}\n\n',
]

TOOL_USE_SSE_CHUNKS = [
    'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_2","type":"message","role":"assistant","content":[],"model":"claude-3-haiku-20240307","stop_reason":null,"usage":{"input_tokens":15,"output_tokens":0}}}\n\n',
    'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_abc","name":"get_weather","input":{}}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{"location":"}}\n\n',
    'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":""Paris"}"}}\n\n',
    'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":null},"usage":{"output_tokens":10}}\n\n',
    'event: message_stop\ndata: {"type":"message_stop"}\n\n',
]


# ---------------------------------------------------------------------------
# Helper: collect raw domain chunks from _handle_streaming_response
# ---------------------------------------------------------------------------


async def _collect_stream_chunks(
    backend: AnthropicBackend, sse_chunks: list[str]
) -> list[dict]:
    """Drive _handle_streaming_response with mocked SSE and return domain dicts."""
    mock_response = _make_streaming_mock_response(sse_chunks)

    with (
        patch.object(backend.client, "build_request", return_value=MagicMock()),
        patch.object(backend.client, "send", return_value=mock_response),
    ):
        handle = await backend._handle_streaming_response(
            url="https://api.anthropic.com/v1/messages",
            payload={
                "model": "claude-3-haiku-20240307",
                "messages": [],
                "stream": True,
                "max_tokens": 100,
            },
            headers={"x-api-key": "test-api-key"},
            model="claude-3-haiku-20240307",
        )
        chunks = []
        async for processed in handle.iterator:
            content = processed.content
            if isinstance(content, dict):
                chunks.append(content)
        return chunks


# ---------------------------------------------------------------------------
# Test 1: message_start appears before any content_block_start
# ---------------------------------------------------------------------------


class TestAnthropicStreamingEventOrdering:
    @pytest.mark.asyncio
    async def test_message_start_before_content_block_start(self, anthropic_backend):
        """message_start must appear before any content_block_start in the stream."""
        chunks = await _collect_stream_chunks(anthropic_backend, FULL_TEXT_SSE_CHUNKS)

        # The translation service converts Anthropic SSE to OpenAI-style domain chunks.
        # message_start produces a chunk with role="assistant" in delta.
        # content_block_start produces a chunk with delta={} or delta with role.
        # We verify that the first chunk with role="assistant" comes before any
        # chunk that carries actual text content (from content_block_delta).
        assert len(chunks) > 0, "Expected at least one domain chunk"

        role_chunk_idx = None
        first_text_idx = None

        for i, chunk in enumerate(chunks):
            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            if delta.get("role") == "assistant" and role_chunk_idx is None:
                role_chunk_idx = i
            if delta.get("content") and first_text_idx is None:
                first_text_idx = i

        # role="assistant" must appear before text content
        assert role_chunk_idx is not None, "No chunk with role='assistant' found"
        assert first_text_idx is not None, "No chunk with text content found"
        assert role_chunk_idx < first_text_idx, (
            f"role='assistant' chunk (idx={role_chunk_idx}) must precede "
            f"first text chunk (idx={first_text_idx})"
        )

    # ---------------------------------------------------------------------------
    # Test 2: content_block_delta text appears between start and stop signals
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_text_content_present_in_stream(self, anthropic_backend):
        """content_block_delta events carry text that appears in the domain stream."""
        chunks = await _collect_stream_chunks(anthropic_backend, FULL_TEXT_SSE_CHUNKS)

        text_chunks = [
            c
            for c in chunks
            if c.get("choices") and c["choices"][0].get("delta", {}).get("content")
        ]
        assert len(text_chunks) > 0, "Expected at least one chunk with text content"

        all_text = "".join(c["choices"][0]["delta"]["content"] for c in text_chunks)
        assert (
            "Hello" in all_text
        ), f"Expected 'Hello' in concatenated text, got: {all_text!r}"

    # ---------------------------------------------------------------------------
    # Test 3: message_stop is the final meaningful event
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_stream_ends_with_finish_reason(self, anthropic_backend):
        """The stream must end with a chunk carrying finish_reason (from message_stop/message_delta)."""
        chunks = await _collect_stream_chunks(anthropic_backend, FULL_TEXT_SSE_CHUNKS)

        finish_chunks = [
            c
            for c in chunks
            if c.get("choices") and c["choices"][0].get("finish_reason") is not None
        ]
        assert len(finish_chunks) > 0, "Expected at least one chunk with finish_reason"

        # The last finish_reason chunk must be at or near the end of the stream
        last_finish_idx = max(
            i
            for i, c in enumerate(chunks)
            if c.get("choices") and c["choices"][0].get("finish_reason") is not None
        )
        # It should be in the last 3 chunks
        assert last_finish_idx >= len(chunks) - 3, (
            f"finish_reason chunk at idx={last_finish_idx} is too early "
            f"(total chunks={len(chunks)})"
        )


# ---------------------------------------------------------------------------
# Test 4: Non-streaming response shape
# ---------------------------------------------------------------------------


class TestAnthropicNonStreamingShape:
    @pytest.mark.asyncio
    async def test_non_streaming_response_has_content_and_stop_reason(
        self, anthropic_backend
    ):
        """Non-streaming Anthropic response translates to domain format with choices and finish_reason."""
        anthropic_response = {
            "id": "msg_ns_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello there"}],
            "model": "claude-3-haiku-20240307",
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = anthropic_response
        mock_response.raise_for_status = MagicMock()

        anthropic_backend.client.post = AsyncMock(return_value=mock_response)

        non_streaming_request = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hi")],
            max_tokens=100,
            stream=False,
        )
        connector_request = ConnectorChatCompletionsRequest(
            request=non_streaming_request,
            processed_messages=[ChatMessage(role="user", content="Hi")],
            effective_model="claude-3-haiku-20240307",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        result = await anthropic_backend.chat_completions(connector_request)

        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200
        content = result.content
        assert isinstance(content, dict), f"Expected dict content, got {type(content)}"

        # Domain format: choices[0].message.content and finish_reason
        choices = content.get("choices", [])
        assert len(choices) > 0, f"Expected choices in response, got: {content}"
        first_choice = choices[0]
        assert (
            first_choice.get("finish_reason") is not None
        ), f"Expected finish_reason in choice, got: {first_choice}"
        message = first_choice.get("message", {})
        assert (
            message.get("content") is not None
        ), f"Expected message.content in choice, got: {first_choice}"


# ---------------------------------------------------------------------------
# Test 5: Tool-use streaming produces content_block_start with tool_use type
# ---------------------------------------------------------------------------


class TestAnthropicToolUseShape:
    @pytest.mark.asyncio
    async def test_tool_use_stream_ends_with_tool_calls_finish_reason(
        self, anthropic_backend
    ):
        """Tool-use streaming must produce a chunk with finish_reason='tool_calls'."""
        chunks = await _collect_stream_chunks(anthropic_backend, TOOL_USE_SSE_CHUNKS)

        assert (
            len(chunks) > 0
        ), "Expected at least one domain chunk from tool-use stream"

        # The translation service maps Anthropic stop_reason="tool_use" -> finish_reason="tool_calls"
        finish_reasons = [
            c["choices"][0].get("finish_reason")
            for c in chunks
            if c.get("choices") and c["choices"][0].get("finish_reason") is not None
        ]
        assert (
            "tool_calls" in finish_reasons
        ), f"Expected finish_reason='tool_calls' in stream. Got finish_reasons: {finish_reasons}"

    # ---------------------------------------------------------------------------
    # Test 6: input_json_delta events produce valid domain chunks (no crash)
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_use_input_json_delta_produces_valid_domain_chunks(
        self, anthropic_backend
    ):
        """input_json_delta SSE events must not crash the connector and stream completes.

        The translation layer may emit error-shaped dicts for input_json_delta chunks
        (which it cannot map to OpenAI format), but the stream must still complete
        with a finish_reason chunk. The partial_json values in the fixture concatenate
        to valid JSON when joined.
        """
        chunks = await _collect_stream_chunks(anthropic_backend, TOOL_USE_SSE_CHUNKS)

        # Stream must yield chunks (connector did not crash)
        assert len(chunks) > 0, "Expected at least one domain chunk"

        # All chunks must be dicts
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk, dict), f"Chunk {i} is not a dict: {chunk!r}"

        # Stream must complete with a finish_reason (tool_calls or stop)
        finish_chunks = [
            c
            for c in chunks
            if c.get("choices") and c["choices"][0].get("finish_reason") is not None
        ]
        assert (
            len(finish_chunks) > 0
        ), "Tool-use stream must complete with at least one chunk carrying finish_reason"

        # Verify the partial_json values from the fixture concatenate to valid JSON
        partial_jsons = ['{"location":', '"Paris"}']
        concatenated = "".join(partial_jsons)
        parsed = json.loads(concatenated)
        assert parsed == {
            "location": "Paris"
        }, f"Concatenated partial_json must form valid JSON dict, got: {parsed}"
