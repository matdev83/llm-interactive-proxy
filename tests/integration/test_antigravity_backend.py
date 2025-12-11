"""Integration tests for the Antigravity backend connector.

These tests verify that the gemini-oauth-antigravity backend works correctly,
including graceful degradation when quota is exhausted.
"""

import httpx
import pytest
from src.connectors.gemini_oauth_antigravity import GeminiOAuthAntigravityConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService

pytestmark = pytest.mark.integration


@pytest.fixture
def config():
    """Provide test configuration."""
    return AppConfig()


@pytest.fixture
def translation_service():
    """Provide translation service."""
    return TranslationService()


@pytest.fixture
async def connector(config, translation_service):
    """Create and initialize the Antigravity connector."""
    async with httpx.AsyncClient() as client:
        conn = GeminiOAuthAntigravityConnector(
            client=client,
            config=config,
            translation_service=translation_service,
            name="test-antigravity",
        )
        # Mock credential loading to avoid actual file access
        conn._oauth_credentials = {
            "access_token": "test-token",
            "expiry_date": 9999999999999,  # Far future
        }
        conn._credentials_path = "test/path"
        conn.is_functional = True
        yield conn


class TestAntigravityBackendFunctionality:
    """Test that the Antigravity backend connector is functional."""

    @pytest.mark.asyncio
    async def test_connector_initializes_successfully(
        self, config, translation_service
    ):
        """Verify that the connector can be created with required parameters."""
        from src.connectors.gemini_oauth_antigravity import ANTIGRAVITY_SANDBOX_ENDPOINT

        async with httpx.AsyncClient() as client:
            conn = GeminiOAuthAntigravityConnector(
                client=client,
                config=config,
                translation_service=translation_service,
            )
            assert conn.backend_type == "gemini-oauth-antigravity"
            # Verify the module constant for the sandbox endpoint
            assert (
                ANTIGRAVITY_SANDBOX_ENDPOINT
                == "https://daily-cloudcode-pa.sandbox.googleapis.com"
            )

    @pytest.mark.asyncio
    async def test_antigravity_specific_user_agent(self, connector):
        """Verify that Antigravity connector uses the correct User-Agent."""
        headers = connector._get_api_headers()
        assert "User-Agent" in headers
        assert "antigravity/" in headers["User-Agent"]

    @pytest.mark.asyncio
    async def test_antigravity_session_headers(self, connector):
        """Verify that session headers include the Antigravity User-Agent."""
        headers = connector._get_session_headers()
        assert "User-Agent" in headers
        assert "antigravity/" in headers["User-Agent"]


class TestAntigravityGracefulDegradation:
    """Test graceful degradation behavior for quota-exhausted models."""

    @pytest.mark.asyncio
    async def test_quota_exhaustion_triggers_cooldown(self, connector):
        """When a model returns 429, it should be put in cooldown."""
        # Simulate a 429 error
        connector._set_cooldown("gemini-2.5-pro")

        assert connector._is_in_cooldown("gemini-2.5-pro")
        assert not connector._is_in_cooldown("gemini-2.5-flash")

    @pytest.mark.asyncio
    async def test_other_models_not_affected_by_quota(self, connector):
        """Quota exhaustion on one model should not affect others."""
        connector._set_cooldown("gemini-2.5-pro")

        # Other models should work fine
        assert not connector._is_in_cooldown("gemini-2.5-flash")
        assert not connector._is_in_cooldown("claude-sonnet-4-5")
        assert connector.is_functional  # Backend itself is still functional

    @pytest.mark.asyncio
    async def test_backend_remains_functional_after_quota_error(self, connector):
        """Backend should remain functional even after quota errors."""
        # Simulate quota exhaustion
        connector._mark_backend_unusable(reason="quota_exceeded")

        # Backend should still be functional for other models
        assert connector.is_functional
        assert connector._quota_exceeded  # But quota flag is set


class TestAntigravityErrorHandling:
    """Test error handling and propagation."""

    @pytest.mark.asyncio
    async def test_error_chunks_contain_error_field(self, connector):
        """Error chunks should contain the error field for client visibility."""
        from src.core.ports.streaming_contracts import StreamingContent

        error_content = StreamingContent(
            content={"error": {"message": "Quota exhausted", "code": 429}},
            metadata={
                "finish_reason": "error",
                "error": {"message": "Quota exhausted"},
            },
            is_done=True,
        )

        # The error should be accessible
        assert error_content.metadata.get("error") is not None
        assert error_content.metadata["error"]["message"] == "Quota exhausted"

    @pytest.mark.asyncio
    async def test_rate_limit_error_detection(self, connector):
        """Rate limit errors should be properly detected."""
        error_429 = BackendError("Rate limit exceeded", status_code=429)
        error_500 = BackendError("Server error", status_code=500)

        assert connector._is_rate_limit_like_error(error_429)
        assert not connector._is_rate_limit_like_error(error_500)


class TestAntigravityRequestBodyFormat:
    """Test that request body is formatted correctly for Antigravity sandbox."""

    @pytest.mark.asyncio
    async def test_build_code_assist_request_body_structure(self, connector):
        """Verify the request body has the correct Antigravity-specific structure."""
        request = ChatRequest(
            model="gemini-2.5-flash",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
            max_tokens=100,
        )

        # Build the inner code assist request structure
        code_assist_request = {
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
            "generationConfig": {"maxOutputTokens": 100},
        }

        body = connector._build_code_assist_request_body(
            effective_model="gemini-2.5-flash",
            project_id="test-project",
            request_data=request,
            code_assist_request=code_assist_request,
        )

        # Antigravity format should have model at top level
        assert "model" in body
        assert body["model"] == "gemini-2.5-flash"

        # Should have requestId and userAgent
        assert "requestId" in body
        assert "userAgent" in body

        # Should have requestType
        assert "requestType" in body


class TestAntigravityRecoveryProbes:
    """Test recovery probe behavior."""

    @pytest.mark.asyncio
    async def test_recovery_probe_only_for_cooldown_models(self, connector):
        """Recovery probes should only run for models in cooldown."""
        # Model not in cooldown - probe should return True immediately
        result = await connector._probe_model_recovery("gemini-2.5-flash")
        assert result is True  # Not in cooldown, nothing to recover

    @pytest.mark.asyncio
    async def test_model_in_cooldown_needs_probe(self, connector):
        """Models in cooldown should require recovery probes."""
        connector._set_cooldown("gemini-2.5-pro")

        assert connector._is_in_cooldown("gemini-2.5-pro")
        # Recovery probe will try to make an API call - we just verify the state
        assert "gemini-2.5-pro" in connector._graceful_degradation.model_retry_states


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
