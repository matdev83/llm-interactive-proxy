from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.gemini import GeminiBackend
from src.core.common.exceptions import AuthenticationError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope


class TestGeminiStreamingInitError:
    @pytest.mark.asyncio
    async def test_streaming_init_error_returns_sse(self):
        """
        Test that an exception during initialization (e.g. config resolution)
        returns a StreamingResponseEnvelope with an error chunk if streaming is requested.
        """
        # Mock dependencies
        client = AsyncMock()
        config = MagicMock()
        translation_service = MagicMock()

        backend = GeminiBackend(client, config, translation_service)

        # Mock _resolve_gemini_api_config to raise an exception
        backend._resolve_gemini_api_config = AsyncMock(
            side_effect=AuthenticationError("Init failed")
        )

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gemini-pro",
            stream=True,
        )
        connector_req = ConnectorChatCompletionsRequest(
            request=request,
            processed_messages=[],
            effective_model="gemini-pro",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        response = await backend.chat_completions(connector_req)

        # Verify it returns a StreamingResponseEnvelope
        assert isinstance(response, StreamingResponseEnvelope)

        # Verify the content is an error chunk
        chunks = []
        async for chunk in response.content:
            chunks.append(chunk)

        assert len(chunks) == 1
        chunk_bytes = chunks[0].content
        decoded = chunk_bytes.decode("utf-8")

        print(f"Decoded output: {decoded}")

        # Verify SSE format
        assert decoded.startswith("data: ")
        assert "Init failed" in decoded
        assert "AuthenticationError" in decoded
        assert "data: [DONE]" in decoded
