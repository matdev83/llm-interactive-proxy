"""Regression test for OpenAI Codex non-streaming response cleanup fix.

This test verifies that OpenAICodexConnector properly cleans up compatibility state
for non-streaming responses, preventing memory leaks.

Fixed: Added _handle_non_streaming_response override that calls cleanup_state.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.openai_codex import OpenAICodexConnector
from src.connectors.openai_codex.compat import CompatibilityLayer
from src.connectors.openai_codex.contracts import CompatibilityState
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


class TestCodexNonStreamingCleanupRegression:
    """Regression tests for OpenAI Codex non-streaming response cleanup fix."""

    @pytest.fixture
    def mock_config(self) -> AppConfig:
        """Create a mock AppConfig."""
        config = MagicMock(spec=AppConfig)
        config.backends = {}
        return config

    @pytest.fixture
    def mock_translation_service(self) -> TranslationService:
        """Create a mock TranslationService."""
        return MagicMock(spec=TranslationService)

    @pytest.fixture
    def mock_client(self):
        """Create a mock httpx.AsyncClient."""
        return MagicMock()

    def test_connector_has_handle_non_streaming_response_override(self) -> None:
        """Test that connector has _handle_non_streaming_response override."""
        assert hasattr(
            OpenAICodexConnector, "_handle_non_streaming_response"
        ), "Connector should override _handle_non_streaming_response for cleanup"

        # Check that it's actually an override (not just inherited)
        base_method = getattr(
            OpenAICodexConnector.__bases__[0], "_handle_non_streaming_response", None
        )
        connector_method = OpenAICodexConnector._handle_non_streaming_response

        # Methods should be different (override exists)
        assert (
            connector_method is not base_method
        ), "Connector should override parent's _handle_non_streaming_response"

    @pytest.mark.asyncio
    async def test_non_streaming_response_cleans_up_state(
        self,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
        mock_client,
    ) -> None:
        """Test that non-streaming responses clean up compatibility state."""
        # Create connector with mock compatibility layer
        connector = OpenAICodexConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Create mock compatibility layer
        mock_compat_layer = MagicMock(spec=CompatibilityLayer)
        mock_compat_layer.cleanup_state = AsyncMock()
        connector._compatibility_layer = mock_compat_layer

        # Create compatibility state
        state = CompatibilityState()
        state.droid_tool_name_cache["call_1"] = "tool_1"
        state.droid_tool_args_buffer["call_1"] = '{"arg": 1}'

        # Create payload with compatibility state in metadata
        payload = {
            "messages": [{"role": "user", "content": "test"}],
            "metadata": {"compatibility_state": state},
        }

        # Mock parent's _handle_non_streaming_response
        mock_response = MagicMock()
        connector._handle_non_streaming_response = AsyncMock(
            wraps=connector._handle_non_streaming_response
        )

        # Patch parent method to return mock response
        with patch.object(
            connector.__class__.__bases__[0],
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_parent:
            # Call the override method
            result = await connector._handle_non_streaming_response(
                url="https://api.example.com",
                payload=payload,
                headers={},
                session_id="test-session",
            )

            # Verify parent was called
            mock_parent.assert_called_once()

            # Verify cleanup_state was called
            mock_compat_layer.cleanup_state.assert_called_once_with(state)

            # Verify result is returned
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_non_streaming_response_cleans_up_on_exception(
        self,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
        mock_client,
    ) -> None:
        """Test that cleanup happens even if parent method raises exception."""
        connector = OpenAICodexConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        mock_compat_layer = MagicMock(spec=CompatibilityLayer)
        mock_compat_layer.cleanup_state = AsyncMock()
        connector._compatibility_layer = mock_compat_layer

        state = CompatibilityState()
        payload = {
            "messages": [{"role": "user", "content": "test"}],
            "metadata": {"compatibility_state": state},
        }

        # Mock parent to raise exception
        with patch.object(
            connector.__class__.__bases__[0],
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
            side_effect=Exception("Parent failed"),
        ):
            # Should raise exception but still cleanup
            with pytest.raises(Exception, match="Parent failed"):
                await connector._handle_non_streaming_response(
                    url="https://api.example.com",
                    payload=payload,
                    headers={},
                    session_id="test-session",
                )

            # Verify cleanup was still called
            mock_compat_layer.cleanup_state.assert_called_once_with(state)

    @pytest.mark.asyncio
    async def test_non_streaming_response_handles_missing_state(
        self,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
        mock_client,
    ) -> None:
        """Test that method handles missing compatibility state gracefully."""
        connector = OpenAICodexConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        mock_compat_layer = MagicMock(spec=CompatibilityLayer)
        connector._compatibility_layer = mock_compat_layer

        # Payload without compatibility state
        payload = {"messages": [{"role": "user", "content": "test"}]}

        mock_response = MagicMock()
        with patch.object(
            connector.__class__.__bases__[0],
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await connector._handle_non_streaming_response(
                url="https://api.example.com",
                payload=payload,
                headers={},
                session_id="test-session",
            )

            # Should not call cleanup_state if state is missing
            mock_compat_layer.cleanup_state.assert_not_called()
            assert result == mock_response

    def test_handle_non_streaming_response_is_async(self) -> None:
        """Test that _handle_non_streaming_response is async."""
        import inspect

        method = OpenAICodexConnector._handle_non_streaming_response
        assert inspect.iscoroutinefunction(
            method
        ), "_handle_non_streaming_response should be async"
