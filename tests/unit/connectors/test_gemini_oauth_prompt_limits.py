"""Unit tests for Gemini OAuth prompt limit configuration.

These tests verify that prompt limits are correctly configured for different
model families (Claude, Gemini, etc.) to prevent invalid 502 errors.
"""

from unittest.mock import MagicMock

import httpx
import pytest
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.connectors.gemini_oauth_base import (
    CODE_ASSIST_PROMPT_LIMIT_MARGIN,
    DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
    GeminiOAuthBaseConnector,
)
from src.connectors.gemini_oauth_free import GeminiOAuthFreeConnector
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_client() -> httpx.AsyncClient:
    """Create a mock httpx client."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_config() -> AppConfig:
    """Create a mock app config."""
    config = MagicMock(spec=AppConfig)
    config.context_window_override = None
    return config


@pytest.fixture
def mock_translation_service() -> TranslationService:
    """Create a mock translation service."""
    return MagicMock(spec=TranslationService)


class TestPromptLimitConfiguration:
    """Tests for prompt limit configuration on OAuth connectors."""

    def test_base_connector_has_claude_prefix_override(self) -> None:
        """Verify base connector has Claude prefix override defined."""
        # Claude models have 200K context windows
        assert len(GeminiOAuthBaseConnector.prompt_limit_prefix_overrides) > 0

        prefixes = dict(GeminiOAuthBaseConnector.prompt_limit_prefix_overrides)
        assert "claude" in prefixes
        assert prefixes["claude"] == 200_000

    def test_plan_connector_has_gemini_prefix_override(self) -> None:
        """Verify plan connector has Gemini 2.5 prefix override."""
        prefixes = dict(GeminiOAuthPlanConnector.prompt_limit_prefix_overrides)
        assert "gemini-2.5" in prefixes
        assert prefixes["gemini-2.5"] == 1_000_000

    def test_default_limit_is_65k(self) -> None:
        """Verify the default prompt limit is 65,536 tokens."""
        assert DEFAULT_CODE_ASSIST_PROMPT_LIMIT == 65_536

    def test_prompt_limit_margin_is_97_percent(self) -> None:
        """Verify the soft limit margin is 97%."""
        assert CODE_ASSIST_PROMPT_LIMIT_MARGIN == 0.97


class TestPromptLimitResolution:
    """Tests for _get_prompt_limit method."""

    def test_claude_model_gets_200k_limit(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify Claude models get the 200K limit from prefix overrides."""
        connector = GeminiOAuthFreeConnector(
            mock_client, mock_config, mock_translation_service
        )

        # Test various Claude model names
        claude_models = [
            "claude-sonnet-4-5",
            "claude-3-5-sonnet",
            "claude-3-opus",
            "claude-instant",
        ]

        for model in claude_models:
            limit = connector._get_prompt_limit(model)
            assert limit == 200_000, f"Expected 200K limit for {model}, got {limit}"

    def test_non_prefixed_model_gets_default_limit(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify models without prefix override get the default limit."""
        connector = GeminiOAuthFreeConnector(
            mock_client, mock_config, mock_translation_service
        )

        # Models without specific overrides should get the default
        limit = connector._get_prompt_limit("some-other-model")
        assert limit == DEFAULT_CODE_ASSIST_PROMPT_LIMIT

    def test_plan_connector_gemini_25_gets_1m_limit(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify Gemini 2.5 models get 1M limit on plan connector."""
        connector = GeminiOAuthPlanConnector(
            mock_client, mock_config, mock_translation_service
        )

        gemini_25_models = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]

        for model in gemini_25_models:
            limit = connector._get_prompt_limit(model)
            assert limit == 1_000_000, f"Expected 1M limit for {model}, got {limit}"

    def test_antigravity_connector_claude_gets_200k_limit(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify Antigravity connector also respects Claude 200K limit."""
        connector = GeminiOAuthAntigravityConnector(
            mock_client, mock_config, mock_translation_service
        )

        limit = connector._get_prompt_limit("claude-sonnet-4-5")
        assert limit == 200_000

    def test_normalize_model_key_strips_prefix(self) -> None:
        """Verify model normalization strips backend prefixes."""
        normalized = GeminiOAuthBaseConnector._normalize_model_key(
            "gemini-oauth-antigravity:claude-sonnet-4-5"
        )
        assert normalized == "claude-sonnet-4-5"

    def test_normalize_model_key_handles_models_slash(self) -> None:
        """Verify model normalization handles models/ prefix."""
        normalized = GeminiOAuthBaseConnector._normalize_model_key(
            "models/claude-sonnet-4-5"
        )
        assert normalized == "claude-sonnet-4-5"

    def test_context_window_override_takes_precedence(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify context_window_override in config can reduce the limit."""
        mock_config.context_window_override = 50_000  # Lower than default

        connector = GeminiOAuthFreeConnector(
            mock_client, mock_config, mock_translation_service
        )

        # For Claude, the override should cap it at 50K (min of 200K and 50K)
        limit = connector._get_prompt_limit("claude-sonnet-4-5")
        assert limit == 50_000


class TestPromptLimitEnforcement:
    """Tests for _enforce_prompt_limit method."""

    def test_enforce_allows_request_under_limit(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify requests under the limit are not blocked."""
        connector = GeminiOAuthFreeConnector(
            mock_client, mock_config, mock_translation_service
        )

        # 78K tokens should be allowed for Claude (200K limit)
        # This is the exact scenario from the bug report
        connector._enforce_prompt_limit(78044, "claude-sonnet-4-5")
        # Should not raise

    def test_enforce_blocks_request_over_limit(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify requests over the limit are blocked."""
        from src.core.common.exceptions import InvalidRequestError

        connector = GeminiOAuthFreeConnector(
            mock_client, mock_config, mock_translation_service
        )

        # 250K tokens should be blocked for Claude (200K limit)
        with pytest.raises(InvalidRequestError) as exc_info:
            connector._enforce_prompt_limit(250_000, "claude-sonnet-4-5")

        assert "exceeds" in str(exc_info.value.message).lower()

    def test_enforce_respects_soft_limit_margin(
        self,
        mock_client: httpx.AsyncClient,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
    ) -> None:
        """Verify the 97% soft limit margin is applied."""
        from src.core.common.exceptions import InvalidRequestError

        connector = GeminiOAuthFreeConnector(
            mock_client, mock_config, mock_translation_service
        )

        # 200K * 0.97 = 194K soft limit for Claude
        # 193K should be allowed
        connector._enforce_prompt_limit(193_000, "claude-sonnet-4-5")
        # Should not raise

        # 195K should be blocked (over 194K soft limit)
        with pytest.raises(InvalidRequestError):
            connector._enforce_prompt_limit(195_000, "claude-sonnet-4-5")
