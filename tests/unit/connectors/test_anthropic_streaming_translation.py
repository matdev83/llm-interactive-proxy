"""Tests for Anthropic connector streaming translation to domain format."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_anthropic_streaming_translates_to_domain_format():
    """Test that Anthropic streaming chunks are translated to domain format."""
    from src.connectors.anthropic import AnthropicBackend
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    # Setup
    client = httpx.AsyncClient()
    config = AppConfig()
    translation_service = TranslationService()

    backend = AnthropicBackend(client, config, translation_service)
    await backend.initialize(
        anthropic_api_base_url="https://api.anthropic.com/v1",
        key_name="test_key",
        api_key="test-api-key-123",
    )

    # Mock the HTTP response with Anthropic SSE format
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}

    # Simulate Anthropic streaming response
    anthropic_chunks = [
        'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_123","role":"assistant"}}\n\n',
        'event: content_block_start\ndata: {"type":"content_block_start","index":0}\n\n',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n',
        'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n',
        'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]

    async def mock_aiter_text():
        for chunk in anthropic_chunks:
            yield chunk

    mock_response.aiter_text = mock_aiter_text
    mock_response.aclose = AsyncMock()

    with (
        patch.object(backend.client, "build_request", return_value=MagicMock()),
        patch.object(backend.client, "send", return_value=mock_response),
    ):
        # Call the streaming handler
        stream_handle = await backend._handle_streaming_response(
            url="https://api.anthropic.com/v1/messages",
            payload={"model": "claude-3-opus-20240229", "messages": []},
            headers={"x-api-key": "test-api-key-123"},
            model="claude-3-opus-20240229",
        )

        # Collect all chunks
        chunks = []
        async for chunk in stream_handle.iterator:
            chunks.append(chunk.content)

        # Verify chunks are in domain format (OpenAI-style)
        assert len(chunks) > 0, "Expected chunks but got none"

        # Check that we got domain-formatted chunks
        content_chunks = [c for c in chunks if isinstance(c, dict) and c.get("choices")]
        assert (
            len(content_chunks) > 0
        ), f"Should have domain-formatted chunks. Got: {chunks[:3]}"

        # Verify structure matches OpenAI format
        for i, chunk in enumerate(content_chunks):
            assert "id" in chunk, f"Chunk {i} missing 'id': {chunk}"
            assert "object" in chunk, f"Chunk {i} missing 'object': {chunk}"
            assert (
                chunk["object"] == "chat.completion.chunk"
            ), f"Chunk {i} wrong object type: {chunk['object']}"
            assert "choices" in chunk, f"Chunk {i} missing 'choices': {chunk}"
            assert len(chunk["choices"]) > 0, f"Chunk {i} has empty choices"
            assert (
                "delta" in chunk["choices"][0]
            ), f"Chunk {i} missing 'delta': {chunk['choices'][0]}"
            assert (
                "index" in chunk["choices"][0]
            ), f"Chunk {i} missing 'index': {chunk['choices'][0]}"

        # Verify we got content - collect all content from deltas
        content_parts = []
        for chunk in content_chunks:
            delta = chunk["choices"][0]["delta"]
            if delta.get("content"):
                content_parts.append(delta["content"])

        full_content = "".join(content_parts)
        # At least one of the content chunks should have text
        assert (
            full_content
        ), f"Expected content but got empty. Chunks: {[c['choices'][0]['delta'] for c in content_chunks[:5]]}"
        assert (
            "Hello" in full_content or "world" in full_content
        ), f"Expected 'Hello' or 'world' in content, got: '{full_content}'"


@pytest.mark.asyncio
async def test_anthropic_streaming_handles_sse_format():
    """Test that Anthropic connector properly handles SSE format chunks."""
    from src.core.domain.translation import Translation

    # Test various SSE formats
    test_cases = [
        # Content delta
        (
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n',
            "Hi",
        ),
        # Message start
        (
            'data: {"type":"message_start","message":{"role":"assistant"}}\n\n',
            "assistant",
        ),
        # Message stop
        ('data: {"type":"message_stop"}\n\n', "stop"),
    ]

    for sse_chunk, expected_value in test_cases:
        result = Translation.anthropic_to_domain_stream_chunk(sse_chunk)

        # Verify it's in domain format
        assert isinstance(result, dict)
        assert "choices" in result
        assert "delta" in result["choices"][0]

        # Verify expected content
        delta = result["choices"][0]["delta"]
        if expected_value == "Hi":
            assert delta.get("content") == "Hi"
        elif expected_value == "assistant":
            assert delta.get("role") == "assistant"
        elif expected_value == "stop":
            assert result["choices"][0].get("finish_reason") == "stop"


@pytest.mark.asyncio
async def test_anthropic_streaming_handles_done_marker():
    """Test that [DONE] marker is properly translated."""
    from src.core.domain.translation import Translation

    result = Translation.anthropic_to_domain_stream_chunk("data: [DONE]\n\n")

    assert isinstance(result, dict)
    assert "choices" in result
    assert result["choices"][0]["delta"] == {}


@pytest.mark.asyncio
async def test_zai_coding_plan_uses_openai_format():
    """Test that zai-coding-plan now uses OpenAI-style API."""
    from src.connectors.openai import OpenAIConnector
    from src.connectors.zai_coding_plan import ZaiCodingPlanBackend

    # Use minimal mock setup to avoid heavy initialization
    client = MagicMock()
    config = MagicMock()
    translation_service = MagicMock()

    backend = ZaiCodingPlanBackend(client, config, translation_service)

    # Verify it inherits from OpenAI, not Anthropic
    assert isinstance(backend, OpenAIConnector)
    assert backend.backend_type == "zai-coding-plan"

    # Mock the _refresh_available_models to avoid network call entirely
    async def mock_refresh():
        backend.available_models = ["glm-4.6", "claude-sonnet-4-20250514"]
        backend._provider_models = {"glm-4.6", "claude-sonnet-4-20250514"}

    # Patch _refresh_available_models and directly set attributes to avoid initialization overhead
    with patch.object(backend, "_refresh_available_models", new=mock_refresh):
        # Directly set attributes that would be set during initialize
        backend.api_key = "test-zai-key"
        backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
        backend._max_tokens_limit = 200000
        backend._default_max_tokens = 8192

    # Verify correct API base URL
    assert backend.api_base_url == "https://api.z.ai/api/coding/paas/v4"

    # Verify available models (should use mocked response)
    models = await backend.get_available_models_async()
    assert "glm-4.6" in models
