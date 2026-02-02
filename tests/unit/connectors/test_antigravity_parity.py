"""
Tests for Antigravity OAuth connector account block handling and feature parity.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import BackendError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


@pytest.fixture
def mock_client():
    return MagicMock()

@pytest.fixture
def connector(mock_client):
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService
    
    config = AppConfig()
    translation_service = TranslationService()
    conn = AntigravityOAuthConnector(mock_client, config, translation_service)
    # Enable debugging override to bypass chat_completions check
    conn._enable_antigravity_backend_debugging_override = True
    return conn

class TestAntigravityParity:
    """Test parity features in Antigravity connector."""

    def test_account_block_message_detection(self, connector):
        """Should detect account block messages."""
        msg = "To continue, validate your account"
        assert connector._is_account_blocked_message(msg, status_code=403) is True
        
        msg = "Account suspended" # Marker is "account suspended" or "account is suspended"
        assert connector._is_account_blocked_message(msg, status_code=403) is True
        
        # Non-403 status should not be blocked
        assert connector._is_account_blocked_message(msg, status_code=429) is False
        
        # Normal 403 (e.g. invalid key) without block marker should not be blocked
        assert connector._is_account_blocked_message("Forbidden", status_code=403) is False

    @pytest.mark.asyncio
    async def test_chat_completions_handles_account_block(self, connector):
        """Should mark backend unusable and set resilience context on account block."""
        block_msg = "To continue, validate your account"
        error = BackendError(message=block_msg, status_code=403)
        
        # Mock super().chat_completions to raise the error
        with patch("src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions", side_effect=error):
            # Mock _ensure_models_loaded to skip initialization
            connector._ensure_models_loaded = AsyncMock()
            connector.mark_auth_invalid = MagicMock()
            
            request = ConnectorChatCompletionsRequest(
                request=CanonicalChatRequest(model="google/gemini-3-pro", messages=[ChatMessage(role="user", content="hi")]),
                processed_messages=[],
                effective_model="google/gemini-3-pro",
                options={},
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None
            )
            
            with pytest.raises(BackendError) as exc_info:
                await connector.chat_completions(request)
            
            # Verify backend was disabled
            connector.mark_auth_invalid.assert_called_with(block_msg)
            
            # Verify resilience context was set
            assert getattr(exc_info.value, "__resilience_context__", {}).get("is_personal_backend") is True

    def test_extract_retry_after_seconds(self, connector):
        """Should extract retry_after from error details."""
        error = BackendError("Rate limit", details={"retry_after": 30.5})
        assert connector._extract_retry_after_seconds(error) == 30.5
        
        error = BackendError("Other error")
        assert connector._extract_retry_after_seconds(error) is None

    @pytest.mark.asyncio
    async def test_chat_completions_logic_amplification_protection(self, connector):
        """Should prevent redundant rate limit recording via flag."""
        error = BackendError("Rate limit", status_code=429, details={"retry_after": 10})
        
        with patch("src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions", side_effect=error):
            connector._ensure_models_loaded = AsyncMock()
            connector.record_rate_limit = AsyncMock()
            
            request = ConnectorChatCompletionsRequest(
                request=CanonicalChatRequest(model="google/gemini-3-pro", messages=[ChatMessage(role="user", content="hi")]),
                processed_messages=[],
                effective_model="google/gemini-3-pro",
                options={},
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None
            )
            
            with pytest.raises(BackendError) as exc_info:
                await connector.chat_completions(request)
            
            # Verify record_rate_limit was called
            connector.record_rate_limit.assert_called_once()
            
            # Verify flag is set on error object
            assert exc_info.value.__rate_limit_recorded__ is True
            
            # Second call with SAME error object (re-raised) should NOT call record_rate_limit again
            connector.record_rate_limit.reset_mock()
            with patch("src.connectors.gemini_oauth_base.GeminiOAuthBaseConnector.chat_completions", side_effect=exc_info.value):
                with pytest.raises(BackendError):
                    await connector.chat_completions(request)
                connector.record_rate_limit.assert_not_called()
