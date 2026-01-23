"""
Refinement tests for OAuthFlowService covering error branches.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import RedirectResponse

from src.connectors.gemini_oauth_auto.errors import OAuthError
from src.connectors.gemini_oauth_auto.oauth_flow import OAuthFlowService
from src.connectors.gemini_oauth_auto.constants import FAILURE_REDIRECT, SUCCESS_REDIRECT


@pytest.fixture
def oauth_service() -> OAuthFlowService:
    """Fixture providing OAuthFlowService with mocked storage."""
    return OAuthFlowService(storage=MagicMock())


@pytest.mark.asyncio
class TestOAuthFlowRefinement:
    """Tests for OAuthFlowService error branches and refinement."""

    async def test_callback_logic_error_from_google(self, oauth_service):
        """Test callback handles error from Google."""
        future = asyncio.Future()
        response = await oauth_service._handle_callback_logic(
            received_state="state",
            code=None,
            error="access_denied",
            expected_state="state",
            code_received_future=future
        )
        
        assert response.headers["location"] == FAILURE_REDIRECT
        assert future.done()
        with pytest.raises(OAuthError, match="access_denied"):
            future.result()

    async def test_callback_logic_state_mismatch(self, oauth_service):
        """Test callback handles state mismatch."""
        future = asyncio.Future()
        response = await oauth_service._handle_callback_logic(
            received_state="wrong_state",
            code="code",
            error=None,
            expected_state="expected_state",
            code_received_future=future
        )
        
        assert response.headers["location"] == FAILURE_REDIRECT
        assert future.done()
        with pytest.raises(OAuthError, match="State parameter mismatch"):
            future.result()

    async def test_callback_logic_no_code(self, oauth_service):
        """Test callback handles missing code."""
        future = asyncio.Future()
        response = await oauth_service._handle_callback_logic(
            received_state="state",
            code=None,
            error=None,
            expected_state="state",
            code_received_future=future
        )
        
        assert response.headers["location"] == FAILURE_REDIRECT
        assert future.done()
        with pytest.raises(OAuthError, match="No authorization code received"):
            future.result()

    async def test_callback_logic_success(self, oauth_service):
        """Test callback handles success."""
        future = asyncio.Future()
        response = await oauth_service._handle_callback_logic(
            received_state="state",
            code="good_code",
            error=None,
            expected_state="state",
            code_received_future=future
        )
        
        assert response.headers["location"] == SUCCESS_REDIRECT
        assert future.done()
        assert future.result() == "good_code"

    @pytest.mark.asyncio
    async def test_authorize_with_existing_account(self, oauth_service):
        """Test authorize when account already exists (update flow)."""
        mock_account = MagicMock()
        mock_account.with_updated_tokens.return_value = MagicMock()
        
        oauth_service._storage.get_account = AsyncMock(return_value=mock_account)
        oauth_service._storage.save_account = AsyncMock()
        oauth_service._http_client = MagicMock()
        
        # Mock internal methods to simulate a successful flow
        oauth_service._exchange_code = AsyncMock(return_value={
            "access_token": "new_access",
            "expires_in": 3600,
            "refresh_token": "new_refresh",
            "scope": "scope"
        })
        oauth_service._fetch_userinfo = AsyncMock(return_value={"email": "test@gmail.com"})
        
        # Mock uvicorn and webbrowser
        with patch("webbrowser.open"), \
             patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
            
            # Simulate code received
            async def simulate_code(*args, **kwargs):
                # We need to find the code_received future and set it
                # This is a bit complex due to scoping, let's just mock the whole authorize 
                # or parts of it.
                pass

            # Instead of mocking everything, let's just test the logic after code exchange 
            # in a separate test if needed, but here we want to cover line 171.
            
            # Let's use a simpler approach: test the logic inside authorize by patching wait_for
            with patch("asyncio.wait_for", AsyncMock(return_value="code123")):
                await oauth_service.authorize(open_browser=False)
                
                # Verify get_account was called
                oauth_service._storage.get_account.assert_called()
                # Verify with_updated_tokens was called
                mock_account.with_updated_tokens.assert_called()
                # Verify save_account was called with the updated account
                oauth_service._storage.save_account.assert_called_with(
                    mock_account.with_updated_tokens.return_value
                )

from unittest.mock import patch
