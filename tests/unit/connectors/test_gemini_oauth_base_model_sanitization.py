from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


# Concrete implementation for testing abstract base class
class ConcreteGeminiConnector(GeminiOAuthBaseConnector):
    async def _discover_project_id(self, auth_session):
        return "test-project"


class TestGeminiOAuthBaseModelSanitization:
    @pytest.fixture
    def connector(self):
        client = AsyncMock()
        config = AppConfig()
        translation_service = MagicMock(spec=TranslationService)
        return ConcreteGeminiConnector(
            client, config, translation_service, "test-connector"
        )

    def test_sanitize_model_name_internal(self, connector):
        """Test that internal model names are sanitized."""
        sanitized = connector._sanitize_model_name("code-assist-model")
        assert sanitized == "gemini-2.5-pro"

        sanitized = connector._sanitize_model_name("some-prefix/code-assist-model")
        assert sanitized == "gemini-2.5-pro"

    def test_sanitize_model_name_normal(self, connector):
        """Test that normal model names are preserved."""
        sanitized = connector._sanitize_model_name("gemini-1.5-pro")
        assert sanitized == "gemini-1.5-pro"

        sanitized = connector._sanitize_model_name("gemini-2.0-flash")
        assert sanitized == "gemini-2.0-flash"

    def test_sanitize_model_name_empty(self, connector):
        """Test handling of empty model names."""
        sanitized = connector._sanitize_model_name("")
        assert sanitized == "unknown"

        sanitized = connector._sanitize_model_name(None)
        assert sanitized == "unknown"

    def test_normalize_model_key(self, connector):
        """Test model key normalization."""
        assert connector._normalize_model_key("models/gemini-pro") == "gemini-pro"
        assert connector._normalize_model_key("gemini-pro") == "gemini-pro"
        assert connector._normalize_model_key("provider:gemini-pro") == "gemini-pro"
        assert connector._normalize_model_key("  gemini-pro  ") == "gemini-pro"
