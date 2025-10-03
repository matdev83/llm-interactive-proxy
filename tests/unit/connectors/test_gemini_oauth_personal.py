"""
Tests for Gemini OAuth Personal connector.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def connector(mock_client):
    """Create a GeminiOAuthPersonalConnector instance."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    return GeminiOAuthPersonalConnector(mock_client, config, translation_service)


class TestGeminiOAuthPersonalConnector:
    """Test cases for GeminiOAuthPersonalConnector."""

    def test_backend_type(self, connector):
        """Test that the backend type is correct."""
        assert connector.backend_type == "gemini-cli-oauth-personal"

    def test_initialization(self, connector):
        """Test that the connector initializes with correct default values."""
        assert connector.name == "gemini-cli-oauth-personal"
        assert connector._oauth_credentials is None
        assert connector._credentials_path is None
        assert connector._last_modified == 0
        assert connector._refresh_token is None
        assert isinstance(connector._token_refresh_lock, asyncio.Lock)
        assert connector._last_cli_refresh_attempt == 0.0
        assert connector._cli_refresh_process is None

    def test_is_token_expired_no_credentials(self, connector):
        """Test token expiry check when no credentials are loaded."""
        assert connector._is_token_expired() is True

    def test_is_token_expired_no_expiry(self, connector):
        """Test token expiry check when no expiry date is present."""
        connector._oauth_credentials = {"access_token": "test_token"}
        assert connector._is_token_expired() is False

    def test_is_token_expired_expired(self, connector):
        """Test token expiry check when token is expired."""
        import time

        connector._oauth_credentials = {
            "access_token": "test_token",
            "expiry_date": (time.time() - 100) * 1000,  # Expired 100 seconds ago
        }
        assert connector._is_token_expired() is True

    def test_is_token_expired_not_expired(self, connector):
        """Test token expiry check when token is not expired."""
        import time

        connector._oauth_credentials = {
            "access_token": "test_token",
            "expiry_date": (time.time() + 1000) * 1000,  # Expires in 1000 seconds
        }
        assert connector._is_token_expired() is False

    def test_get_refresh_token_from_credentials(self, connector):
        """Test getting refresh token from credentials."""
        connector._oauth_credentials = {"refresh_token": "test_refresh_token"}
        assert connector._get_refresh_token() == "test_refresh_token"

    def test_get_refresh_token_from_cache(self, connector):
        """Test getting refresh token from cache."""
        connector._refresh_token = "cached_refresh_token"
        assert connector._get_refresh_token() == "cached_refresh_token"

    def test_should_trigger_cli_refresh_with_short_expiry(self, connector):
        """Token expiring within threshold should trigger CLI refresh."""
        connector._oauth_credentials = {
            "access_token": "token",
            "expiry_date": (time.time() + 90) * 1000,
        }

        assert connector._should_trigger_cli_refresh() is True

    def test_should_trigger_cli_refresh_with_no_expiry(self, connector):
        """Token without expiry should not trigger CLI refresh."""
        connector._oauth_credentials = {"access_token": "token"}

        assert connector._should_trigger_cli_refresh() is False

    @patch("pathlib.Path.home")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    @patch("builtins.open")
    def test_load_oauth_credentials_success(
        self, mock_open, mock_stat, mock_exists, mock_home, connector
    ):
        """Test successful loading of OAuth credentials."""
        # Setup mocks
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = True
        mock_stat.return_value = MagicMock(st_mtime=1234567890)

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.__exit__.return_value = None
        mock_open.return_value = mock_file

        test_credentials = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expiry_date": 1756204339476,
        }
        mock_file.read.return_value = json.dumps(test_credentials)

        # Test
        result = asyncio.run(connector._load_oauth_credentials())

        assert result is True
        assert connector._oauth_credentials == test_credentials
        assert connector._credentials_path == Path(
            "/home/test/.gemini/oauth_creds.json"
        )
        assert connector._last_modified == 1234567890

    @patch("pathlib.Path.home")
    @patch("pathlib.Path.exists")
    def test_load_oauth_credentials_file_not_found(
        self, mock_exists, mock_home, connector
    ):
        """Test loading OAuth credentials when file doesn't exist."""
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = False

        result = asyncio.run(connector._load_oauth_credentials())

        assert result is False
        assert connector._oauth_credentials is None

    @patch("pathlib.Path.home")
    @patch("pathlib.Path.exists")
    @patch("builtins.open")
    def test_load_oauth_credentials_invalid_json(
        self, mock_open, mock_exists, mock_home, connector
    ):
        """Test loading OAuth credentials with invalid JSON."""
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = True

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.__exit__.return_value = None
        mock_open.return_value = mock_file
        mock_file.read.return_value = "invalid json"

        result = asyncio.run(connector._load_oauth_credentials())

        assert result is False
        assert connector._oauth_credentials is None

    @patch("pathlib.Path.home")
    @patch("pathlib.Path.exists")
    @patch("builtins.open")
    def test_load_oauth_credentials_missing_access_token(
        self, mock_open, mock_exists, mock_home, connector
    ):
        """Test loading OAuth credentials missing access_token."""
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = True

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.__exit__.return_value = None
        mock_open.return_value = mock_file

        test_credentials = {
            "refresh_token": "test_refresh_token",
            "expiry_date": 1756204339476,
            # Missing access_token
        }
        mock_file.read.return_value = json.dumps(test_credentials)

        result = asyncio.run(connector._load_oauth_credentials())

        assert result is False
        assert connector._oauth_credentials is None

    @patch("pathlib.Path.home")
    @patch("pathlib.Path.exists")
    @patch("builtins.open")
    @patch("pathlib.Path.mkdir")
    def test_save_oauth_credentials(
        self, mock_mkdir, mock_open, mock_exists, mock_home, connector
    ):
        """Test saving OAuth credentials."""
        mock_home.return_value = Path("/home/test")
        mock_exists.return_value = True

        mock_file = MagicMock()
        mock_file.__enter__.return_value = mock_file
        mock_file.__exit__.return_value = None
        mock_open.return_value = mock_file

        test_credentials = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expiry_date": 1756204339476,
        }

        asyncio.run(connector._save_oauth_credentials(test_credentials))

        # Verify that open was called with the correct path
        expected_path = Path("/home/test/.gemini/oauth_creds.json")
        mock_open.assert_called_once_with(expected_path, "w", encoding="utf-8")

        # Verify that json.dump wrote the credentials
        # json.dump calls write multiple times, so we need to collect all calls
        write_calls = [call[0][0] for call in mock_file.write.call_args_list]
        written_content = "".join(write_calls)
        assert json.loads(written_content) == test_credentials

    @patch.object(
        GeminiOAuthPersonalConnector, "_load_oauth_credentials", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    @patch.object(GeminiOAuthPersonalConnector, "_is_token_expired", return_value=False)
    @patch.object(
        GeminiOAuthPersonalConnector,
        "_validate_credentials_file_exists",
        return_value=(True, []),
    )
    @patch.object(
        GeminiOAuthPersonalConnector,
        "_validate_credentials_structure",
        return_value=(True, []),
    )
    @patch.object(GeminiOAuthPersonalConnector, "_start_file_watching")
    async def test_initialize_success(
        self,
        mock_start_watching,
        mock_validate_structure,
        mock_validate_file,
        mock_is_token_expired,
        mock_refresh,
        mock_load,
        connector,
    ):
        """Test successful initialization."""
        mock_load.return_value = True
        mock_refresh.return_value = True
        connector._oauth_credentials = {"access_token": "test_token"}

        await connector.initialize()

        assert connector.is_functional is True
        mock_validate_file.assert_called_once()
        mock_load.assert_called_once()
        mock_validate_structure.assert_called_once()
        mock_refresh.assert_called_once()
        mock_start_watching.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_load_oauth_credentials", new_callable=AsyncMock
    )
    async def test_initialize_load_failure(self, mock_load, connector):
        """Test initialization when credential loading fails."""
        mock_load.return_value = False

        await connector.initialize()

        assert connector.is_functional is False

    @patch.object(
        GeminiOAuthPersonalConnector, "_load_oauth_credentials", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector,
        "_validate_credentials_structure",
        return_value=(True, []),
    )
    @patch.object(
        GeminiOAuthPersonalConnector,
        "_validate_credentials_file_exists",
        return_value=(True, []),
    )
    @patch.object(GeminiOAuthPersonalConnector, "_start_file_watching")
    async def test_initialize_refresh_failure(
        self,
        mock_start_watching,
        mock_validate_file,
        mock_validate_structure,
        mock_refresh,
        mock_load,
        connector,
    ):
        """Test initialization when token refresh fails."""
        mock_load.return_value = True
        mock_refresh.return_value = False
        connector._oauth_credentials = {"access_token": "stale"}

        await connector.initialize()

        assert connector.is_functional is False
        assert connector._initialization_failed is False
        mock_start_watching.assert_called_once()
        assert connector.get_validation_errors() == [
            "OAuth token refresh pending; Gemini CLI background refresh was triggered."
        ]

    def test_recover_clears_initialization_failure(self, connector):
        """Recover should reset initialization failure flag."""
        connector._initialization_failed = True
        connector._recover()

        assert connector._initialization_failed is False

    async def test_resolve_gemini_api_config_no_credentials(self, connector):
        """Test resolving API config when no credentials are available."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await connector._resolve_gemini_api_config(None, None, None)

    async def test_resolve_gemini_api_config_with_credentials(self, connector):
        """Test resolving API config with valid credentials."""
        connector._oauth_credentials = {"access_token": "test_token"}

        base_url, headers = await connector._resolve_gemini_api_config(
            "https://test.api.com", None, None
        )

        assert base_url == "https://test.api.com"
        assert headers == {"Authorization": "Bearer test_token"}

    async def test_resolve_gemini_api_config_with_api_key_falls_back_to_oauth(
        self, connector
    ):
        """Test that API key is ignored in favor of OAuth token."""
        connector._oauth_credentials = {"access_token": "oauth_token"}

        base_url, headers = await connector._resolve_gemini_api_config(
            "https://test.api.com", None, "api_key_value"
        )

        assert base_url == "https://test.api.com"
        assert headers == {"Authorization": "Bearer oauth_token"}

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    async def test_perform_health_check_success(self, mock_refresh, connector):
        """Test successful health check."""
        # Setup
        connector.gemini_api_base_url = "https://test.api.com"
        connector._oauth_credentials = {"access_token": "test_token"}

        mock_response_data = {
            "models": [{"name": "gemini-pro"}, {"name": "gemini-pro-vision"}]
        }

        import json
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_response.text = json.dumps(mock_response_data)

        with patch.object(connector, "client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_refresh.return_value = True

            # Test
            result = await connector._perform_health_check()

            assert result is True
            mock_client.get.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    async def test_perform_health_check_no_models(self, mock_refresh, connector):
        """Test health check with empty response from Code Assist API."""
        # Setup
        connector.gemini_api_base_url = "https://test.api.com"
        connector._oauth_credentials = {"access_token": "test_token"}

        # Code Assist API returns user settings, not models
        mock_response_data = {}

        import json
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_response_data
        mock_response.text = json.dumps(mock_response_data)

        with patch.object(connector, "client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_refresh.return_value = True

            # Test - Code Assist API should succeed with any valid response
            result = await connector._perform_health_check()

            assert result is True  # Empty response from Code Assist API is still valid
            mock_client.get.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    async def test_perform_health_check_authentication_error(
        self, mock_refresh, connector
    ):
        """Test health check when authentication fails."""

        # Setup
        connector.gemini_api_base_url = "https://test.api.com"
        connector._oauth_credentials = {"access_token": "test_token"}

        import json
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": {"message": "Invalid token"}}
        mock_response.text = json.dumps({"error": {"message": "Invalid token"}})

        with patch.object(connector, "client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_refresh.return_value = True

            # Test
            result = await connector._perform_health_check()

            assert result is False
            mock_client.get.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    async def test_perform_health_check_backend_error(self, mock_refresh, connector):
        """Test health check when backend error occurs."""

        # Setup
        connector.gemini_api_base_url = "https://test.api.com"
        connector._oauth_credentials = {"access_token": "test_token"}

        import json
        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": {"message": "API error"}}
        mock_response.text = json.dumps({"error": {"message": "API error"}})

        with patch.object(connector, "client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_refresh.return_value = True

            # Test
            result = await connector._perform_health_check()

            assert result is False
            mock_client.get.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    async def test_perform_health_check_unexpected_error(self, mock_refresh, connector):
        """Test health check when unexpected error occurs."""
        # Setup
        connector.gemini_api_base_url = "https://test.i.com"
        connector._oauth_credentials = {"access_token": "test_token"}

        with patch.object(connector, "client") as mock_client:
            mock_client.get = AsyncMock(side_effect=Exception("Unexpected error"))
            mock_refresh.return_value = True

            # Test
            result = await connector._perform_health_check()

            assert result is False
            mock_client.get.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector, "_perform_health_check", new_callable=AsyncMock
    )
    async def test_ensure_healthy_first_time(
        self, mock_health_check, mock_refresh, connector
    ):
        """Test that _ensure_healthy performs health check on first call."""
        # Setup
        mock_refresh.return_value = True
        mock_health_check.return_value = True

        # Test - first call should perform health check
        await connector._ensure_healthy()

        assert connector._health_checked is True
        mock_refresh.assert_called_once()
        mock_health_check.assert_called_once()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector, "_perform_health_check", new_callable=AsyncMock
    )
    async def test_ensure_healthy_subsequent_calls(
        self, mock_health_check, mock_refresh, connector
    ):
        """Test that _ensure_healthy skips health check on subsequent calls."""
        # Setup
        connector._health_checked = True
        mock_refresh.return_value = True
        mock_health_check.return_value = True

        # Test - subsequent calls should not perform health check
        await connector._ensure_healthy()

        mock_refresh.assert_not_called()
        mock_health_check.assert_not_called()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector, "_perform_health_check", new_callable=AsyncMock
    )
    async def test_ensure_healthy_token_refresh_failure(
        self, mock_health_check, mock_refresh, connector
    ):
        """Test that _ensure_healthy raises error when token refresh fails."""
        from src.core.common.exceptions import BackendError

        # Setup
        mock_refresh.return_value = False
        mock_health_check.return_value = True

        # Test
        with pytest.raises(BackendError, match="Failed to refresh OAuth token"):
            await connector._ensure_healthy()

        mock_refresh.assert_called_once()
        mock_health_check.assert_not_called()

    @patch.object(
        GeminiOAuthPersonalConnector, "_refresh_token_if_needed", new_callable=AsyncMock
    )
    @patch.object(
        GeminiOAuthPersonalConnector, "_perform_health_check", new_callable=AsyncMock
    )
    async def test_ensure_healthy_health_check_failure(
        self, mock_health_check, mock_refresh, connector
    ):
        """Test that _ensure_healthy continues with warning when health check fails."""
        # Setup
        mock_refresh.return_value = True
        mock_health_check.return_value = False

        # Test - should not raise, just log warning
        await connector._ensure_healthy()

        # Verify both refresh and health check were called
        mock_refresh.assert_called_once()
        mock_health_check.assert_called_once()

        # Verify backend is marked as healthy despite failed health check
        assert connector._health_checked

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_refresh_token_if_needed_triggers_cli_on_expiring(
        self, mock_sleep, connector
    ):
        """Token close to expiry should schedule CLI refresh while remaining valid."""
        mock_sleep.return_value = None
        connector._oauth_credentials = {
            "access_token": "token",
            "expiry_date": (time.time() + 90) * 1000,
        }

        with (
            patch.object(
                connector, "_load_oauth_credentials", new_callable=AsyncMock
            ) as mock_load,
            patch.object(connector, "_launch_cli_refresh_process") as mock_launch,
        ):
            mock_load.return_value = True

            result = await connector._refresh_token_if_needed()

        assert result is True
        mock_launch.assert_called_once()
        mock_load.assert_not_called()

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_refresh_token_if_needed_attempts_cli_on_expired(
        self, mock_sleep, connector
    ):
        """Expired token should attempt reload and spawn CLI refresh."""
        mock_sleep.return_value = None
        expired_time = (time.time() - 5) * 1000

        async def load_side_effect():
            load_side_effect.counter += 1
            if load_side_effect.counter < 3:
                connector._oauth_credentials = {
                    "access_token": "token",
                    "expiry_date": expired_time,
                }
            else:
                connector._oauth_credentials = {
                    "access_token": "fresh",
                    "expiry_date": (time.time() + 3600) * 1000,
                }
            return True

        load_side_effect.counter = 0

        connector._oauth_credentials = {
            "access_token": "token",
            "expiry_date": expired_time,
        }

        with (
            patch.object(
                connector, "_load_oauth_credentials", new_callable=AsyncMock
            ) as mock_load,
            patch.object(connector, "_launch_cli_refresh_process") as mock_launch,
        ):
            mock_load.side_effect = load_side_effect

            result = await connector._refresh_token_if_needed()

        assert result is True
        assert mock_launch.call_count == 1
        assert load_side_effect.counter >= 3

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_refresh_token_if_needed_fails_when_cli_refresh_never_updates(
        self, mock_sleep, connector
    ):
        """Expired token remains invalid if CLI refresh does not update file."""
        mock_sleep.return_value = None
        expired_time = (time.time() - 5) * 1000
        connector._oauth_credentials = {
            "access_token": "token",
            "expiry_date": expired_time,
        }

        async def load_side_effect():
            connector._oauth_credentials = {
                "access_token": "token",
                "expiry_date": expired_time,
            }
            return True

        with (
            patch.object(
                connector, "_load_oauth_credentials", new_callable=AsyncMock
            ) as mock_load,
            patch.object(connector, "_launch_cli_refresh_process") as mock_launch,
        ):
            mock_load.side_effect = load_side_effect

            result = await connector._refresh_token_if_needed()

        assert result is False
        mock_launch.assert_called_once()


class TestFileWatchingFunctionality:
    """Test file watching functionality for credential changes."""

    def test_start_file_watching_success(self, connector):
        """Test file watching starts successfully when credentials path exists."""
        from pathlib import Path
        from unittest.mock import Mock, patch

        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")

        with patch(
            "src.connectors.gemini_oauth_personal.Observer"
        ) as mock_observer_class:
            mock_observer = Mock()
            mock_observer_class.return_value = mock_observer

            connector._start_file_watching()

            assert connector._file_observer is not None
            mock_observer.schedule.assert_called_once()
            mock_observer.start.assert_called_once()

    def test_start_file_watching_no_credentials_path(self, connector):
        """Test file watching doesn't start when credentials path is None."""
        from unittest.mock import patch

        connector._credentials_path = None

        with patch(
            "src.connectors.gemini_oauth_personal.Observer"
        ) as mock_observer_class:
            connector._start_file_watching()

            assert connector._file_observer is None
            mock_observer_class.assert_not_called()

    def test_stop_file_watching_success(self, connector):
        """Test file watching stops successfully."""
        from unittest.mock import Mock

        mock_observer = Mock()
        connector._file_observer = mock_observer

        connector._stop_file_watching()

        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once()
        assert connector._file_observer is None

    def test_stop_file_watching_no_observer(self, connector):
        """Test stop file watching when no observer exists."""
        connector._file_observer = None

        # Should not raise any exception
        connector._stop_file_watching()

        assert connector._file_observer is None

    @pytest.mark.asyncio
    async def test_handle_credentials_file_change_valid_update(self, connector):
        """Test handling of valid credentials file change with force reload."""
        from pathlib import Path
        from unittest.mock import patch

        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")

        # Mock that credentials exist and are valid
        with (
            patch.object(
                connector, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                connector, "_load_oauth_credentials", new_callable=AsyncMock
            ) as mock_load,
            patch.object(
                connector, "_refresh_token_if_needed", new_callable=AsyncMock
            ) as mock_refresh,
        ):
            mock_load.return_value = True
            mock_refresh.return_value = True

            await connector._handle_credentials_file_change()

            # Verify force_reload was used
            mock_load.assert_called_once_with(force_reload=True)
            mock_refresh.assert_called_once()
            assert connector.is_functional
            assert len(connector._credential_validation_errors) == 0

    @pytest.mark.asyncio
    async def test_handle_credentials_file_change_invalid_file(self, connector):
        """Test handling of invalid credentials file change."""
        from pathlib import Path
        from unittest.mock import patch

        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")

        # Mock that credentials file is invalid
        with patch.object(
            connector,
            "_validate_credentials_file_exists",
            return_value=(False, ["File is corrupted"]),
        ):
            await connector._handle_credentials_file_change()

            assert not connector.is_functional
            assert len(connector._credential_validation_errors) > 0
            assert "File is corrupted" in connector._credential_validation_errors

    @pytest.mark.asyncio
    async def test_handle_credentials_file_change_load_failure(self, connector):
        """Test handling when credential loading fails after file change."""
        from pathlib import Path
        from unittest.mock import patch

        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")

        with (
            patch.object(
                connector, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                connector, "_load_oauth_credentials", new_callable=AsyncMock
            ) as mock_load,
        ):
            mock_load.return_value = False

            await connector._handle_credentials_file_change()

            assert not connector.is_functional
            assert len(connector._credential_validation_errors) > 0

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_with_force_reload(self, connector):
        """Test that force_reload bypasses cache check."""
        import json
        import time
        from pathlib import Path
        from unittest.mock import MagicMock, mock_open, patch

        test_credentials = {
            "access_token": "new_token",
            "refresh_token": "refresh_token",
            "expiry_date": (time.time() + 3600) * 1000,
        }

        # Set up connector with cached credentials and last_modified time
        connector._oauth_credentials = {
            "access_token": "old_token",
            "refresh_token": "old_refresh",
            "expiry_date": (time.time() + 3600) * 1000,
        }
        connector._last_modified = 1234567890
        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")

        with (
            patch("pathlib.Path.home", return_value=Path("/test")),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("builtins.open", mock_open(read_data=json.dumps(test_credentials))),
        ):
            # Same mtime as cached
            mock_stat.return_value = MagicMock(st_mtime=1234567890)

            # Without force_reload, should use cache
            result = await connector._load_oauth_credentials(force_reload=False)
            assert result is True
            assert connector._oauth_credentials["access_token"] == "old_token"

            # With force_reload, should reload from file
            result = await connector._load_oauth_credentials(force_reload=True)
            assert result is True
            assert connector._oauth_credentials["access_token"] == "new_token"

    def test_file_handler_on_modified_path_comparison(self, connector):
        """Test that file handler properly compares paths on Windows and Unix."""
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from src.connectors.gemini_oauth_personal import (
            GeminiPersonalCredentialsFileHandler,
        )

        # Set up connector with credentials path
        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")
        connector._main_loop = MagicMock()

        handler = GeminiPersonalCredentialsFileHandler(connector)

        # Create mock event with path that should match
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(connector._credentials_path)

        with patch(
            "asyncio.run_coroutine_threadsafe", return_value=MagicMock()
        ) as mock_run:
            handler.on_modified(event)

            # Should have scheduled the credentials reload
            mock_run.assert_called_once()

    def test_file_handler_on_modified_different_file(self, connector):
        """Test that file handler ignores events for different files."""
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from src.connectors.gemini_oauth_personal import (
            GeminiPersonalCredentialsFileHandler,
        )

        # Set up connector with credentials path
        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")
        connector._main_loop = MagicMock()

        handler = GeminiPersonalCredentialsFileHandler(connector)

        # Create mock event with different path
        event = MagicMock()
        event.is_directory = False
        event.src_path = "/test/.gemini/other_file.json"

        with patch(
            "asyncio.run_coroutine_threadsafe", return_value=MagicMock()
        ) as mock_run:
            handler.on_modified(event)

            # Should NOT have scheduled the credentials reload
            mock_run.assert_not_called()

    def test_file_handler_on_modified_no_event_loop(self, connector):
        """Test that file handler handles missing event loop gracefully."""
        from pathlib import Path
        from unittest.mock import MagicMock

        from src.connectors.gemini_oauth_personal import (
            GeminiPersonalCredentialsFileHandler,
        )

        # Set up connector without event loop
        connector._credentials_path = Path("/test/.gemini/oauth_creds.json")
        connector._main_loop = None

        handler = GeminiPersonalCredentialsFileHandler(connector)

        # Create mock event
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(connector._credentials_path)

        # Should not raise exception even without event loop
        handler.on_modified(event)
