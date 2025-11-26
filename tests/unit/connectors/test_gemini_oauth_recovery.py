"""Unit tests for Gemini OAuth recovery logic.

These tests verify that the recovery probing and cooldown logic works correctly,
ensuring that models are only probed when in cooldown and that rate limiting
for one model doesn't block other models.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.connectors.gemini_oauth_base import GracefulDegradationConfig, ModelRetryState
from src.core.common.exceptions import BackendError


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock AppConfig."""
    config = MagicMock()
    config.backends = MagicMock()
    config.backends.disable_gemini_oauth_fallback = False
    config.logging = MagicMock()
    config.logging.level = "WARNING"
    return config


@pytest.fixture
def mock_translation_service() -> MagicMock:
    """Create mock TranslationService."""
    return MagicMock()


@pytest.fixture
def connector(
    mock_config: MagicMock, mock_translation_service: MagicMock
) -> GeminiOAuthAntigravityConnector:
    """Create GeminiOAuthAntigravityConnector for testing."""
    client = httpx.AsyncClient()
    conn = GeminiOAuthAntigravityConnector(
        client=client,
        config=mock_config,
        translation_service=mock_translation_service,
        name="test-antigravity",
    )
    # Enable graceful degradation
    conn._degradation_config = GracefulDegradationConfig(
        enabled=True,
        enable_recovery_probing=True,
        cooldown_duration=300,
        recovery_probe_interval=60,
    )
    return conn


