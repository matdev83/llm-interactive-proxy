"""Unit tests for ResponseExecutor WebSocket support."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.contracts import ConnectorRequestContext
from src.connectors.openai_codex.executor import _CodexTransportAdapter
from src.core.common.exceptions import AuthenticationError
from src.core.domain.responses import ProcessedResponse, StreamingResponseHandle


@pytest.mark.asyncio
class TestCodexTransportAdapterWebSocket:
    """Test WebSocket transport in _CodexTransportAdapter."""

    async def test_initiate_websocket_streaming_success(self) -> None:
        """Test successful WebSocket streaming via transport adapter."""
        mock_connector = MagicMock()
        adapter = _CodexTransportAdapter(mock_connector, use_websocket=True)

        # Mock WebSocket client
        mock_ws_client = AsyncMock()
        mock_response_chunks = [
            ProcessedResponse(
                content={"message": {"content": "Hello"}},
                metadata={"id": "resp_1"},
            ),
            ProcessedResponse(
                content={"message": {"content": "World"}},
                metadata={"id": "resp_2"},
            ),
        ]

        async def mock_send_response_create(*args, **kwargs):
            for chunk in mock_response_chunks:
                yield chunk

        mock_ws_client.send_response_create = mock_send_response_create

        # Patch OpenAIWebSocketClient (imported inside the method)
        with patch(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            return_value=mock_ws_client,
        ):
            # Call initiate_streaming_request
            url = "https://chatgpt.com/backend-api/codex/responses"
            payload = {"model": "gpt-4", "input": []}
            headers = {"Authorization": "Bearer test_key"}
            session_id = "test_session"

            handle = await adapter.initiate_streaming_request(
                url, payload, headers, session_id
            )

            assert isinstance(handle, StreamingResponseHandle)

        # Consume the stream
        chunks = []
        async for chunk in handle.iterator:
            chunks.append(chunk)

        # Verify chunks
        assert len(chunks) == 2
        # Websocket transport adapter yields ProcessedResponse objects directly
        first_content = cast(dict[str, Any], chunks[0].content)
        second_content = cast(dict[str, Any], chunks[1].content)
        assert cast(dict[str, Any], first_content["message"])["content"] == "Hello"
        assert cast(dict[str, Any], second_content["message"])["content"] == "World"

    async def test_recreates_websocket_client_when_auth_token_changes(self) -> None:
        """Auth refresh retries must not reuse stale WebSocket credentials."""
        mock_connector = MagicMock()
        adapter = _CodexTransportAdapter(mock_connector, use_websocket=True)

        first_client = AsyncMock()
        second_client = AsyncMock()

        async def _stream_once(*args, **kwargs):  # type: ignore[no-untyped-def]
            if False:
                yield None

        first_client.send_response_create = _stream_once
        second_client.send_response_create = _stream_once

        with patch(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            side_effect=[first_client, second_client],
        ) as ws_ctor:
            url = "https://chatgpt.com/backend-api/codex/responses"
            payload = {"model": "gpt-4", "input": []}

            await adapter.initiate_streaming_request(
                url,
                payload,
                {"Authorization": "Bearer token-1"},
                "session-1",
            )
            await adapter.initiate_streaming_request(
                url,
                payload,
                {"Authorization": "Bearer token-2"},
                "session-1",
            )

        assert ws_ctor.call_count == 2
        assert ws_ctor.call_args_list[0].kwargs["api_key"] == "token-1"
        assert ws_ctor.call_args_list[1].kwargs["api_key"] == "token-2"
        first_client.disconnect.assert_awaited_once()

    async def test_initiate_websocket_streaming_no_auth(self) -> None:
        """Test WebSocket streaming fails without authorization header."""
        mock_connector = MagicMock()
        adapter = _CodexTransportAdapter(mock_connector, use_websocket=True)

        url = "https://chatgpt.com/backend-api/codex/responses"
        payload = {"model": "gpt-4", "input": []}
        headers: dict[str, str] = {}  # No authorization header
        session_id = "test_session"

        with pytest.raises(AuthenticationError, match="No API key"):
            await adapter.initiate_streaming_request(url, payload, headers, session_id)

    async def test_http_fallback_when_websocket_disabled(self) -> None:
        """Test fallback to HTTP/SSE when WebSocket is disabled."""
        mock_connector = MagicMock()
        mock_connector._handle_streaming_response = AsyncMock(
            return_value=StreamingResponseHandle(
                iterator=AsyncMock(), headers={}, cancel_callback=AsyncMock()
            )
        )

        adapter = _CodexTransportAdapter(mock_connector, use_websocket=False)

        url = "https://chatgpt.com/backend-api/codex/responses"
        payload = {"model": "gpt-4", "input": []}
        headers = {"Authorization": "Bearer test_key"}
        session_id = "test_session"

        handle = await adapter.initiate_streaming_request(
            url, payload, headers, session_id
        )

        # Verify HTTP/SSE method was called with wire-capture context slot
        mock_connector._handle_streaming_response.assert_called_once_with(
            url, payload, headers, session_id, "responses", context=None
        )
        assert isinstance(handle, StreamingResponseHandle)

    async def test_http_fallback_accepts_transport_metadata_kwargs(self) -> None:
        """Transport adapter should accept the executor's keyword metadata contract."""
        mock_connector = MagicMock()
        mock_connector._handle_streaming_response = AsyncMock(
            return_value=StreamingResponseHandle(
                iterator=AsyncMock(), headers={}, cancel_callback=AsyncMock()
            )
        )

        adapter = _CodexTransportAdapter(mock_connector, use_websocket=False)

        url = "https://chatgpt.com/backend-api/codex/responses"
        payload = {"model": "gpt-4", "input": []}
        headers = {"Authorization": "Bearer test_key"}
        session_id = "test_session"
        request_context = ConnectorRequestContext(
            request_id="req-1",
            session_id="sess-1",
            client_host="127.0.0.1",
            extensions={},
        )

        handle = await adapter.initiate_streaming_request(
            url,
            payload,
            headers,
            session_id,
            context=request_context,
            backend="openai-codex",
            model="gpt-4",
            key_name="openai-codex",
        )

        mock_connector._handle_streaming_response.assert_called_once_with(
            url,
            payload,
            headers,
            session_id,
            "responses",
            context=request_context,
        )
        assert isinstance(handle, StreamingResponseHandle)

    async def test_cleanup_closes_websocket_client(self) -> None:
        """Test cleanup properly disconnects WebSocket client."""
        mock_connector = MagicMock()
        adapter = _CodexTransportAdapter(mock_connector, use_websocket=True)

        # Create mock WebSocket client
        mock_ws_client = AsyncMock()
        adapter._websocket_client = mock_ws_client

        # Call cleanup
        await adapter.cleanup()

        # Verify disconnect was called
        mock_ws_client.disconnect.assert_called_once()
        assert adapter._websocket_client is None

    async def test_cleanup_handles_disconnect_error(self) -> None:
        """Test cleanup handles errors during WebSocket disconnect gracefully."""
        mock_connector = MagicMock()
        adapter = _CodexTransportAdapter(mock_connector, use_websocket=True)

        # Create mock WebSocket client that raises error on disconnect
        mock_ws_client = AsyncMock()
        mock_ws_client.disconnect.side_effect = Exception("Disconnect failed")
        adapter._websocket_client = mock_ws_client

        # Cleanup should not raise
        await adapter.cleanup()

        # Verify client was still cleaned up
        assert adapter._websocket_client is None

    async def test_url_conversion_http_to_ws(self) -> None:
        """Test HTTP URL is correctly converted to WebSocket URL."""
        mock_connector = MagicMock()
        adapter = _CodexTransportAdapter(mock_connector, use_websocket=True)

        mock_ws_client = AsyncMock()

        async def mock_send(*args, **kwargs):
            return
            yield  # Make it an async generator

        mock_ws_client.send_response_create = mock_send

        with patch(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            return_value=mock_ws_client,
        ) as mock_ws_class:
            url = "https://chatgpt.com/backend-api/codex/responses"
            payload = {"model": "gpt-4"}
            headers = {"Authorization": "Bearer key"}
            session_id = "test"

            handle = await adapter.initiate_streaming_request(
                url, payload, headers, session_id
            )

            # Verify handle was created
            assert isinstance(handle, StreamingResponseHandle)

            # Verify WebSocket URL was used
            mock_ws_class.assert_called_once()
            call_kwargs = mock_ws_class.call_args[1]
            assert call_kwargs["api_base"] == "wss://chatgpt.com/backend-api/codex"
            assert call_kwargs["api_key"] == "key"
