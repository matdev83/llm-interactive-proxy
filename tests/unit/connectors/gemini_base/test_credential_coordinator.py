"""
Unit tests for GeminiCredentialCoordinator.

Tests verify credential lifecycle coordination including loading, validation,
refresh, and file watching.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.connectors.gemini_base.credential_coordinator import (
    GeminiCredentialCoordinator,
)
from src.connectors.gemini_base.file_watcher import FileWatcherState
from src.connectors.gemini_base.models import GeminiOAuthCredentials
from src.connectors.gemini_base.token_manager import TokenManager
from src.core.common.exceptions import AuthenticationError


@pytest.fixture
def mock_credential_loader():
    """Mock CredentialLoader static methods."""
    with patch(
        "src.connectors.gemini_base.credential_coordinator.CredentialLoader"
    ) as mock:
        yield mock


@pytest.fixture
def mock_file_watcher():
    """Mock FileWatcher static methods."""
    with patch("src.connectors.gemini_base.credential_coordinator.FileWatcher") as mock:
        yield mock


@pytest.fixture
def mock_token_manager():
    """Create a mock TokenManager."""
    manager = Mock(spec=TokenManager)
    manager.refresh_token_if_needed = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def coordinator(mock_token_manager):
    """Create a GeminiCredentialCoordinator instance."""
    return GeminiCredentialCoordinator(
        token_manager=mock_token_manager,
        file_watcher_state=FileWatcherState(),
    )


@pytest.fixture
def sample_credentials_dict():
    """Sample credentials dictionary."""
    return {
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
        "expiry_date": 9999999999999,  # Far future
        "project_id": "test-project",
    }


@pytest.fixture
def sample_credentials(sample_credentials_dict):
    """Sample GeminiOAuthCredentials instance."""
    return GeminiOAuthCredentials.from_dict(sample_credentials_dict)


class TestInitialize:
    """Test initialize method."""

    @pytest.mark.asyncio
    async def test_initialize_loads_credentials(
        self, coordinator, mock_credential_loader, sample_credentials_dict
    ):
        """Verify credentials are loaded on initialize."""
        # Setup mocks
        mock_credential_loader.validate_credentials_file_exists.return_value = (
            True,
            [],
            Path("/test/oauth_creds.json"),
        )
        mock_credential_loader.load_oauth_credentials = AsyncMock(return_value=True)

        # Mock storage object for load_oauth_credentials
        storage_mock = Mock()
        storage_mock._oauth_credentials = sample_credentials_dict
        storage_mock._credentials_path = Path("/test/oauth_creds.json")
        storage_mock._last_modified = 1234567890.0
        storage_mock.gemini_cli_oauth_path = None

        async def load_side_effect(storage, *args, **kwargs):
            storage._oauth_credentials = sample_credentials_dict
            return True

        mock_credential_loader.load_oauth_credentials.side_effect = load_side_effect
        mock_credential_loader.validate_credentials_structure.return_value = (True, [])

        # Execute
        await coordinator.initialize(gemini_cli_oauth_path=None)

        # Verify
        assert coordinator.credentials is not None
        assert coordinator.credentials.access_token == "test_access_token"
        mock_credential_loader.validate_credentials_file_exists.assert_called_once()
        mock_credential_loader.load_oauth_credentials.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_validates_credentials(
        self, coordinator, mock_credential_loader, sample_credentials_dict
    ):
        """Verify validation is performed."""
        # Setup mocks
        mock_credential_loader.validate_credentials_file_exists.return_value = (
            True,
            [],
            Path("/test/oauth_creds.json"),
        )

        storage_mock = Mock()
        storage_mock._oauth_credentials = sample_credentials_dict
        storage_mock._credentials_path = Path("/test/oauth_creds.json")
        storage_mock._last_modified = 1234567890.0
        storage_mock.gemini_cli_oauth_path = None

        async def load_side_effect(storage, *args, **kwargs):
            storage._oauth_credentials = sample_credentials_dict
            return True

        mock_credential_loader.load_oauth_credentials.side_effect = load_side_effect
        mock_credential_loader.validate_credentials_structure.return_value = (True, [])

        # Execute
        await coordinator.initialize(gemini_cli_oauth_path=None)

        # Verify validation was called
        mock_credential_loader.validate_credentials_structure.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_refreshes_if_needed(
        self,
        coordinator,
        mock_credential_loader,
        mock_token_manager,
        sample_credentials_dict,
    ):
        """Verify token refresh is triggered when expired."""
        # Setup mocks
        mock_credential_loader.validate_credentials_file_exists.return_value = (
            True,
            [],
            Path("/test/oauth_creds.json"),
        )

        storage_mock = Mock()
        storage_mock._oauth_credentials = sample_credentials_dict
        storage_mock._credentials_path = Path("/test/oauth_creds.json")
        storage_mock._last_modified = 1234567890.0
        storage_mock.gemini_cli_oauth_path = None

        async def load_side_effect(storage, *args, **kwargs):
            storage._oauth_credentials = sample_credentials_dict
            return True

        mock_credential_loader.load_oauth_credentials.side_effect = load_side_effect
        mock_credential_loader.validate_credentials_structure.return_value = (True, [])
        mock_token_manager.refresh_token_if_needed.return_value = True

        # Execute
        await coordinator.initialize(gemini_cli_oauth_path=None)

        # Verify refresh was called
        mock_token_manager.refresh_token_if_needed.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_starts_file_watching(
        self,
        coordinator,
        mock_credential_loader,
        mock_file_watcher,
        sample_credentials_dict,
    ):
        """Verify file watcher is started."""
        # Setup mocks
        mock_credential_loader.validate_credentials_file_exists.return_value = (
            True,
            [],
            Path("/test/oauth_creds.json"),
        )

        storage_mock = Mock()
        storage_mock._oauth_credentials = sample_credentials_dict
        storage_mock._credentials_path = Path("/test/oauth_creds.json")
        storage_mock._last_modified = 1234567890.0
        storage_mock.gemini_cli_oauth_path = None

        async def load_side_effect(storage, *args, **kwargs):
            storage._oauth_credentials = sample_credentials_dict
            return True

        mock_credential_loader.load_oauth_credentials.side_effect = load_side_effect
        mock_credential_loader.validate_credentials_structure.return_value = (True, [])

        # Set main loop
        coordinator._file_watcher_state.main_loop = asyncio.get_running_loop()

        # Execute
        await coordinator.initialize(gemini_cli_oauth_path=None)

        # Verify file watcher was started
        mock_file_watcher.start_file_watching.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_handles_missing_file_gracefully(
        self, coordinator, mock_credential_loader
    ):
        """Verify error handling for missing file."""
        # Setup mocks
        mock_credential_loader.validate_credentials_file_exists.return_value = (
            False,
            ["OAuth credentials file not found"],
            None,
        )

        # Execute and verify exception
        with pytest.raises(AuthenticationError) as exc_info:
            await coordinator.initialize(gemini_cli_oauth_path=None)

        assert "credentials file not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_initialize_handles_invalid_credentials(
        self, coordinator, mock_credential_loader, sample_credentials_dict
    ):
        """Verify validation errors are raised."""
        # Setup mocks
        mock_credential_loader.validate_credentials_file_exists.return_value = (
            True,
            [],
            Path("/test/oauth_creds.json"),
        )

        storage_mock = Mock()
        storage_mock._oauth_credentials = sample_credentials_dict
        storage_mock._credentials_path = Path("/test/oauth_creds.json")
        storage_mock._last_modified = 1234567890.0
        storage_mock.gemini_cli_oauth_path = None

        async def load_side_effect(storage, *args, **kwargs):
            storage._oauth_credentials = sample_credentials_dict
            return True

        mock_credential_loader.load_oauth_credentials.side_effect = load_side_effect
        mock_credential_loader.validate_credentials_structure.return_value = (
            False,
            ["Missing required field: access_token"],
        )

        # Execute and verify exception
        with pytest.raises(AuthenticationError) as exc_info:
            await coordinator.initialize(gemini_cli_oauth_path=None)

        assert "access_token" in exc_info.value.message.lower()


class TestValidateRuntime:
    """Test validate_runtime method."""

    @pytest.mark.asyncio
    async def test_validate_runtime_returns_true_when_valid(
        self, coordinator, mock_token_manager, sample_credentials
    ):
        """Verify runtime validation returns True for valid credentials."""
        # Set credentials
        coordinator._credentials = sample_credentials
        mock_token_manager.is_token_expired.return_value = False

        # Execute
        result = await coordinator.validate_runtime()

        # Verify
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_runtime_returns_false_when_expired(
        self, coordinator, mock_token_manager
    ):
        """Verify expired token detection."""
        # Set expired credentials
        expired_creds = GeminiOAuthCredentials(
            access_token="expired_token",
            refresh_token="refresh_token",
            expiry_date=1000,  # Past timestamp
        )
        coordinator._credentials = expired_creds
        mock_token_manager.is_token_expired.return_value = True

        # Execute
        result = await coordinator.validate_runtime()

        # Verify
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_runtime_returns_false_when_no_credentials(
        self, coordinator
    ):
        """Verify False when credentials are None."""
        coordinator._credentials = None

        # Execute
        result = await coordinator.validate_runtime()

        # Verify
        assert result is False


class TestRefreshIfNeeded:
    """Test refresh_if_needed method."""

    @pytest.mark.asyncio
    async def test_refresh_if_needed_refreshes_expired_token(
        self, coordinator, mock_token_manager, sample_credentials_dict
    ):
        """Verify refresh logic for expired tokens."""
        # Setup
        coordinator._credentials = GeminiOAuthCredentials.from_dict(
            sample_credentials_dict
        )
        coordinator._storage = Mock()
        coordinator._storage._oauth_credentials = sample_credentials_dict
        coordinator._storage._load_oauth_credentials = AsyncMock(return_value=True)

        mock_token_manager.refresh_token_if_needed.return_value = True

        # Execute
        result = await coordinator.refresh_if_needed(force_reload=False)

        # Verify
        assert result is True
        mock_token_manager.refresh_token_if_needed.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_if_needed_skips_when_valid(
        self, coordinator, mock_token_manager, sample_credentials
    ):
        """Verify no-op for valid tokens."""
        # Setup
        coordinator._credentials = sample_credentials
        coordinator._storage = Mock()
        mock_token_manager.is_token_expired.return_value = False
        mock_token_manager.refresh_token_if_needed.return_value = True

        # Execute
        result = await coordinator.refresh_if_needed(force_reload=False)

        # Verify
        assert result is True


class TestCredentialsProperty:
    """Test credentials property."""

    def test_credentials_property_returns_typed_model(
        self, coordinator, sample_credentials
    ):
        """Verify GeminiOAuthCredentials return."""
        coordinator._credentials = sample_credentials

        result = coordinator.credentials

        assert isinstance(result, GeminiOAuthCredentials)
        assert result.access_token == "test_access_token"

    def test_credentials_property_returns_none_when_not_loaded(self, coordinator):
        """Verify None when credentials not loaded."""
        coordinator._credentials = None

        result = coordinator.credentials

        assert result is None
