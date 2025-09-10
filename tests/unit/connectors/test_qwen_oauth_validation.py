"""
Comprehensive unit tests for Qwen OAuth credential validation logic.

Tests all the enhanced OAuth credential validation features:
1. Startup validation (file existence, structure, expiry)
2. Backend health status tracking
3. File watching functionality
4. Runtime token validation and reloading
5. Descriptive error responses
6. Startup failure handling
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig


class TestQwenOAuthCredentialValidation:
    """Test class for comprehensive OAuth credential validation."""

    @pytest.fixture
    def mock_config(self) -> AppConfig:
        """Create a mock AppConfig for testing."""
        return AppConfig()

    @pytest.fixture
    def mock_client(self) -> httpx.AsyncClient:
        """Create a mock HTTP client."""
        return AsyncMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(
        self, mock_client: httpx.AsyncClient, mock_config: AppConfig
    ) -> QwenOAuthConnector:
        """Create a QwenOAuthConnector instance for testing."""
        return QwenOAuthConnector(mock_client, mock_config)

    @pytest.fixture
    def temp_credentials_dir(self) -> Path:
        """Create a temporary directory for OAuth credentials testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            credentials_dir = Path(temp_dir) / ".qwen"
            credentials_dir.mkdir(parents=True, exist_ok=True)
            yield credentials_dir

    @pytest.fixture
    def valid_credentials(self) -> dict[str, any]:
        """Create valid OAuth credentials for testing."""
        # Token expires 1 hour from now
        expiry_time = int((time.time() + 3600) * 1000)  # Convert to milliseconds
        return {
            "access_token": "valid_access_token_123",
            "refresh_token": "valid_refresh_token_456",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": expiry_time,
        }

    @pytest.fixture
    def expired_credentials(self) -> dict[str, any]:
        """Create expired OAuth credentials for testing."""
        # Token expired 1 hour ago
        expiry_time = int((time.time() - 3600) * 1000)  # Convert to milliseconds
        return {
            "access_token": "expired_access_token_123",
            "refresh_token": "expired_refresh_token_456",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": expiry_time,
        }

    def create_credentials_file(self, credentials_dir: Path, credentials: dict) -> Path:
        """Helper to create a credentials file with given content."""
        creds_file = credentials_dir / "oauth_creds.json"
        with open(creds_file, "w", encoding="utf-8") as f:
            json.dump(credentials, f, indent=2)
        return creds_file


class TestStartupValidation(TestQwenOAuthCredentialValidation):
    """Test startup validation of OAuth credentials."""

    def test_validate_credentials_file_exists_missing_file(
        self, connector: QwenOAuthConnector
    ):
        """Test validation fails when credentials file doesn't exist."""
        with patch.object(Path, "home", return_value=Path("/nonexistent")):
            is_valid, errors = connector._validate_credentials_file_exists()

            assert not is_valid
            assert len(errors) == 1
            assert "OAuth credentials file not found" in errors[0]

    def test_validate_credentials_file_exists_invalid_json(
        self, connector: QwenOAuthConnector, temp_credentials_dir: Path
    ):
        """Test validation fails when credentials file contains invalid JSON."""
        # Create file with invalid JSON
        creds_file = temp_credentials_dir / "oauth_creds.json"
        with open(creds_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json }")

        with patch.object(Path, "home", return_value=temp_credentials_dir.parent):
            is_valid, errors = connector._validate_credentials_file_exists()

            assert not is_valid
            assert len(errors) == 1
            assert "Invalid JSON in credentials file" in errors[0]

    def test_validate_credentials_structure_missing_fields(
        self, connector: QwenOAuthConnector
    ):
        """Test validation fails when required fields are missing."""
        incomplete_credentials = {
            "access_token": "token123"
            # Missing refresh_token
        }

        is_valid, errors = connector._validate_credentials_structure(
            incomplete_credentials
        )

        assert not is_valid
        assert len(errors) == 1
        assert "Missing required field: refresh_token" in errors[0]

    def test_validate_credentials_structure_empty_fields(
        self, connector: QwenOAuthConnector
    ):
        """Test validation fails when required fields are empty."""
        credentials_with_empty_fields = {
            "access_token": "",
            "refresh_token": "refresh123",
        }

        is_valid, errors = connector._validate_credentials_structure(
            credentials_with_empty_fields
        )

        assert not is_valid
        assert len(errors) == 1
        assert "Invalid access_token: must be a non-empty string" in errors[0]

    def test_validate_credentials_structure_expired_token(
        self, connector: QwenOAuthConnector, expired_credentials: dict
    ):
        """Test validation fails when token is expired."""
        is_valid, errors = connector._validate_credentials_structure(
            expired_credentials
        )

        assert not is_valid
        assert len(errors) == 1
        assert "Token expired at" in errors[0]

    def test_validate_credentials_structure_valid_credentials(
        self, connector: QwenOAuthConnector, valid_credentials: dict
    ):
        """Test validation passes with valid credentials."""
        is_valid, errors = connector._validate_credentials_structure(valid_credentials)

        assert is_valid
        assert len(errors) == 0

    def test_validate_credentials_file_exists_valid_file(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        valid_credentials: dict,
    ):
        """Test validation passes when credentials file is valid."""
        self.create_credentials_file(temp_credentials_dir, valid_credentials)

        with patch.object(Path, "home", return_value=temp_credentials_dir.parent):
            is_valid, errors = connector._validate_credentials_file_exists()

            assert is_valid
            assert len(errors) == 0


