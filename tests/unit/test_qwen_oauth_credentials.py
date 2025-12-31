"""
Unit tests for Qwen OAuth connector credential handling functionality.

These tests focus on the unique aspects of the QwenOAuthConnector:
- Credential loading and caching
- Token refresh logic
- API base URL handling
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.domain.chat import ChatMessage, ChatRequest

from tests.utils.fake_clock import FakeClock, FakeClockContext

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
    ),
    pytest.mark.no_global_mock,
    pytest.mark.xdist_group("qwen_oauth_serial"),
]


@pytest.fixture(autouse=True)
def cleanup_connector_state():
    """Clean up connector state between tests to ensure isolation."""
    yield
    # Cleanup after each test - patch mock should auto-cleanup when context exits


@pytest.fixture(autouse=True)
def isolate_test_completely():
    """Ensure complete test isolation by clearing any global state."""
    import os

    # Store original environment
    original_env = dict(os.environ)

    yield

    # Restore original environment completely
    os.environ.clear()
    os.environ.update(original_env)


class TestQwenOAuthCredentials:
    """Unit tests for credential handling in QwenOAuthConnector."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        connector = QwenOAuthConnector(mock_client, config=config)
        return connector

    @pytest.mark.asyncio
    async def test_load_oauth_credentials(self, connector):
        """Test loading OAuth credentials from file."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            mock_creds = {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "token_type": "Bearer",
                "resource_url": "portal.qwen.ai",
                "expiry_date": int(clock.now() * 1000) + 3600000,
            }

            # Mock Path.exists and Path.stat
            with (
                patch("pathlib.Path.exists", return_value=True),
                patch("pathlib.Path.stat") as mock_stat,
                patch("builtins.open", mock_open(read_data=json.dumps(mock_creds))),
            ):
                # Mock stat to return a modified time
                mock_stat_result = MagicMock()
                mock_stat_result.st_mtime = 12345.0
                mock_stat.return_value = mock_stat_result

                # Call the method
                result = await connector._load_oauth_credentials()

                # Verify results
                assert result is True
                assert connector._oauth_credentials == mock_creds
                assert connector._last_modified == 12345.0
            assert connector.api_base_url == "https://portal.qwen.ai/v1"

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_file_not_found(self, connector):
        """Test loading OAuth credentials when file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = await connector._load_oauth_credentials()
            assert result is False
            assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_invalid_json(self, connector):
        """Test loading OAuth credentials with invalid JSON."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="invalid json")),
        ):
            result = await connector._load_oauth_credentials()
            assert result is False
            assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_missing_fields(self, connector):
        """Test loading OAuth credentials with missing required fields."""
        mock_creds = {"some_field": "value"}  # Missing access_token and refresh_token

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(mock_creds))),
        ):
            result = await connector._load_oauth_credentials()
            assert result is False
            # The connector doesn't store invalid credentials

    @pytest.mark.asyncio
    async def test_is_token_expired(self, connector):
        """Test token expiry check."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Test with no credentials
            connector._oauth_credentials = None
            assert connector._is_token_expired() is True

            # Test with no expiry date
            connector._oauth_credentials = {"access_token": "test"}
            assert connector._is_token_expired() is False

            # Test with future expiry date
            connector._oauth_credentials = {
                "expiry_date": int(clock.now() * 1000) + 3600000
            }
            assert connector._is_token_expired() is False

            # Test with past expiry date
            connector._oauth_credentials = {"expiry_date": int(clock.now() * 1000) - 1000}
            assert connector._is_token_expired() is True

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_not_expired(self, connector):
        """Test refresh token when not expired."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            connector._oauth_credentials = {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "expiry_date": int(clock.now() * 1000) + 3600000,  # 1 hour in the future
            }

            with patch.object(connector, "_is_token_expired", return_value=False):
                result = await connector._refresh_token_if_needed()
                assert result is True

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_success(self, connector, mock_client):
        """Test successful token refresh using CLI-based refresh."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            connector._oauth_credentials = {
                "refresh_token": "test-refresh-token",
            }

            # Mock CLI-based token refresh (since Qwen OAuth now uses CLI, not HTTP)
            new_credentials = {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "resource_url": "new.portal.qwen.ai",
                "expiry_date": int(clock.now() * 1000) + 3600000,
            }

            with (
                patch.object(connector, "_is_token_expired", return_value=True),
                patch.object(
                    connector, "_load_oauth_credentials", return_value=True
                ),  # Load after CLI refresh
                patch("shutil.which", return_value="/mock/qwen"),  # CLI tool available
                patch.object(connector, "_launch_cli_refresh_process") as mock_launch,
                patch.object(
                    connector, "_poll_for_new_token", return_value=True
                ),  # CLI succeeded
            ):
                # Mock the actual credential loading that happens after CLI refresh
                def mock_load_side_effect():
                    connector._oauth_credentials = new_credentials
                    # The real implementation no longer updates API base URL from resource_url
                    # It always uses the fixed DashScope endpoint
                    return True

                connector._load_oauth_credentials.side_effect = mock_load_side_effect

                result = await connector._refresh_token_if_needed()

                # Verify the token was refreshed via CLI
                assert result is True
                assert connector._oauth_credentials["access_token"] == "new-access-token"
                assert connector._oauth_credentials["refresh_token"] == "new-refresh-token"
                assert connector.api_base_url == "https://new.portal.qwen.ai/v1"
                mock_launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_http_error(self, connector, mock_client):
        """Test token refresh when CLI process fails but API fallback succeeds."""
        connector._oauth_credentials = {
            "refresh_token": "test-refresh-token",
        }

        # Mock CLI process failure (CLI not found) but API fallback succeeds
        with (
            patch.object(connector, "_is_token_expired", return_value=True),
            patch("shutil.which", return_value=None),  # CLI tool not available
            patch.object(
                connector, "_load_oauth_credentials", return_value=False
            ),  # Force CLI refresh
            patch.object(
                connector, "_poll_for_new_token", return_value=False
            ),  # CLI polling fails
            patch.object(
                connector, "_refresh_token_via_endpoint", return_value=True
            ) as mock_api_refresh,  # API fallback succeeds
        ):
            result = await connector._refresh_token_if_needed()
            assert result is True  # Should succeed via API fallback
            mock_api_refresh.assert_called_once()  # Verify API fallback was called

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_network_error(self, connector, mock_client):
        """Test token refresh when both CLI and API fallback fail."""
        connector._oauth_credentials = {
            "refresh_token": "test-refresh-token",
        }

        # Mock both CLI and API refresh to fail
        with (
            patch.object(connector, "_is_token_expired", return_value=True),
            patch("shutil.which", return_value="/mock/qwen"),  # CLI tool available
            patch.object(
                connector, "_load_oauth_credentials", return_value=False
            ),  # Force CLI refresh
            patch.object(connector, "_launch_cli_refresh_process") as mock_launch,
            patch.object(
                connector, "_poll_for_new_token", return_value=False
            ),  # CLI failed
            patch.object(
                connector, "_refresh_token_via_endpoint", return_value=False
            ) as mock_api_refresh,  # API fallback also fails
        ):
            result = await connector._refresh_token_if_needed()
            assert result is False  # Should fail when both methods fail
            mock_launch.assert_called_once()
            mock_api_refresh.assert_called_once()  # Verify API fallback was attempted

    @pytest.mark.slow
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_refresh_token_waits_for_delayed_cli_update(
        self, connector, monkeypatch
    ):
        """Ensure refresh waits for credentials file update instead of failing fast."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            connector._oauth_credentials = {
                "access_token": "old-token",
                "refresh_token": "refresh-token",
                "expiry_date": int((clock.now() - 120) * 1000),
            }

            monkeypatch.setattr(connector, "_launch_cli_refresh_process", MagicMock())

            load_calls = 0

            async def fake_load(force_reload: bool = False) -> bool:
                nonlocal load_calls
                load_calls += 1
                if load_calls >= 8:
                    connector._oauth_credentials["expiry_date"] = int(
                        (clock.now() + 3600) * 1000
                    )
                    connector._oauth_credentials["access_token"] = f"new-token-{load_calls}"
                return True

            connector._load_oauth_credentials = AsyncMock(  # type: ignore[assignment]
                side_effect=fake_load
            )

            sleep_calls = 0

            async def fake_sleep(_: float) -> None:
                nonlocal sleep_calls
                sleep_calls += 1

            monkeypatch.setattr(asyncio, "sleep", fake_sleep)

            result = await connector._refresh_token_if_needed()

            assert result is True
            assert sleep_calls >= 7
            assert connector._oauth_credentials["access_token"].startswith("new-token")

    def test_get_headers(self, connector):
        """Test getting headers with access token."""
        connector._oauth_credentials = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
        }

        headers = connector.get_headers()
        assert headers["Authorization"] == "Bearer test-access-token"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_chat_completions_with_token_refresh(self, connector, mock_client):
        """Test chat completion with token refresh."""
        async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
            # Set up the connector with expired token
            connector._oauth_credentials = {
                "access_token": "old-token",
                "refresh_token": "test-refresh-token",
                "expiry_date": int(clock.now() * 1000) - 1000,  # Expired
            }

            # Mock chat completion response (CLI refresh happens independently)
            mock_completion_response = MagicMock()
            mock_completion_response.status_code = 200
            mock_completion_response.json.return_value = {
                "id": "test-id",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Test response"},
                        "finish_reason": "stop",
                    }
                ],
            }
            mock_completion_response.headers = {"content-type": "application/json"}

            # Set up the mock client for the chat completion call only
            mock_client.post.return_value = mock_completion_response

            # Create a simple request
            test_message = ChatMessage(role="user", content="Hello")
            request_data = ChatRequest(
                model="qwen3-coder-plus",
                messages=[test_message],
                stream=False,
            )

            # Call the method with CLI-based refresh mocking
            new_credentials = {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expiry_date": int(clock.now() * 1000) + 3600000,
            }

            # Create mocks with proper reset and clear any existing state
            with (
                patch.object(
                    connector, "_validate_runtime_credentials", new_callable=AsyncMock
                ) as mock_validate,
                patch.object(
                    connector, "_refresh_token_if_needed", new_callable=AsyncMock
                ) as mock_refresh,
                patch.object(
                    connector,
                    "_chat_completions_canonical",
                    new_callable=AsyncMock,
                ) as mock_parent_chat,
            ):
                # Configure mocks explicitly
                mock_validate.return_value = True

                # Mock successful CLI refresh
                async def mock_refresh_side_effect(*args, **kwargs):
                    connector._oauth_credentials = new_credentials
                    return True

                mock_refresh.return_value = True
                mock_refresh.side_effect = mock_refresh_side_effect
                from src.core.domain.responses import ResponseEnvelope
                mock_parent_chat.return_value = ResponseEnvelope(
                    content={"id": "test-id", "choices": []},
                )

                await connector.chat_completions(
                    request_data=request_data,
                    processed_messages=[test_message],
                    effective_model="qwen3-coder-plus",
                )

                # Verify token refresh was attempted and parent method was called
                assert (
                    mock_refresh.call_count == 1
                ), f"Expected _refresh_token_if_needed to be called once, was called {mock_refresh.call_count} times"
                assert (
                    mock_parent_chat.call_count == 1
                ), f"Expected parent _chat_completions_canonical to be called once, was called {mock_parent_chat.call_count} times"
                # Verify the new token is now in the credentials
            assert connector._oauth_credentials["access_token"] == "new-access-token"
