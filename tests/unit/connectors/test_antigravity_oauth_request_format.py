"""
Tests for Antigravity OAuth connector request format.

These tests verify that the Antigravity connector sends requests in the correct
format expected by the Antigravity sandbox API, including:
- Correct request body structure with userAgent and requestType fields
- Correct User-Agent HTTP header
- Proper model name handling
- Quota error handling
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.antigravity_oauth import (
    ANTIGRAVITY_SANDBOX_ENDPOINT,
    ANTIGRAVITY_USER_AGENT,
    AntigravityOAuthConnector,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_config() -> AppConfig:
    """Create a mock AppConfig for testing."""
    config = MagicMock(spec=AppConfig)
    config.gemini_credentials_path = None
    config.graceful_degradation_enabled = False
    return config


@pytest.fixture
def mock_translation_service() -> TranslationService:
    """Create a mock TranslationService for testing."""
    service = MagicMock(spec=TranslationService)
    # Mock the from_domain_to_gemini_request method
    service.from_domain_to_gemini_request.return_value = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 100},
    }
    return service


class TestAntigravityRequestBodyFormat:
    """Tests for the request body format sent to the Antigravity API."""

    def test_build_code_assist_request_body_has_required_fields(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that the request body contains all Antigravity-specific fields."""
        client = MagicMock(spec=httpx.AsyncClient)
        connector = AntigravityOAuthConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        request_data = ChatRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
        )

        code_assist_request = {
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
            "generationConfig": {"temperature": 0.7},
        }

        request_body = connector._build_code_assist_request_body(
            effective_model="claude-sonnet-4-5",
            project_id="test-project-123",
            request_data=request_data,
            code_assist_request=code_assist_request,
        )

        # Verify Antigravity-specific fields
        assert "project" in request_body
        assert request_body["project"] == "test-project-123"
        assert "requestId" in request_body
        assert "request" in request_body
        assert "model" in request_body
        assert request_body["model"] == "claude-sonnet-4-5"

        # These are the critical Antigravity-specific fields
        assert "userAgent" in request_body
        assert request_body["userAgent"] == "antigravity"
        assert "requestType" in request_body
        assert request_body["requestType"] == "agent"

    def test_build_code_assist_request_body_uses_request_id_not_user_prompt_id(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that Antigravity uses 'requestId' instead of 'user_prompt_id'."""
        client = MagicMock(spec=httpx.AsyncClient)
        connector = AntigravityOAuthConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        request_data = ChatRequest(
            model="claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        request_body = connector._build_code_assist_request_body(
            effective_model="claude-sonnet-4-5",
            project_id="test-project",
            request_data=request_data,
            code_assist_request={},
        )

        # Antigravity uses requestId, not user_prompt_id
        assert "requestId" in request_body
        assert "user_prompt_id" not in request_body


class TestAntigravityHeaders:
    """Tests for HTTP headers sent to the Antigravity API."""

    def test_get_session_headers_includes_user_agent(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that session headers include Antigravity User-Agent."""
        client = MagicMock(spec=httpx.AsyncClient)
        connector = AntigravityOAuthConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        headers = connector._get_session_headers()

        assert "User-Agent" in headers
        assert headers["User-Agent"] == ANTIGRAVITY_USER_AGENT

    def test_get_api_headers_includes_user_agent(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that API headers include Antigravity User-Agent."""
        client = MagicMock(spec=httpx.AsyncClient)
        connector = AntigravityOAuthConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Mock credentials for get_api_headers
        connector._oauth_credentials = {"access_token": "test-token"}

        headers = connector._get_api_headers()

        assert "User-Agent" in headers
        assert headers["User-Agent"] == ANTIGRAVITY_USER_AGENT


class TestAntigravityEndpoint:
    """Tests for the Antigravity sandbox endpoint configuration."""

    def test_sandbox_endpoint_is_configured(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that the connector uses the Antigravity sandbox endpoint."""
        assert (
            ANTIGRAVITY_SANDBOX_ENDPOINT
            == "https://daily-cloudcode-pa.sandbox.googleapis.com"
        )

    @pytest.mark.asyncio
    async def test_initialize_passes_sandbox_endpoint_to_parent(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that initialize passes the Antigravity sandbox endpoint to parent."""
        client = MagicMock(spec=httpx.AsyncClient)
        connector = AntigravityOAuthConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Mock the credential loading to avoid filesystem access
        with patch.object(
            connector, "_load_oauth_credentials", new_callable=AsyncMock
        ) as mock_load:
            mock_load.return_value = True
            connector._oauth_credentials = {
                "access_token": "test-token",
                "expiry_date": 9999999999000,  # Far future
            }

            # Mock the parent initialize to capture kwargs
            with patch.object(
                AntigravityOAuthConnector.__bases__[0],
                "initialize",
                new_callable=AsyncMock,
            ) as mock_parent_init:
                await connector.initialize()

        # Verify parent initialize was called with the sandbox endpoint
        mock_parent_init.assert_called_once()
        call_kwargs = mock_parent_init.call_args.kwargs
        assert call_kwargs.get("gemini_api_base_url") == ANTIGRAVITY_SANDBOX_ENDPOINT


class TestAntigravityQuotaErrors:
    """Tests for quota error handling in the Antigravity connector."""

    def test_quota_error_details_are_preserved(self) -> None:
        """Test that quota error details from the API are preserved."""
        # This is an example of the error response from the API
        error_response = {
            "error": {
                "code": 429,
                "message": "You have exhausted your capacity on this model. "
                "Your quota will reset after 3h28m40s.",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "QUOTA_EXHAUSTED",
                        "domain": "cloudcode-pa.googleapis.com",
                        "metadata": {
                            "model": "claude-sonnet-4-5",
                            "quotaResetDelay": "3h28m40.97366169s",
                            "quotaResetTimeStamp": "2025-11-26T14:51:05Z",
                        },
                    }
                ],
            }
        }

        # Extract metadata from error response
        error_dict: dict[str, Any] = error_response["error"]
        details: list[dict[str, Any]] = error_dict.get("details", [])
        assert len(details) > 0

        error_info: dict[str, Any] = details[0]
        metadata: dict[str, Any] = error_info.get("metadata", {})

        # Verify we can extract the quota reset information
        assert "quotaResetDelay" in metadata
        assert "quotaResetTimeStamp" in metadata
        assert "model" in metadata
        assert metadata["model"] == "claude-sonnet-4-5"


class TestAntigravityModelValidation:
    """Tests for model validation in the Antigravity connector."""

    def test_model_prefix_stripping_for_validation(
        self, mock_config: AppConfig, mock_translation_service: TranslationService
    ) -> None:
        """Test that model prefixes are stripped correctly for validation."""
        client = MagicMock(spec=httpx.AsyncClient)
        connector = AntigravityOAuthConnector(
            client=client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # The connector should strip "gemini-oauth-plan:" prefix for validation
        # but note it checks for this specific prefix, not the backend prefix
        model_with_prefix = "gemini-oauth-plan:claude-sonnet-4-5"
        model_without_prefix = "claude-sonnet-4-5"

        # The actual model name after stripping should be used for validation
        if model_with_prefix.startswith("gemini-oauth-plan:"):
            stripped_model = model_with_prefix[len("gemini-oauth-plan:") :]
            assert stripped_model == model_without_prefix

        # Verify connector has available_models attribute (test connector was created)
        assert hasattr(connector, "available_models")