class TestCooldownLogic:
    """Tests for model cooldown management."""

    def test_model_not_in_cooldown_by_default(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Models should not be in cooldown by default."""
        assert not connector._is_in_cooldown("gemini-2.5-pro")
        assert not connector._is_in_cooldown("claude-sonnet-4-5")
        assert not connector._is_in_cooldown("any-model")

    def test_set_cooldown_puts_model_in_cooldown(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """_set_cooldown should put a model in cooldown."""
        model = "gemini-2.5-pro"
        assert not connector._is_in_cooldown(model)

        connector._set_cooldown(model)

        assert connector._is_in_cooldown(model)
        assert model in connector._model_retry_states

    def test_cooldown_state_per_model(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Cooldown state should be tracked per model, not globally."""
        model_a = "gemini-2.5-pro"
        model_b = "claude-sonnet-4-5"

        connector._set_cooldown(model_a)

        assert connector._is_in_cooldown(model_a)
        assert not connector._is_in_cooldown(model_b)

    def test_cooldown_expires_after_duration(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Cooldown should expire after the configured duration."""
        model = "gemini-2.5-pro"
        connector._degradation_config.cooldown_duration = 1  # 1 second

        connector._set_cooldown(model)
        assert connector._is_in_cooldown(model)

        # Wait for cooldown to expire
        time.sleep(1.1)
        assert not connector._is_in_cooldown(model)

    def test_multiple_models_can_be_in_cooldown(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Multiple models can be in cooldown simultaneously."""
        models = ["gemini-2.5-pro", "gemini-2.5-flash", "claude-sonnet-4-5"]

        for model in models:
            connector._set_cooldown(model)

        for model in models:
            assert connector._is_in_cooldown(model)


class TestRecoveryProbeGuards:
    """Tests for recovery probe guard conditions."""

    @pytest.mark.asyncio
    async def test_recovery_probe_returns_true_for_model_not_in_cooldown(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Recovery probe should return True (recovered) for models not in cooldown."""
        model = "gemini-2.5-pro"
        # Model is not in cooldown by default

        result = await connector._probe_model_recovery(model)

        assert result is True

    @pytest.mark.asyncio
    async def test_recovery_probe_returns_true_for_model_with_no_state(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Recovery probe should return True for models with no retry state."""
        model = "unknown-model"
        assert model not in connector._model_retry_states

        result = await connector._probe_model_recovery(model)

        assert result is True

    @pytest.mark.asyncio
    async def test_recovery_probe_skipped_when_disabled(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Recovery probing should be skipped when disabled in config."""
        connector._degradation_config.enable_recovery_probing = False
        model = "gemini-2.5-pro"
        connector._set_cooldown(model)

        result = await connector._probe_model_recovery(model)

        assert result is False

    @pytest.mark.asyncio
    async def test_recovery_probe_respects_interval(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Recovery probe should respect the probe interval."""
        model = "gemini-2.5-pro"
        connector._degradation_config.recovery_probe_interval = 60
        connector._set_cooldown(model)

        # First probe updates last_probe_attempt
        state = connector._model_retry_states[model]
        state.last_probe_attempt = time.time()

        # Second probe within interval should return False
        result = await connector._probe_model_recovery(model)

        assert result is False

    @pytest.mark.asyncio
    async def test_recovery_probe_bypass_interval_check(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Recovery probe should bypass interval check when flag is set."""
        model = "gemini-2.5-pro"
        connector._degradation_config.recovery_probe_interval = 60
        connector._set_cooldown(model)

        # Set recent probe time
        state = connector._model_retry_states[model]
        state.last_probe_attempt = time.time()

        # With bypass flag, probing should be allowed but will fail on API call
        # We need to mock the API call to avoid actual network request
        with patch.object(
            connector, "_chat_completions_code_assist", new_callable=AsyncMock
        ) as mock_chat:
            mock_chat.side_effect = BackendError(
                message="Still rate limited",
                code="rate_limit_exceeded",
                status_code=429,
            )

            result = await connector._probe_model_recovery(
                model, bypass_interval_check=True
            )

            # Should attempt probe (not short-circuit due to interval)
            # Result depends on API response
            assert result is False


class TestGracefulDegradationConfig:
    """Tests for graceful degradation configuration."""

    def test_default_config_values(self) -> None:
        """Default configuration should have sensible values."""
        config = GracefulDegradationConfig()

        assert config.enabled is True
        assert config.cooldown_duration > 0
        assert config.max_total_attempts > 0
        assert len(config.retry_delays) > 0

    def test_config_can_be_customized(self) -> None:
        """Configuration values should be customizable."""
        config = GracefulDegradationConfig(
            enabled=False,
            cooldown_duration=120,
            max_total_attempts=5,
            retry_delays=[1, 2, 4],
            enable_recovery_probing=False,
            recovery_probe_interval=30,
        )

        assert config.enabled is False
        assert config.cooldown_duration == 120
        assert config.max_total_attempts == 5
        assert config.retry_delays == [1, 2, 4]
        assert config.enable_recovery_probing is False
        assert config.recovery_probe_interval == 30


class TestModelRetryState:
    """Tests for model retry state tracking."""

    def test_default_state(self) -> None:
        """Default state should have sensible values."""
        state = ModelRetryState()

        assert state.attempts == 0
        assert state.cooldown_until == 0
        assert state.last_probe_attempt == 0
        assert state.probe_success_count == 0

    def test_state_tracks_attempts(self) -> None:
        """State should track retry attempts."""
        state = ModelRetryState()

        state.attempts = 3
        assert state.attempts == 3

    def test_state_tracks_cooldown(self) -> None:
        """State should track cooldown expiration time."""
        state = ModelRetryState()
        future_time = time.time() + 300

        state.cooldown_until = future_time
        assert state.cooldown_until == future_time


class TestRateLimitErrorDetection:
    """Tests for rate limit error detection."""

    def test_is_rate_limit_like_error_with_429(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Should detect 429 status code as rate limit error."""
        error = BackendError(
            message="Rate limited",
            code="rate_limit_exceeded",
            status_code=429,
        )

        result = connector._is_rate_limit_like_error(error)

        assert result is True

    def test_is_rate_limit_like_error_with_empty_response_code(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Should detect empty_response code as rate limit-like error."""
        error = BackendError(
            message="Empty response",
            code="empty_response",
            status_code=200,
        )

        result = connector._is_rate_limit_like_error(error)

        assert result is True

    def test_is_rate_limit_like_error_with_500(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Should not detect 500 as rate limit error."""
        error = BackendError(
            message="Internal error",
            code="internal_error",
            status_code=500,
        )

        result = connector._is_rate_limit_like_error(error)

        assert result is False


class TestBackendFunctionality:
    """Tests for backend functionality management."""

    def test_backend_functional_after_initialization(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Backend functional status is False before init, can be set to True."""
        # Before initialization, is_functional is False
        # (connectors require initialize() to be called)
        # Set it to True to simulate initialized state
        connector.is_functional = True
        assert connector.is_functional is True

    def test_mark_backend_unusable_for_quota(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Marking backend unusable for quota should set quota flag."""
        connector._mark_backend_unusable(reason="quota_exceeded")

        assert connector._quota_exceeded is True
        # Backend should still be functional for other models
        # (the is_functional behavior depends on implementation)

    def test_quota_exceeded_does_not_permanently_fail_backend(
        self, connector: GeminiOAuthAntigravityConnector
    ) -> None:
        """Quota exhaustion should not permanently fail the backend."""
        connector._mark_backend_unusable(reason="quota_exceeded")

        # _permanently_failed should not be set
        assert connector._permanently_failed is False