class TestBackendHealthTracking(TestQwenOAuthCredentialValidation):
    """Test backend health status tracking."""

    def test_is_backend_functional_with_valid_state(
        self, connector: QwenOAuthConnector
    ):
        """Test backend is functional when all conditions are met."""
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []

        assert connector.is_backend_functional()

    def test_is_backend_functional_with_initialization_failed(
        self, connector: QwenOAuthConnector
    ):
        """Test backend is not functional when initialization failed."""
        connector.is_functional = True
        connector._initialization_failed = True
        connector._credential_validation_errors = []

        assert not connector.is_backend_functional()

    def test_is_backend_functional_with_validation_errors(
        self, connector: QwenOAuthConnector
    ):
        """Test backend is not functional when validation errors exist."""
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = ["Token expired"]

        assert not connector.is_backend_functional()

    def test_is_backend_functional_not_functional(self, connector: QwenOAuthConnector):
        """Test backend is not functional when is_functional is False."""
        connector.is_functional = False
        connector._initialization_failed = False
        connector._credential_validation_errors = []

        assert not connector.is_backend_functional()

    def test_get_validation_errors(self, connector: QwenOAuthConnector):
        """Test getting validation errors returns a copy."""
        errors = ["Error 1", "Error 2"]
        connector._credential_validation_errors = errors

        returned_errors = connector.get_validation_errors()

        assert returned_errors == errors
        assert returned_errors is not errors  # Should be a copy


class TestInitializationValidation(TestQwenOAuthCredentialValidation):
    """Test comprehensive initialization validation."""

    @pytest.mark.asyncio
    async def test_initialize_missing_credentials_file(
        self, connector: QwenOAuthConnector
    ):
        """Test initialization fails when credentials file is missing."""
        with patch.object(Path, "home", return_value=Path("/nonexistent")):
            await connector.initialize()

            assert not connector.is_functional
            assert connector._initialization_failed
            assert len(connector._credential_validation_errors) > 0
            assert (
                "OAuth credentials file not found"
                in connector._credential_validation_errors[0]
            )

    @pytest.mark.asyncio
    async def test_initialize_expired_credentials(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        expired_credentials: dict,
    ):
        """Test initialization fails when credentials are expired."""
        self.create_credentials_file(temp_credentials_dir, expired_credentials)

        with patch.object(Path, "home", return_value=temp_credentials_dir.parent):
            await connector.initialize()

            assert not connector.is_functional
            assert connector._initialization_failed
            assert len(connector._credential_validation_errors) > 0
            assert "Token expired" in connector._credential_validation_errors[0]

    @pytest.mark.asyncio
    async def test_initialize_valid_credentials(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        valid_credentials: dict,
    ):
        """Test initialization succeeds with valid credentials."""
        self.create_credentials_file(temp_credentials_dir, valid_credentials)

        with (
            patch.object(Path, "home", return_value=temp_credentials_dir.parent),
            patch.object(connector, "_refresh_token_if_needed", return_value=True),
            patch.object(connector, "_start_file_watching"),
        ):
            await connector.initialize()

            assert connector.is_functional
            assert not connector._initialization_failed
            assert len(connector._credential_validation_errors) == 0

    @pytest.mark.asyncio
    async def test_initialize_token_refresh_failure(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        valid_credentials: dict,
    ):
        """Test initialization fails when token refresh fails."""
        self.create_credentials_file(temp_credentials_dir, valid_credentials)

        with patch.object(Path, "home", return_value=temp_credentials_dir.parent):
            # Mock token refresh to fail
            with patch.object(
                connector, "_refresh_token_if_needed", return_value=False
            ):
                await connector.initialize()

            assert not connector.is_functional
            assert connector._initialization_failed
            assert len(connector._credential_validation_errors) > 0
            assert (
                "Failed to refresh expired OAuth token"
                in connector._credential_validation_errors[0]
            )


