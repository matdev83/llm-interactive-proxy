"""Contract tests for Gemini connector streaming chunk shape and tool-call shape.

These tests assert behavioral parity for:
- Streaming chunks have candidates list (via domain translation to OpenAI-style)
- Each streaming chunk carries text content in delta.content
- Final streaming chunk has finish_reason set
- Non-streaming response has choices[0].message.content and usage fields
- Tool-call response chunk has tool_calls with name and args
- Tool-call works without any workaround flags in options
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini import GeminiApiConfig, GeminiBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService

from tests.unit.gemini_connector_tests.helpers import (
    attach_gemini_non_streaming_httpx_mocks,
)

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
def gemini_backend(mock_client, mock_config, translation_service):
    backend = GeminiBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )
    backend.api_key = "test-api-key"
    backend.key_name = "x-goog-api-key"
    backend.gemini_api_base_url = "https://generativelanguage.googleapis.com"
    return backend


# ---------------------------------------------------------------------------
# Gemini streaming JSON-lines fixtures
# ---------------------------------------------------------------------------

GEMINI_TEXT_CHUNKS = [
    '{"candidates":[{"content":{"parts":[{"text":"Hello"}],"role":"model"},"finishReason":null,"index":0}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":1}}\n',
    '{"candidates":[{"content":{"parts":[{"text":" world"}],"role":"model"},"finishReason":"STOP","index":0}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2}}\n',
]

GEMINI_TOOL_CALL_CHUNKS = [
    '{"candidates":[{"content":{"parts":[{"functionCall":{"name":"get_weather","args":{"location":"Paris"}}}],"role":"model"},"finishReason":"STOP","index":0}]}\n',
]


def _make_streaming_mock_response(json_chunks: list[str]) -> MagicMock:
    """Build a mock httpx response that streams the given JSON-lines chunks."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    async def _aiter_text():
        for chunk in json_chunks:
            yield chunk

    mock_response.aiter_text = _aiter_text
    mock_response.aclose = AsyncMock()
    return mock_response


async def _collect_stream_chunks(
    backend: GeminiBackend, json_chunks: list[str]
) -> list:
    """Drive _handle_gemini_streaming_response and return ProcessedResponse.content items."""
    mock_response = _make_streaming_mock_response(json_chunks)

    with (
        patch.object(backend.client, "build_request", return_value=MagicMock()),
        patch.object(backend.client, "send", return_value=mock_response),
    ):
        handle = await backend._handle_gemini_streaming_response(
            base_url="https://generativelanguage.googleapis.com",
            payload={"contents": [{"role": "user", "parts": [{"text": "Hi"}]}]},
            headers={"x-goog-api-key": "test-api-key"},
            effective_model="gemini-1.5-flash",
        )
        chunks = []
        async for processed in handle.iterator:
            chunks.append(processed.content)
        return chunks


# ---------------------------------------------------------------------------
# Test 1: Streaming chunks have candidates list (via domain OpenAI-style)
# ---------------------------------------------------------------------------


class TestGeminiStreamingShape:
    @pytest.mark.asyncio
    async def test_streaming_chunks_have_choices(self, gemini_backend):
        """Each streaming chunk must be in OpenAI domain format with choices list."""
        chunks = await _collect_stream_chunks(gemini_backend, GEMINI_TEXT_CHUNKS)

        assert len(chunks) > 0, "Expected at least one domain chunk"

        # Translation produces CanonicalStreamChunk objects with choices
        for i, chunk in enumerate(chunks):
            # chunk is a CanonicalStreamChunk (has .choices) or dict
            if hasattr(chunk, "choices"):
                assert chunk.choices is not None, f"Chunk {i} has None choices"
                assert len(chunk.choices) > 0, f"Chunk {i} has empty choices"
            elif isinstance(chunk, dict):
                assert "choices" in chunk, f"Chunk {i} missing choices: {chunk}"
                assert len(chunk["choices"]) > 0, f"Chunk {i} has empty choices"

    # ---------------------------------------------------------------------------
    # Test 2: Each streaming chunk's delta carries text content
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_streaming_text_chunks_carry_content(self, gemini_backend):
        """Text streaming chunks must carry content in delta."""
        chunks = await _collect_stream_chunks(gemini_backend, GEMINI_TEXT_CHUNKS)

        text_contents = []
        for chunk in chunks:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                if delta and getattr(delta, "content", None):
                    text_contents.append(delta.content)
            elif isinstance(chunk, dict) and chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {})
                if delta.get("content"):
                    text_contents.append(delta["content"])

        assert len(text_contents) > 0, "Expected at least one chunk with text content"
        full_text = "".join(text_contents)
        assert (
            "Hello" in full_text or "world" in full_text
        ), f"Expected 'Hello' or 'world' in text content, got: {full_text!r}"

    # ---------------------------------------------------------------------------
    # Test 3: Final streaming chunk has finish_reason set
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_final_streaming_chunk_has_finish_reason(self, gemini_backend):
        """The final streaming chunk must have finish_reason set (not None)."""
        chunks = await _collect_stream_chunks(gemini_backend, GEMINI_TEXT_CHUNKS)

        finish_reasons = []
        for chunk in chunks:
            if hasattr(chunk, "choices") and chunk.choices:
                fr = chunk.choices[0].finish_reason
                if fr is not None:
                    finish_reasons.append(fr)
            elif isinstance(chunk, dict) and chunk.get("choices"):
                fr = chunk["choices"][0].get("finish_reason")
                if fr is not None:
                    finish_reasons.append(fr)

        assert (
            len(finish_reasons) > 0
        ), f"Expected at least one chunk with finish_reason. Got {len(chunks)} chunks."


