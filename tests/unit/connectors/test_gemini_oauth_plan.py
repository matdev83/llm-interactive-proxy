"""
Tests for Gemini OAuth Plan connector.
"""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from src.connectors.gemini_oauth_plan import GeminiOAuthPlanConnector


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def connector(mock_client):
    """Create a GeminiOAuthPlanConnector instance."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    return GeminiOAuthPlanConnector(mock_client, config, translation_service)


class TestGeminiOAuthPlanConnector:
    """Test cases for GeminiOAuthPlanConnector."""

    def test_backend_type(self, connector):
        """Test that the backend type is correct."""
        assert connector.backend_type == "gemini-oauth-plan"

    def test_initialization(self, connector):
        """Test that the connector initializes with correct default values."""
        assert connector.name == "gemini-oauth-plan"
        assert connector._oauth_credentials is None
        assert connector._credentials_path is None
        assert connector._last_modified == 0
        assert connector._refresh_token is None
        assert isinstance(connector._token_refresh_lock, asyncio.Lock)
        assert connector._last_cli_refresh_attempt == 0.0
        assert connector._cli_refresh_process is None

    async def test_discover_project_id_for_plan(self, connector):
        """Test that the project ID is discovered correctly for the paid plan."""
        from unittest.mock import Mock

        # Mock the auth session to return successful responses for tier selection and onboarding
        mock_auth_session = Mock()

        # Mock the tier selection response
        tier_selection_response = Mock()
        tier_selection_response.status_code = 200
        tier_selection_response.json.return_value = {}

        # Mock the onboarding response
        onboarding_response = Mock()
        onboarding_response.status_code = 200
        onboarding_response.json.return_value = {"projectId": "test-project-id"}

        # Configure the mock to return different responses for different calls
        mock_auth_session.post.side_effect = [
            tier_selection_response,  # First call (tier selection)
            onboarding_response,  # Second call (onboarding)
        ]

        # The gemini_api_base_url needs to be set for the method to work
        connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"

        project_id = await connector._discover_project_id(mock_auth_session)

        # Verify the returned project ID
        assert project_id == "test-project-id"
        assert connector._project_id == "test-project-id"

        # Verify that the correct calls were made
        assert mock_auth_session.post.call_count == 2
        # Check the first call (tier selection)
        mock_auth_session.post.assert_any_call(
            "https://cloudcode-pa.googleapis.com/v1internal/userTier:select",
            json={"userTierId": "paid-tier"},
            headers={"Content-Type": "application/json"},
        )
        # Check the second call (onboarding)
        mock_auth_session.post.assert_called_with(
            "https://cloudcode-pa.googleapis.com/v1internal/onboard",
            json={
                "userTierId": "paid-tier",
                "cloudaicompanionProject": {
                    "name": "cloudaicompanionProject",
                },
            },
            headers={"Content-Type": "application/json"},
        )
