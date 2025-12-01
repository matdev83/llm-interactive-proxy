from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
from src.connectors.gemini_base.graceful_degradation import (
    DEFAULT_FALLBACK_MAP,
    GracefulDegradationManager,
    get_fallback_model,
)
from src.core.common.exceptions import BackendError


class TestGeminiFallbackLogic:
    def test_default_fallback_map_structure(self):
        """Test that the default fallback map has the correct structure."""
        assert "gemini-3-pro" in DEFAULT_FALLBACK_MAP
        assert DEFAULT_FALLBACK_MAP["gemini-3-pro"] == [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]
        assert DEFAULT_FALLBACK_MAP["gemini-3-pro-high"] == [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]
        assert DEFAULT_FALLBACK_MAP["gemini-2.5-pro"] == "gemini-2.5-flash"

    def test_get_fallback_model_returns_list(self):
        """Test that get_fallback_model returns a list for gemini-3-pro."""
        fallback = get_fallback_model("gemini-3-pro")
        assert isinstance(fallback, list)
        assert fallback == ["gemini-2.5-pro", "gemini-2.5-flash"]

    def test_manager_get_models_to_try_with_list(self):
        """Test that GracefulDegradationManager expands list fallbacks."""
        manager = GracefulDegradationManager(MagicMock())
        models = manager.get_models_to_try("gemini-3-pro")
        assert models == ["gemini-3-pro", "gemini-2.5-pro", "gemini-2.5-flash"]

    def test_manager_get_models_to_try_with_string(self):
        """Test that GracefulDegradationManager handles string fallbacks."""
        manager = GracefulDegradationManager(MagicMock())
        models = manager.get_models_to_try("gemini-2.5-pro")
        assert models == ["gemini-2.5-pro", "gemini-2.5-flash"]

    @pytest.mark.asyncio
    async def test_connector_handle_429_fallback_chain(self):
        """Test that the connector tries the fallback chain in order."""

        # Define a concrete subclass for testing
        class TestConnector(GeminiOAuthBaseConnector):
            async def _discover_project_id(self, auth_session):
                return "test-project"

        # Mock the connector and its dependencies
        connector = TestConnector(
            client=AsyncMock(),
            config=MagicMock(),
            translation_service=MagicMock(),
            name="test-connector",
        )
        connector._degradation_config = MagicMock()
        connector._degradation_config.enabled = True
        connector._degradation_config.retry_delays = [0.1]
        connector._degradation_config.max_total_attempts = 10
        connector._degradation_config.enable_recovery_probing = False
        connector.config.backends.disable_gemini_oauth_fallback = False

        # Mock _chat_completions_code_assist to fail for first two models and succeed for third
        connector._chat_completions_code_assist = AsyncMock()

        # Setup side effects for the mock
        # 1. gemini-3-pro (original) -> fails
        # 2. gemini-2.5-pro (fallback 1) -> fails
        # 3. gemini-2.5-flash (fallback 2) -> succeeds

        async def side_effect(
            request_data, processed_messages, effective_model, **kwargs
        ):
            if effective_model == "gemini-3-pro":
                raise BackendError(message="Rate limit", status_code=429)
            if effective_model == "gemini-2.5-pro":
                raise BackendError(message="Rate limit", status_code=429)
            if effective_model == "gemini-2.5-flash":
                return "Success"
            raise ValueError(f"Unexpected model: {effective_model}")

        connector._chat_completions_code_assist.side_effect = side_effect

        # Call the method
        result = await connector._handle_429_with_graceful_degradation(
            original_model="gemini-3-pro",
            request_data={},
            processed_messages=[],
        )

        assert result == "Success"

        # Verify call order
        calls = connector._chat_completions_code_assist.call_args_list
        models_called = [call.kwargs["effective_model"] for call in calls]

        # We expect retries for each model based on retry_delays (1 retry -> 2 attempts per model)
        # But wait, logic says:
        # if model == original_model and fallback_model: max_attempts_for_model = 1
        # So gemini-3-pro should be tried 1 time (since it failed initially to get here? No, this method IS the retry logic)
        # Actually _handle_429 is called AFTER the first failure.
        # Inside _handle_429:
        # models_to_try = [original, fallback1, fallback2]
        # For original: max_attempts = 1 (because fallback exists)
        # For fallbacks: max_attempts = len(retry_delays) + 1 = 2

        # Expected sequence:
        # 1. gemini-3-pro (1 attempt)
        # 2. gemini-2.5-pro (2 attempts)
        # 3. gemini-2.5-flash (1 attempt, succeeds)

        # Wait, my side effect raises 429 for 2.5-pro every time.
        # So:
        # 1. gemini-3-pro (fails)
        # 2. gemini-2.5-pro (attempt 1 fails)
        # 3. gemini-2.5-pro (attempt 2 fails)
        # 4. gemini-2.5-flash (attempt 1 succeeds)

        assert models_called[0] == "gemini-3-pro"
        assert models_called[1] == "gemini-2.5-pro"
        assert models_called[2] == "gemini-2.5-pro"
        assert models_called[3] == "gemini-2.5-flash"