class TestRuntimeValidation(TestQwenOAuthCredentialValidation):
    """Test runtime token validation and reloading."""

    @pytest.mark.asyncio
    async def test_validate_runtime_credentials_valid_token(
        self, connector: QwenOAuthConnector
    ):
        """Test runtime validation passes with valid token."""
        # Set up valid state
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []
        connector._last_validation_time = 0  # Force validation

        # Mock token as not expired
        with patch.object(connector, "_is_token_expired", return_value=False):
            result = await connector._validate_runtime_credentials()

            assert result is True

    @pytest.mark.asyncio
    async def test_validate_runtime_credentials_expired_token_reload_success(
        self, connector: QwenOAuthConnector
    ):
        """Test runtime validation handles expired token with successful reload."""
        # Set up initial state
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []
        connector._last_validation_time = 0  # Force validation

        # Mock token as expired initially, then valid after reload
        with (
            patch.object(connector, "_is_token_expired", side_effect=[True, False]),
            patch.object(connector, "_load_oauth_credentials", return_value=True),
        ):
            result = await connector._validate_runtime_credentials()

            assert result is True
            assert connector.is_functional
            assert len(connector._credential_validation_errors) == 0

    @pytest.mark.asyncio
    async def test_validate_runtime_credentials_expired_token_reload_still_expired(
        self, connector: QwenOAuthConnector
    ):
        """Test runtime validation handles expired token that remains expired after reload."""
        # Set up initial state
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []
        connector._last_validation_time = 0  # Force validation

        # Mock token as expired both before and after reload
        with (
            patch.object(connector, "_is_token_expired", return_value=True),
            patch.object(connector, "_load_oauth_credentials", return_value=True),
        ):
            result = await connector._validate_runtime_credentials()

            assert result is False
            assert not connector.is_functional
            assert (
                "Token expired and no valid replacement found"
                in connector._credential_validation_errors
            )

    @pytest.mark.asyncio
    async def test_validate_runtime_credentials_reload_failure(
        self, connector: QwenOAuthConnector
    ):
        """Test runtime validation handles failed credential reload."""
        # Set up initial state
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []
        connector._last_validation_time = 0  # Force validation

        # Mock token as expired and reload fails
        with (
            patch.object(connector, "_is_token_expired", return_value=True),
            patch.object(connector, "_load_oauth_credentials", return_value=False),
        ):
            result = await connector._validate_runtime_credentials()

            assert result is False
            assert not connector.is_functional
            assert (
                "Failed to reload expired credentials"
                in connector._credential_validation_errors
            )

    @pytest.mark.asyncio
    async def test_validate_runtime_credentials_throttling(
        self, connector: QwenOAuthConnector
    ):
        """Test runtime validation is throttled to avoid excessive checks."""
        # Set up valid state
        connector.is_functional = True
        connector._initialization_failed = False
        connector._credential_validation_errors = []
        connector._last_validation_time = time.time()  # Recent validation

        # Should not perform validation due to throttling
        with patch.object(connector, "_is_token_expired") as mock_expired:
            result = await connector._validate_runtime_credentials()

            assert result is True
            mock_expired.assert_not_called()  # Should not check expiry due to throttling