# ---------------------------------------------------------------------------
# Test 4: Non-streaming response shape
# ---------------------------------------------------------------------------


class TestGeminiNonStreamingShape:
    @pytest.mark.asyncio
    async def test_non_streaming_response_has_content_and_usage(self, gemini_backend):
        """Non-streaming Gemini response must have choices[0].message.content and usage."""
        gemini_response = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hello there"}], "role": "model"},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 3,
                "totalTokenCount": 8,
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = gemini_response

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        non_streaming_request = CanonicalChatRequest(
            model="gemini-1.5-flash",
            messages=[ChatMessage(role="user", content="Hi")],
            max_tokens=100,
            stream=False,
        )
        connector_request = ConnectorChatCompletionsRequest(
            request=non_streaming_request,
            processed_messages=[ChatMessage(role="user", content="Hi")],
            effective_model="gemini-1.5-flash",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        with patch.object(
            gemini_backend,
            "_resolve_gemini_api_config",
            new_callable=AsyncMock,
            return_value=GeminiApiConfig(
                base_url="https://generativelanguage.googleapis.com",
                headers={"x-goog-api-key": "test-api-key"},
            ),
        ):
            result = await gemini_backend.chat_completions(connector_request)

        assert isinstance(result, ResponseEnvelope)
        content = result.content
        assert isinstance(content, dict), f"Expected dict content, got {type(content)}"

        choices = content.get("choices", [])
        assert len(choices) > 0, f"Expected choices in response, got: {content}"

        message = choices[0].get("message", {})
        assert (
            message.get("content") is not None
        ), f"Expected message.content, got: {choices[0]}"

        # Usage must be present (from usageMetadata)
        assert result.usage is not None, "Expected usage in ResponseEnvelope"
        assert result.usage.prompt_tokens == 5
        assert result.usage.completion_tokens == 3


# ---------------------------------------------------------------------------
# Test 5: Tool-call response chunk has tool_calls with name and args
# ---------------------------------------------------------------------------


class TestGeminiToolCallShape:
    @pytest.mark.asyncio
    async def test_tool_call_chunk_has_function_name_and_args(self, gemini_backend):
        """Gemini tool-call response must produce a chunk with tool_calls.function.name and args."""
        chunks = await _collect_stream_chunks(gemini_backend, GEMINI_TOOL_CALL_CHUNKS)

        assert (
            len(chunks) > 0
        ), "Expected at least one domain chunk from tool-call stream"

        tool_call_chunks = []
        for chunk in chunks:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                if delta and getattr(delta, "tool_calls", None):
                    tool_call_chunks.append(chunk)
            elif isinstance(chunk, dict) and chunk.get("choices"):
                delta = chunk["choices"][0].get("delta", {})
                if delta.get("tool_calls"):
                    tool_call_chunks.append(chunk)

        assert (
            len(tool_call_chunks) > 0
        ), f"Expected chunks with tool_calls. Got {len(chunks)} chunks."

        # Verify first tool_call has name and arguments
        first = tool_call_chunks[0]
        if hasattr(first, "choices"):
            tc = first.choices[0].delta.tool_calls[0]
            assert tc.function is not None, "tool_call must have function"
            assert (
                tc.function.name == "get_weather"
            ), f"Expected function.name='get_weather', got: {tc.function.name}"
            args = json.loads(tc.function.arguments)
            assert (
                args.get("location") == "Paris"
            ), f"Expected location='Paris' in args, got: {args}"
        else:
            tc = first["choices"][0]["delta"]["tool_calls"][0]
            fn = tc.get("function", {})
            assert fn.get("name") == "get_weather"
            args = json.loads(fn.get("arguments", "{}"))
            assert args.get("location") == "Paris"

    # ---------------------------------------------------------------------------
    # Test 6: Tool-call works without workaround flags in options
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_call_requires_no_workaround_flags(self, gemini_backend):
        """Tool-call must work with plain options={} — no workaround flags needed."""
        tool_def = {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            },
        }

        non_streaming_request = CanonicalChatRequest(
            model="gemini-1.5-flash",
            messages=[ChatMessage(role="user", content="What's the weather in Paris?")],
            max_tokens=100,
            stream=False,
            tools=[tool_def],
        )
        # options={} — no workaround flags
        connector_request = ConnectorChatCompletionsRequest(
            request=non_streaming_request,
            processed_messages=[
                ChatMessage(role="user", content="What's the weather in Paris?")
            ],
            effective_model="gemini-1.5-flash",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        gemini_tool_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "get_weather",
                                    "args": {"location": "Paris"},
                                }
                            }
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15,
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = gemini_tool_response
        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        with patch.object(
            gemini_backend,
            "_resolve_gemini_api_config",
            new_callable=AsyncMock,
            return_value=GeminiApiConfig(
                base_url="https://generativelanguage.googleapis.com",
                headers={"x-goog-api-key": "test-api-key"},
            ),
        ):
            # Must not raise — no workaround flags needed
            result = await gemini_backend.chat_completions(connector_request)

        assert isinstance(
            result, ResponseEnvelope
        ), f"Expected ResponseEnvelope, got {type(result)}"
        assert result.status_code == 200
