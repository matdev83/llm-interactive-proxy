"""Tests for disable_gemini_oauth_fallback behavior in graceful degradation."""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.connectors.gemini_oauth_base import (
    GeminiOAuthBaseConnector,
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
    ModelRetryState,
)
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig


@dataclass
class MockRequest:
    """Mock request object for testing."""

    model: str
    messages: list[dict[str, str]]
    stream: bool = False
    max_tokens: int = 100
    temperature: float = 0.0


class MockGeminiOAuthConnector(GeminiOAuthBaseConnector):
    """Mock Gemini OAuth connector for testing disable_gemini_oauth_fallback."""

    def __init__(self, config: AppConfig | None = None):
        """Initialize with optional config override."""
        from src.connectors.gemini_base.file_watcher import FileWatcherState
        from src.connectors.gemini_base.token_manager import TokenManager

        if config is None:
            config = AppConfig.from_env()

        # Initialize composed managers FIRST (before setting properties that delegate to them)
        self._token_manager = TokenManager()
        self._file_watcher_state = FileWatcherState()

        # Initialize with minimal required components
        self.config = config
        self.name = "test-connector"
        self.is_functional = True
        self._oauth_credentials = {"access_token": "test-token"}
        self._credentials_path = None
        self._last_modified = 0
        self._refresh_token = None
        self.translation_service = MagicMock()
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._main_loop = None
        self._quota_exceeded = False
        self._request_counter = None
        self._health_checked = True

        # Initialize graceful degradation
        self._degradation_config = GracefulDegradationConfig.from_config(self.config)
        self._model_retry_states: dict[str, ModelRetryState] = {}
        self._total_attempts = 0
        self._permanently_failed = False
        self._recovery_probe_task = None

        # Mock API call behavior
        self._api_call_results: dict[str, list[Any]] = {}
        self._api_call_count: dict[str, int] = {}
        self._graceful_metrics = GracefulDegradationMetrics()

    def set_api_behavior(self, model: str, results: list[Any]) -> None:
        """Configure mock API behavior for a model."""
        self._api_call_results[model] = results.copy()
        self._api_call_count[model] = 0

    async def _chat_completions_code_assist(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _in_graceful_degradation: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Mock API call that returns configured results."""
        call_count = self._api_call_count.get(effective_model, 0)
        results = self._api_call_results.get(effective_model, [])

        self._api_call_count[effective_model] = call_count + 1

        if call_count < len(results):
            result = results[call_count]
            if isinstance(result, Exception):
                raise result
            return result  # type: ignore[no-any-return]

        # If no more configured results, raise the last error if it was an exception
        if results and isinstance(results[-1], Exception):
            raise results[-1]

        # Otherwise raise a generic error
        raise BackendError(f"No more results configured for {effective_model}")

    async def _discover_project_id(self, auth_session: Any) -> str:
        """Mock project ID discovery."""
        return "test-project"


class TestDisableGeminiOAuthFallbackBehavior:
    """Test graceful degradation behavior with disable_gemini_oauth_fallback flag."""

    @staticmethod
    def _configure_fast_degradation(
        connector: MockGeminiOAuthConnector,
    ) -> MockGeminiOAuthConnector:
        """Configure connector to degrade quickly without background probing."""
        connector._degradation_config = GracefulDegradationConfig(
            enabled=True,
            retry_delays=[0.0, 0.0],
            max_total_attempts=20,
            cooldown_duration=0.0,
            enable_recovery_probing=False,
            recovery_probe_interval=3600.0,
        )
        return connector

    @pytest.fixture
    def config_with_fallback_disabled(self) -> AppConfig:
        """Create config with fallback disabled."""
        cfg = AppConfig.from_env()
        cfg.backends.disable_gemini_oauth_fallback = True
        return cfg

    @pytest.fixture
    def config_with_fallback_enabled(self) -> AppConfig:
        """Create config with fallback enabled (default)."""
        cfg = AppConfig.from_env()
        cfg.backends.disable_gemini_oauth_fallback = False
        return cfg

    @pytest.fixture
    def connector_fallback_disabled(
        self, config_with_fallback_disabled: AppConfig
    ) -> MockGeminiOAuthConnector:
        """Create connector with fallback disabled."""
        connector = MockGeminiOAuthConnector(config_with_fallback_disabled)
        return self._configure_fast_degradation(connector)

    @pytest.fixture
    def connector_fallback_enabled(
        self, config_with_fallback_enabled: AppConfig
    ) -> MockGeminiOAuthConnector:
        """Create connector with fallback enabled."""
        connector = MockGeminiOAuthConnector(config_with_fallback_enabled)
        return self._configure_fast_degradation(connector)

    @pytest.fixture
    def mock_request(self) -> MockRequest:
        """Create a mock chat request."""
        return MockRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "Hello"}],
            stream=False,
        )

    @pytest.mark.asyncio
    async def test_fallback_disabled_no_flash_attempt(
        self,
        connector_fallback_disabled: MockGeminiOAuthConnector,
        mock_request: MockRequest,
    ):
        """Test that with fallback disabled, flash model is NOT attempted."""
        # Setup: Pro model always fails
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector_fallback_disabled.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, error_429]
        )

        # Don't configure flash model behavior - it should never be called

        # Execute: Expect failure after pro model retries
        with pytest.raises(BackendError) as exc_info:
            await connector_fallback_disabled.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Pro model attempts match retry configuration, flash not used
        pro_attempts = connector_fallback_disabled._api_call_count["gemini-2.5-pro"]
        delay_count = len(connector_fallback_disabled._degradation_config.retry_delays)
        expected_attempts = delay_count + 2  # initial call plus configured retries
        assert (
            pro_attempts == expected_attempts
        ), f"Expected {expected_attempts} pro attempts, observed {pro_attempts}"
        assert "gemini-2.5-flash" not in connector_fallback_disabled._api_call_count

        # Verify: Backend marked unusable with explanatory error
        error = exc_info.value
        assert getattr(error, "code", None) == "all_models_exhausted"
        assert "all models exhausted" in str(error).lower()
        assert connector_fallback_disabled._permanently_failed is True
        assert connector_fallback_disabled.is_functional is False

        # Cleanup
        if (
            connector_fallback_disabled._recovery_probe_task
            and not connector_fallback_disabled._recovery_probe_task.done()
        ):
            connector_fallback_disabled._recovery_probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connector_fallback_disabled._recovery_probe_task

    @pytest.mark.asyncio
    async def test_fallback_enabled_attempts_flash(
        self,
        connector_fallback_enabled: MockGeminiOAuthConnector,
        mock_request: MockRequest,
    ):
        """Test that with fallback enabled, flash model IS attempted after pro fails."""
        # Setup: Pro fails, Flash succeeds
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector_fallback_enabled.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429]
        )
        connector_fallback_enabled.set_api_behavior(
            "gemini-2.5-flash", [{"success": True, "model": "gemini-2.5-flash"}]
        )

        # Execute: Should succeed using flash fallback
        result = await connector_fallback_enabled.chat_completions(
            request_data=mock_request,
            processed_messages=mock_request.messages,
            effective_model="gemini-2.5-pro",
        )

        # Verify: Both models were attempted
        assert connector_fallback_enabled._api_call_count["gemini-2.5-pro"] == 2
        assert connector_fallback_enabled._api_call_count["gemini-2.5-flash"] >= 1

        # Verify: Request succeeded
        assert result is not None

        # Cleanup
        if (
            connector_fallback_enabled._recovery_probe_task
            and not connector_fallback_enabled._recovery_probe_task.done()
        ):
            connector_fallback_enabled._recovery_probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connector_fallback_enabled._recovery_probe_task

    @pytest.mark.asyncio
    async def test_fallback_disabled_faster_failure(
        self,
        connector_fallback_disabled: MockGeminiOAuthConnector,
        mock_request: MockRequest,
    ):
        """Test that with fallback disabled, failure occurs faster (no flash attempt)."""
        # Setup: Pro model always fails
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector_fallback_disabled.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429, error_429]
        )

        start_time = time.time()

        # Execute: Expect failure
        with pytest.raises(BackendError) as exc_info:
            await connector_fallback_disabled.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        elapsed = time.time() - start_time

        # Verify: Failure happens with configured retries (no fallback)
        # Initial 2s delay + retry delays to prevent burst rate limiting
        assert elapsed < 6.0

        # Verify: Error indicates exhaustion without fallback
        error = exc_info.value
        assert getattr(error, "code", None) == "all_models_exhausted"
        assert "all models exhausted" in str(error).lower()
        assert "gemini-2.5-flash" not in connector_fallback_disabled._api_call_count

        # Cleanup
        if (
            connector_fallback_disabled._recovery_probe_task
            and not connector_fallback_disabled._recovery_probe_task.done()
        ):
            connector_fallback_disabled._recovery_probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connector_fallback_disabled._recovery_probe_task

    @pytest.mark.asyncio
    async def test_fallback_enabled_with_both_models_failing(
        self,
        connector_fallback_enabled: MockGeminiOAuthConnector,
        mock_request: MockRequest,
    ):
        """Test that with fallback enabled, both models are tried before final failure."""
        # Setup: Both models fail
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        connector_fallback_enabled.set_api_behavior(
            "gemini-2.5-pro", [error_429, error_429, error_429]
        )
        connector_fallback_enabled.set_api_behavior(
            "gemini-2.5-flash", [error_429, error_429, error_429, error_429]
        )

        # Execute: Expect final failure
        with pytest.raises(BackendError):
            await connector_fallback_enabled.chat_completions(
                request_data=mock_request,
                processed_messages=mock_request.messages,
                effective_model="gemini-2.5-pro",
            )

        # Verify: Both models were attempted
        assert connector_fallback_enabled._api_call_count["gemini-2.5-pro"] == 2
        assert connector_fallback_enabled._api_call_count["gemini-2.5-flash"] >= 1

        # Cleanup
        if (
            connector_fallback_enabled._recovery_probe_task
            and not connector_fallback_enabled._recovery_probe_task.done()
        ):
            connector_fallback_enabled._recovery_probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connector_fallback_enabled._recovery_probe_task