class TestErrorResponses(TestQwenOAuthCredentialValidation):
    """Test descriptive error responses when backend is non-functional."""

    @pytest.mark.asyncio
    async def test_chat_completions_non_functional_backend(
        self, connector: QwenOAuthConnector
    ):
        """Test chat_completions raises descriptive error when backend is non-functional."""
        # Set up non-functional state with specific errors
        connector.is_functional = False
        connector._credential_validation_errors = [
            "Token expired",
            "Invalid credentials",
        ]

        # Mock validation to return False
        with patch.object(
            connector, "_validate_runtime_credentials", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions({}, [], "test-model")

            assert exc_info.value.status_code == 502
            assert (
                "No valid OAuth credentials found for backend qwen-oauth"
                in exc_info.value.detail
            )
            assert "Token expired; Invalid credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_chat_completions_non_functional_backend_no_specific_errors(
        self, connector: QwenOAuthConnector
    ):
        """Test chat_completions error message when no specific errors are available."""
        # Set up non-functional state without specific errors
        connector.is_functional = False
        connector._credential_validation_errors = []

        # Mock validation to return False
        with patch.object(
            connector, "_validate_runtime_credentials", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions({}, [], "test-model")

            assert exc_info.value.status_code == 502
            assert (
                "No valid OAuth credentials found for backend qwen-oauth"
                in exc_info.value.detail
            )
            assert "Backend is not functional" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_chat_completions_token_refresh_failure(
        self, connector: QwenOAuthConnector
    ):
        """Test chat_completions error when token refresh fails."""
        # Mock validation to pass but refresh to fail
        with (
            patch.object(connector, "_validate_runtime_credentials", return_value=True),
            patch.object(connector, "_refresh_token_if_needed", return_value=False),
            pytest.raises(HTTPException) as exc_info,
        ):
            await connector.chat_completions({}, [], "test-model")

        assert exc_info.value.status_code == 401
        assert "Failed to refresh Qwen OAuth token" in exc_info.value.detail


class TestFileWatchingFunctionality(TestQwenOAuthCredentialValidation):
    """Test file watching functionality for credential changes."""

    def test_start_file_watching_success(
        self, connector: QwenOAuthConnector, temp_credentials_dir: Path
    ):
        """Test file watching starts successfully when credentials path exists."""
        connector._credentials_path = temp_credentials_dir / "oauth_creds.json"
        connector._credentials_path.touch()  # Create the file

        with patch("src.connectors.qwen_oauth.Observer") as mock_observer_class:
            mock_observer = Mock()
            mock_observer_class.return_value = mock_observer

            connector._start_file_watching()

            assert connector._file_observer is not None
            mock_observer.schedule.assert_called_once()
            mock_observer.start.assert_called_once()

    def test_start_file_watching_no_credentials_path(
        self, connector: QwenOAuthConnector
    ):
        """Test file watching doesn't start when credentials path is None."""
        connector._credentials_path = None

        with patch("src.connectors.qwen_oauth.Observer") as mock_observer_class:
            connector._start_file_watching()

            assert connector._file_observer is None
            mock_observer_class.assert_not_called()

    def test_stop_file_watching_success(self, connector: QwenOAuthConnector):
        """Test file watching stops successfully."""
        mock_observer = Mock()
        connector._file_observer = mock_observer

        connector._stop_file_watching()

        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once_with(timeout=5.0)
        assert connector._file_observer is None

    def test_stop_file_watching_no_observer(self, connector: QwenOAuthConnector):
        """Test stop_file_watching handles case when no observer exists."""
        connector._file_observer = None

        # Should not raise any exception
        connector._stop_file_watching()

        assert connector._file_observer is None

    @pytest.mark.asyncio
    async def test_handle_credentials_file_change_valid_update(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        valid_credentials: dict,
    ):
        """Test handling of valid credentials file change."""
        self.create_credentials_file(temp_credentials_dir, valid_credentials)

        with (
            patch.object(Path, "home", return_value=temp_credentials_dir.parent),
            patch.object(connector, "_load_oauth_credentials", return_value=True),
        ):
            await connector._handle_credentials_file_change()

            assert connector.is_functional
            assert len(connector._credential_validation_errors) == 0

    @pytest.mark.asyncio
    async def test_handle_credentials_file_change_invalid_update(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        expired_credentials: dict,
    ):
        """Test handling of invalid credentials file change."""
        self.create_credentials_file(temp_credentials_dir, expired_credentials)

        with patch.object(Path, "home", return_value=temp_credentials_dir.parent):
            await connector._handle_credentials_file_change()

            assert not connector.is_functional
            assert len(connector._credential_validation_errors) > 0
            assert "Token expired" in connector._credential_validation_errors[0]


class TestCleanupFunctionality(TestQwenOAuthCredentialValidation):
    """Test cleanup functionality."""

    def test_cleanup_on_destruction(self, connector: QwenOAuthConnector):
        """Test that file watching is stopped when connector is destroyed."""
        mock_observer = Mock()
        connector._file_observer = mock_observer

        # Test __del__ method
        with patch.object(connector, "_stop_file_watching") as mock_stop:
            connector.__del__()
            mock_stop.assert_called_once()

    def test_cleanup_handles_exceptions(self, connector: QwenOAuthConnector):
        """Test that cleanup handles exceptions gracefully."""
        with patch.object(
            connector, "_stop_file_watching", side_effect=Exception("Test error")
        ):
            # Should not raise exception
            connector.__del__()


class TestIntegrationScenarios(TestQwenOAuthCredentialValidation):
    """Test complete integration scenarios."""

    @pytest.mark.asyncio
    async def test_complete_expired_token_scenario(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        expired_credentials: dict,
    ):
        """Test complete scenario: startup with expired token -> initialization fails."""
        self.create_credentials_file(temp_credentials_dir, expired_credentials)

        with patch.object(Path, "home", return_value=temp_credentials_dir.parent):
            await connector.initialize()

            # Should fail initialization
            assert not connector.is_functional
            assert connector._initialization_failed
            assert not connector.is_backend_functional()

            # Should have descriptive error
            errors = connector.get_validation_errors()
            assert len(errors) > 0
            assert "Token expired" in errors[0]

    @pytest.mark.asyncio
    async def test_complete_valid_token_scenario(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        valid_credentials: dict,
    ):
        """Test complete scenario: startup with valid token -> initialization succeeds."""
        self.create_credentials_file(temp_credentials_dir, valid_credentials)

        with (
            patch.object(Path, "home", return_value=temp_credentials_dir.parent),
            patch.object(connector, "_refresh_token_if_needed", return_value=True),
            patch.object(connector, "_start_file_watching"),
        ):
            await connector.initialize()

            # Should succeed initialization
            assert connector.is_functional
            assert not connector._initialization_failed
            assert connector.is_backend_functional()

            # Should have no errors
            errors = connector.get_validation_errors()
            assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_complete_runtime_expiry_scenario(
        self,
        connector: QwenOAuthConnector,
        temp_credentials_dir: Path,
        valid_credentials: dict,
    ):
        """Test complete scenario: valid at startup -> expires at runtime -> reload fails."""
        # Start with valid credentials
        self.create_credentials_file(temp_credentials_dir, valid_credentials)

        with (
            patch.object(Path, "home", return_value=temp_credentials_dir.parent),
            patch.object(connector, "_refresh_token_if_needed", return_value=True),
            patch.object(connector, "_start_file_watching"),
        ):
            await connector.initialize()

            # Should be functional initially
            assert connector.is_functional

            # Now simulate runtime expiry
            connector._last_validation_time = 0  # Force validation

            # Mock token as expired and reload fails
            with (
                patch.object(connector, "_is_token_expired", return_value=True),
                patch.object(connector, "_load_oauth_credentials", return_value=False),
            ):
                result = await connector._validate_runtime_credentials()

                # Should become non-functional
                assert result is False
                assert not connector.is_functional
                assert not connector.is_backend_functional()

                # Should have descriptive error
                errors = connector.get_validation_errors()
                assert len(errors) > 0
                assert "Failed to reload expired credentials" in errors[0]
