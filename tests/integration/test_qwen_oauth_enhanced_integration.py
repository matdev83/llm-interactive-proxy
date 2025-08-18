"""
Enhanced integration tests for Qwen OAuth backend with focus on authentication scenarios.

These tests verify that the Qwen OAuth backend properly handles:
1. Token refresh during long-running sessions
2. Authentication error recovery
3. Token persistence across requests
4. Authentication with different credential states

Run with: pytest -m "integration and network" tests/integration/test_qwen_oauth_enhanced_integration.py
"""

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app

# Mark all tests in this module as integration and network tests
pytestmark = [pytest.mark.integration, pytest.mark.network]


# Check if OAuth credentials are available
def _has_qwen_oauth_credentials() -> bool:
    """Check if Qwen OAuth credentials are available."""
    home_dir = Path.home()
    creds_path = home_dir / ".qwen" / "oauth_creds.json"

    if not creds_path.exists():
        return False

    try:
        with open(creds_path, encoding="utf-8") as f:
            creds = json.load(f)
        return bool(creds.get("access_token") and creds.get("refresh_token"))
    except Exception:
        return False


# Skip all tests if OAuth credentials are not available
QWEN_OAUTH_AVAILABLE = _has_qwen_oauth_credentials()


class TestQwenOAuthAuthenticationFlow:
    """Test the authentication flow for Qwen OAuth connector."""

    @pytest.fixture
    def mock_oauth_credentials(self):
        """Create mock OAuth credentials for testing."""
        current_time_ms = int(time.time() * 1000)
        return {
            "access_token": "mock-access-token",
            "refresh_token": "mock-refresh-token",
            "token_type": "Bearer",
            "expiry_date": current_time_ms + 3600 * 1000,  # 1 hour from now
            "resource_url": "https://dashscope.aliyuncs.com/compatible-mode",
        }

    @pytest.fixture
    def mock_expired_oauth_credentials(self):
        """Create mock expired OAuth credentials for testing."""
        current_time_ms = int(time.time() * 1000)
        return {
            "access_token": "mock-expired-access-token",
            "refresh_token": "mock-refresh-token",
            "token_type": "Bearer",
            "expiry_date": current_time_ms - 60 * 1000,  # 1 minute ago
            "resource_url": "https://dashscope.aliyuncs.com/compatible-mode",
        }

    @pytest.fixture
    def mock_token_refresh_response(self):
        """Create mock token refresh response for testing."""
        return {
            "access_token": "mock-refreshed-access-token",
            "refresh_token": "mock-new-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,  # 1 hour
            "resource_url": "https://dashscope.aliyuncs.com/compatible-mode",
        }

    @pytest.mark.asyncio
    async def test_token_refresh_during_session(
        self, mock_expired_oauth_credentials, mock_token_refresh_response
    ):
        """Test that tokens are refreshed during a session when they expire."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        # Create a connector with mock client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        connector = QwenOAuthConnector(mock_client)

        # Setup mock for credentials file
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", MagicMock()),
            patch("json.load", return_value=mock_expired_oauth_credentials),
            patch("json.dump"),
        ):

            # Setup mock for token refresh response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_token_refresh_response
            mock_client.post.return_value = mock_response

            # Initialize connector
            await connector.initialize()

            # Verify token refresh was attempted during initialization
            mock_client.post.assert_called_once_with(
                "https://chat.qwen.ai/api/v1/oauth2/token",
                content=pytest.approx(
                    "grant_type=refresh_token&refresh_token=mock-refresh-token&client_id=f0304373b74a44d2b584a3fb70ca9e56"
                ),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )

            # Verify the token was updated
            assert (
                connector._oauth_credentials is not None
                and connector._oauth_credentials["access_token"]
                == "mock-refreshed-access-token"
            )
            assert (
                connector._oauth_credentials is not None
                and connector._oauth_credentials["refresh_token"]
                == "mock-new-refresh-token"
            )

    @pytest.mark.asyncio
    async def test_authentication_error_recovery(self, mock_expired_oauth_credentials):
        """Test recovery from authentication errors during token refresh."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        # Create a connector with mock client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        connector = QwenOAuthConnector(mock_client)

        # Setup mock for credentials file
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", MagicMock()),
            patch("json.load", return_value=mock_expired_oauth_credentials),
            patch("json.dump"),
        ):

            # Setup mock for token refresh response - first fail, then succeed
            mock_error_response = MagicMock()
            mock_error_response.status_code = 401
            mock_error_response.text = "Invalid refresh token"

            mock_success_response = MagicMock()
            mock_success_response.status_code = 200
            mock_success_response.json.return_value = {
                "access_token": "mock-refreshed-access-token",
                "refresh_token": "mock-new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

            # First call fails, second call succeeds
            mock_client.post.side_effect = [mock_error_response, mock_success_response]

            # Initialize connector - should fail to refresh token
            await connector.initialize()

            # Verify token refresh was attempted
            assert mock_client.post.call_count == 1

            # Connector should not be functional due to failed refresh
            assert not connector.is_functional

            # Now simulate a chat completion that would trigger another refresh attempt
            from src.core.domain.chat import ChatMessage, ChatRequest

            # But first we need to mock the refresh to succeed this time
            mock_client.post.reset_mock()
            mock_client.post.return_value = mock_success_response

            # Set up a request
            request = ChatRequest(
                model="qwen3-coder-plus",
                messages=[ChatMessage(role="user", content="Hello")],
            )

            # Mock the parent class chat_completions to avoid actual API calls
            with patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                return_value=({"id": "test", "choices": []}, {}),
            ):

                # This should trigger a token refresh attempt
                try:
                    await connector.chat_completions(
                        request_data=request,
                        processed_messages=[{"role": "user", "content": "Hello"}],
                        effective_model="qwen3-coder-plus",
                    )
                    # If we get here, the refresh succeeded
                    mock_client.post.assert_called_once()
                    assert (
                        connector._oauth_credentials is not None
                        and connector._oauth_credentials["access_token"]
                        == "mock-refreshed-access-token"
                    )
                except Exception as e:
                    pytest.fail(f"Failed to recover from authentication error: {e}")

    @pytest.mark.asyncio
    async def test_token_persistence_across_requests(self, mock_oauth_credentials):
        """Test that tokens are persisted across requests."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        # Create a connector with mock client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        connector = QwenOAuthConnector(mock_client)

        # Setup mock for credentials file
        mock_open = MagicMock()
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open),
            patch("json.load", return_value=mock_oauth_credentials),
            patch("json.dump") as mock_json_dump,
        ):

            # Initialize connector
            await connector.initialize()

            # Verify credentials were loaded
            assert (
                connector._oauth_credentials is not None
                and connector._oauth_credentials["access_token"] == "mock-access-token"
            )

            # Now simulate updating the token
            if connector._oauth_credentials is not None:
                connector._oauth_credentials["access_token"] = "updated-access-token"

            # Save the credentials
            await connector._save_oauth_credentials()

            # Verify the credentials were saved
            mock_json_dump.assert_called_once()
            args, _ = mock_json_dump.call_args
            saved_creds = args[0]
            assert saved_creds["access_token"] == "updated-access-token"

    @pytest.mark.asyncio
    async def test_authentication_with_missing_credentials(self):
        """Test behavior when credentials file is missing."""
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        # Create a connector with mock client
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        connector = QwenOAuthConnector(mock_client)

        # Setup mock for missing credentials file
        with patch("pathlib.Path.exists", return_value=False):
            # Initialize connector
            await connector.initialize()

            # Connector should not be functional
            assert not connector.is_functional
            assert len(connector.get_available_models()) == 0

            # Attempting to get headers should raise an exception
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as excinfo:
                connector.get_headers()

            assert excinfo.value.status_code == 401
            assert "No valid Qwen OAuth access token available" in excinfo.value.detail

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_real_token_refresh_integration(self):
        """Test token refresh with real credentials (if available)."""
        # This test uses the actual credentials file
        import httpx
        from src.connectors.qwen_oauth import QwenOAuthConnector

        async def run_test():
            async with httpx.AsyncClient(timeout=30.0) as client:
                connector = QwenOAuthConnector(client)

                # Initialize the connector
                await connector.initialize()

                # Force token refresh by manipulating expiry
                if connector._oauth_credentials:
                    original_token = connector._oauth_credentials.get("access_token")

                    # Force token to be considered expired
                    connector._oauth_credentials["expiry_date"] = (
                        int(time.time() * 1000) - 60000
                    )

                    # Trigger a refresh by checking expiry
                    is_expired = connector._is_token_expired()
                    assert is_expired is True

                    # Attempt to refresh the token
                    refresh_success = await connector._refresh_token_if_needed()

                    if refresh_success:
                        new_token = connector._oauth_credentials.get("access_token")
                        # Either the token should be different, or it should be the same but with updated expiry
                        if new_token != original_token:
                            print("✅ Token was successfully refreshed to a new value")
                        else:
                            print("i Token value remained the same after refresh")

                        # Expiry should be updated
                        new_expiry = connector._oauth_credentials.get("expiry_date")
                        assert new_expiry is not None and new_expiry > int(
                            time.time() * 1000
                        )
                    else:
                        print("❌ Token refresh failed")

        # Run the async test
        asyncio.run(run_test())


class TestQwenOAuthAuthenticationWithProxy:
    """Test authentication scenarios with the full proxy application."""

    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for Qwen OAuth backend."""
        with patch("src.core.config.load_dotenv"):
            # Set up environment for testing
            os.environ["LLM_BACKEND"] = "qwen-oauth"
            os.environ["DISABLE_AUTH"] = "true"  # Disable proxy auth for testing
            os.environ["DISABLE_ACCOUNTING"] = "true"  # Disable accounting for testing
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"

            app = build_app()
            yield app

    @pytest.fixture
    def qwen_oauth_client(self, qwen_oauth_app):
        """TestClient for Qwen OAuth configured app."""
        with TestClient(qwen_oauth_app) as client:
            yield client

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_authentication_headers_in_proxy_requests(self, qwen_oauth_client):
        """Test that authentication headers are properly included in proxy requests."""
        # Use respx to mock the actual API request and inspect headers
        import respx

        # Mock the Qwen API endpoint
        with respx.mock(assert_all_mocked=False) as respx_mock:
            # Create a route that captures the request
            route = respx_mock.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            ).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": "test",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "Hello!"},
                                "finish_reason": "stop",
                            }
                        ],
                    },
                )
            )

            # Make a request through the proxy
            request_payload = {
                "model": "qwen-oauth:qwen3-coder-plus",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10,
                "temperature": 0.1,
                "stream": False,
            }

            response = qwen_oauth_client.post(
                "/v1/chat/completions", json=request_payload
            )

            # Verify the response
            assert response.status_code == 200

            # Verify the request was made with proper authentication
            assert route.called
            request = route.calls[0].request
            assert "authorization" in request.headers
            assert request.headers["authorization"].startswith("Bearer ")

            # The token should not be the test proxy key
            assert request.headers["authorization"] != "Bearer test-proxy-key"

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_session_persistence_with_token_refresh(self, qwen_oauth_client):
        """Test that session state is maintained when tokens are refreshed."""
        # First request to establish session
        first_payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [
                {"role": "user", "content": "Remember that my favorite color is blue."}
            ],
            "max_tokens": 50,
            "temperature": 0.1,
            "stream": False,
        }

        first_response = qwen_oauth_client.post(
            "/v1/chat/completions", json=first_payload
        )
        assert first_response.status_code == 200

        # Get the session ID from the response
        session_id = first_response.cookies.get("session_id")
        assert session_id is not None

        # Now simulate token refresh by directly manipulating the backend
        # (This is a bit of a hack, but it's the easiest way to test this)
        app = qwen_oauth_client.app
        backend = app.state.qwen_oauth_backend

        if backend and backend._oauth_credentials:
            # Force token to be considered expired
            original_token = backend._oauth_credentials.get("access_token")
            backend._oauth_credentials["expiry_date"] = int(time.time() * 1000) - 60000

            # Make a second request with the same session
            second_payload = {
                "model": "qwen-oauth:qwen3-coder-plus",
                "messages": [
                    {
                        "role": "user",
                        "content": "Remember that my favorite color is blue.",
                    },
                    {
                        "role": "assistant",
                        "content": "I'll remember that your favorite color is blue.",
                    },
                    {"role": "user", "content": "What's my favorite color?"},
                ],
                "max_tokens": 50,
                "temperature": 0.1,
                "stream": False,
            }

            # Include the session cookie
            cookies = {"session_id": session_id}
            second_response = qwen_oauth_client.post(
                "/v1/chat/completions", json=second_payload, cookies=cookies
            )

            # Verify the response
            assert second_response.status_code == 200

            # Check if token was refreshed
            if (
                backend._oauth_credentials is not None
                and backend._oauth_credentials.get("access_token") != original_token
            ):
                print("✅ Token was refreshed during the session")

            # Verify the response mentions blue (context was maintained)
            result = second_response.json()
            content = result["choices"][0]["message"]["content"].lower()

            # The model should remember the favorite color
            assert "blue" in content


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-m", "integration and network"])
