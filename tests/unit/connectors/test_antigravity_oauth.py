"""
Tests for the Antigravity OAuth connector.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.connectors.mixins.antigravity_auth_mixin import (
    ANTIGRAVITY_AUTH_KEY,
    ANTIGRAVITY_SANDBOX_ENDPOINT,
    ANTIGRAVITY_USER_AGENT,
)


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def connector(mock_client):
    """Create a AntigravityOAuthConnector instance."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    return AntigravityOAuthConnector(
        mock_client, config, translation_service, name="antigravity-oauth"
    )


def _write_state_db(db_path: Path, token: str, name: str) -> Path:
    """Create a minimal Antigravity state database with auth status."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        (ANTIGRAVITY_AUTH_KEY, json.dumps({"apiKey": token, "name": name})),
    )
    conn.commit()
    conn.close()
    return db_path


class TestAntigravityOAuthConnector:
    """Test cases for Antigravity OAuth connector."""

    def test_candidate_paths_use_override(self, connector, monkeypatch, tmp_path):
        """Ensure explicit override takes precedence."""
        override = tmp_path / "custom" / "state.vscdb"
        monkeypatch.setenv("ANTIGRAVITY_STATE_DB", str(override))

        paths = connector._candidate_state_db_paths()

        assert paths == [override]

    @pytest.mark.asyncio
    async def test_load_credentials_from_state_db(
        self, connector, monkeypatch, tmp_path
    ):
        """Load credentials from the Antigravity state database."""
        db_path = _write_state_db(tmp_path / "state.vscdb", "token-123", "Test User")
        monkeypatch.setenv("ANTIGRAVITY_STATE_DB", str(db_path))

        loaded = await connector._load_oauth_credentials()

        assert loaded is True
        assert connector._oauth_credentials is not None
        assert connector._oauth_credentials["access_token"] == "token-123"
        assert connector._credentials_path == db_path

    @pytest.mark.asyncio
    async def test_load_credentials_from_backup_when_primary_missing(
        self, connector, monkeypatch, tmp_path
    ):
        """Use backup database when the primary file is unavailable."""
        storage_dir = tmp_path / "Antigravity" / "User" / "globalStorage"
        backup_db = _write_state_db(
            storage_dir / "state.vscdb.backup", "backup-token", "Backup User"
        )
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.delenv("ANTIGRAVITY_STATE_DB", raising=False)

        loaded = await connector._load_oauth_credentials()

        assert loaded is True
        assert connector._credentials_path == backup_db
        assert connector._oauth_credentials is not None
        assert connector._oauth_credentials["access_token"] == "backup-token"

    @pytest.mark.asyncio
    async def test_missing_database_fails_gracefully(
        self, connector, monkeypatch, tmp_path
    ):
        """Ensure missing Antigravity installation does not raise."""
        monkeypatch.setenv(
            "ANTIGRAVITY_STATE_DB", str(tmp_path / "absent" / "state.vscdb")
        )

        loaded = await connector._load_oauth_credentials()

        assert loaded is False
        assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_model_enumeration_uses_fetch_available_models_endpoint(
        self, connector, monkeypatch
    ):
        """Skip fetchAvailableModels on the sandbox and use fallback list."""
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT
        connector._oauth_credentials = {"access_token": "token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.client.get = AsyncMock()  # type: ignore[assignment]

        await connector._ensure_models_loaded()

        assert connector.available_models  # fallback list loaded
        assert connector.client.get.await_count == 0

    @pytest.mark.asyncio
    async def test_model_enumeration_uses_correct_endpoint_url(
        self, connector, monkeypatch
    ):
        """Verify that non-sandbox base URLs still use fetchAvailableModels."""
        connector.gemini_api_base_url = "https://custom-endpoint.example.com"
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]

        captured_url = None

        async def capture_get(url, **kwargs):
            nonlocal captured_url
            captured_url = url

            class DummyResponse:
                status_code = 200
                text = "{}"

                def json(self):
                    return {"models": {}, "agentModelSorts": []}

            return DummyResponse()

        connector.client.get = capture_get  # type: ignore[assignment]

        await connector._load_models_from_api()

        assert (
            captured_url
            == "https://custom-endpoint.example.com/v1internal:fetchAvailableModels"
        )

    @pytest.mark.asyncio
    async def test_model_enumeration_fallback_on_failure(self, connector, monkeypatch):
        """Fall back to default list when enumeration fails."""
        connector.gemini_api_base_url = "https://custom-endpoint.example.com"
        connector._oauth_credentials = {"access_token": "token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.client.get = AsyncMock(side_effect=httpx.RequestError("boom"))  # type: ignore[assignment]

        await connector._ensure_models_loaded()

        assert connector.available_models

    @pytest.mark.asyncio
    async def test_health_check_uses_fetch_available_models_endpoint(
        self, connector, monkeypatch
    ):
        """Health check should skip fetchAvailableModels on sandbox base URL."""
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        connector.client.get = AsyncMock()  # type: ignore[assignment]

        result = await connector._perform_health_check()

        assert result is True
        assert connector.client.get.await_count == 0
        assert connector._health_checked is True
        assert connector._refresh_token_if_needed.await_count == 1

    @pytest.mark.asyncio
    async def test_health_check_fails_on_non_200_response(self, connector, monkeypatch):
        """Health check should return False on non-200 response."""
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.gemini_api_base_url = "https://custom-endpoint.example.com"

        class DummyResponse:
            status_code = 401
            text = "Unauthorized"

            def json(self):
                return {"error": "Unauthorized"}

        connector.client.get = AsyncMock(return_value=DummyResponse())  # type: ignore[assignment]

        result = await connector._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_list_models_uses_fetch_available_models_endpoint(
        self, connector, monkeypatch
    ):
        """list_models should use fetchAvailableModels and transform response."""
        connector._oauth_credentials = {"access_token": "test-token"}
        connector.gemini_api_base_url = "https://custom-endpoint.example.com"

        class DummyResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "models": {
                        "gemini-2.5-flash": {
                            "displayName": "Gemini 2.5 Flash",
                            "maxTokens": 1048576,
                            "maxOutputTokens": 65535,
                        },
                        "claude-sonnet-4-5": {
                            "displayName": "Claude Sonnet 4.5",
                            "maxTokens": 200000,
                            "maxOutputTokens": 64000,
                        },
                    }
                }

        connector.client.get = AsyncMock(return_value=DummyResponse())  # type: ignore[assignment]

        result = await connector.list_models(
            gemini_api_base_url="https://custom-endpoint.example.com",
            key_name="test",
            api_key="test-key",
        )

        assert result.data
        assert len(result.data) == 2
        model_names = [m.id for m in result.data]
        assert "models/gemini-2.5-flash" in model_names
        assert "models/claude-sonnet-4-5" in model_names

    @pytest.mark.asyncio
    async def test_list_models_uses_fallback_on_sandbox(self, connector, monkeypatch):
        """Sandbox list_models should use the cached fallback list without HTTP calls."""
        connector._oauth_credentials = {"access_token": "test-token"}
        connector.client.get = AsyncMock()  # type: ignore[assignment]

        result = await connector.list_models(
            gemini_api_base_url=ANTIGRAVITY_SANDBOX_ENDPOINT,
            key_name="test",
            api_key="test-key",
        )

        assert connector.client.get.await_count == 0
        assert result.data
        # Model names now include vendor prefix in public list
        assert any(
            model.id == "models/google/gemini-2.5-pro"
            for model in result.data
        )


    @pytest.mark.asyncio
    async def test_discover_project_id_prefers_paid_tier(self, connector, monkeypatch):
        """Project discovery should select the highest tier and return its project id."""
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        class DummyResponse:
            def __init__(self, payload: dict[str, Any], status_code: int = 200):
                self._payload = payload
                self.status_code = status_code
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        responses = [
            DummyResponse(
                {
                    "allowedTiers": [
                        {"id": "free-tier", "maxContextTokens": 1024},
                        {"id": "paid-tier", "maxContextTokens": 2048},
                    ]
                }
            ),
            DummyResponse(
                {
                    "done": True,
                    "response": {"cloudaicompanionProject": {"id": "project-paid"}},
                }
            ),
        ]

        def request_side_effect(*args, **kwargs):
            return responses.pop(0)

        session = Mock()
        session.request = Mock(side_effect=request_side_effect)

        monkeypatch.setattr(
            "src.connectors.antigravity_oauth.asyncio.to_thread",
            AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)),
        )
        monkeypatch.setattr(
            "src.connectors.antigravity_oauth.asyncio.sleep", AsyncMock()
        )

        project_id = await connector._discover_project_id(session)

        assert project_id == "project-paid"
        assert connector._project_id == "project-paid"
        assert session.request.call_count == 2
        onboard_payload = session.request.call_args_list[1].kwargs["json"]
        assert onboard_payload["tierId"] == "paid-tier"

    @pytest.mark.asyncio
    async def test_discover_project_id_uses_existing_project(
        self, connector, monkeypatch
    ):
        """If loadCodeAssist returns a project id, onboarding should be skipped."""
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        class DummyResponse:
            def __init__(self, payload: dict[str, Any], status_code: int = 200):
                self._payload = payload
                self.status_code = status_code
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        session = Mock()
        session.request = Mock(
            return_value=DummyResponse({"cloudaicompanionProject": "proj-from-load"})
        )

        monkeypatch.setattr(
            "src.connectors.antigravity_oauth.asyncio.to_thread",
            AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)),
        )

        project_id = await connector._discover_project_id(session)

        assert project_id == "proj-from-load"
        assert connector._project_id == "proj-from-load"
        assert session.request.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_streaming_rate_limit_yields_error_chunk(
        self, connector, monkeypatch
    ):
        """Streaming 429 should emit an error chunk immediately.

        NOTE: This test is marked as slow because the retry mechanism
        in the connector causes long delays even with mocked sleep.
        The test needs refactoring to properly mock the retry loop.
        """

        # Minimal wiring to pass validation
        connector._oauth_credentials = {"access_token": "token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector._discover_project_id = AsyncMock(return_value="project-id")  # type: ignore[attr-defined]
        connector.translation_service.from_domain_to_gemini_request = Mock(
            return_value={
                "contents": [],
                "generationConfig": {},
            }
        )
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        quota_error = {
            "error": {
                "code": 429,
                "message": "You have exhausted your capacity on this model. Your quota will reset after 1s.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = quota_error
        mock_response.text = json.dumps(quota_error)
        mock_response.headers = {}  # Ensure headers is a dict, not a Mock

        async_to_thread = AsyncMock(return_value=mock_response)

        class DummySession:
            def __init__(self) -> None:
                self.request = Mock()
                self.headers: dict[str, str] = {}

        dummy_session = DummySession()

        monkeypatch.setattr(
            "google.auth.transport.requests.AuthorizedSession",
            lambda *args, **kwargs: dummy_session,
        )
        monkeypatch.setattr(
            "src.connectors.gemini_oauth_base.asyncio.to_thread", async_to_thread
        )
        # Mock asyncio.sleep to avoid real delays during retry logic
        monkeypatch.setattr(
            "src.connectors.gemini_oauth_base.asyncio.sleep", AsyncMock()
        )

        # Create a properly configured request object
        # Use spec to ensure attribute access works correctly
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request = CanonicalChatRequest(
            model="gemini-2.5-flash",
            messages=[ChatMessage(role="user", content="test")],
            stream=True,
        )

        envelope = await connector._chat_completions_code_assist_streaming(
            request, [ChatMessage(role="user", content="test")], "gemini-2.5-flash"
        )

        stream = envelope.content
        first_chunk = await stream.__anext__()

        assert first_chunk.metadata.get("finish_reason") == "error"
        assert isinstance(first_chunk.content, dict)
        assert first_chunk.content["error"]["code"] == 503
        assert first_chunk.content["error"]["type"] == "quota_exceeded"
        assert "exhausted your capacity" in first_chunk.content["error"]["message"]

    @pytest.mark.asyncio
    async def test_initialize_sets_custom_user_agent(self, mock_client, monkeypatch):
        """Initialize should create a client with Antigravity-specific User-Agent."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

        # Mock credential loading to succeed
        connector._load_oauth_credentials = AsyncMock(return_value=True)  # type: ignore[method-assign]
        connector._oauth_credentials = {"access_token": "test-token"}

        await connector.initialize()

        # After initialization, the connector should have a custom client
        # with the Antigravity User-Agent header
        assert connector.client is not None
        assert connector.client.headers.get("User-Agent") == ANTIGRAVITY_USER_AGENT

    def test_get_api_headers_includes_user_agent(self, mock_client):
        """_get_api_headers should include the Antigravity User-Agent."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}

        headers = connector._get_api_headers()

        assert headers["User-Agent"] == ANTIGRAVITY_USER_AGENT
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    def test_get_session_headers_includes_user_agent(self, mock_client):
        """_get_session_headers should include the Antigravity User-Agent."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

        headers = connector._get_session_headers()

        assert headers["User-Agent"] == ANTIGRAVITY_USER_AGENT

    def test_build_code_assist_request_body_uses_antigravity_format(self, mock_client):
        """_build_code_assist_request_body should use Antigravity-specific format."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

        # Create a mock request_data with an id
        request_data = Mock()
        request_data.id = None  # Will trigger UUID generation

        code_assist_request = {
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
            "generationConfig": {"temperature": 0.7},
        }

        request_body = connector._build_code_assist_request_body(
            effective_model="gemini-2.5-flash",
            project_id="test-project-123",
            request_data=request_data,
            code_assist_request=code_assist_request,
        )

        # Verify Antigravity-specific format
        assert "project" in request_body
        assert request_body["project"] == "test-project-123"

        assert "requestId" in request_body  # NOT user_prompt_id
        assert "user_prompt_id" not in request_body

        assert "model" in request_body
        assert request_body["model"] == "gemini-2.5-flash"

        assert "userAgent" in request_body
        assert request_body["userAgent"] == "antigravity"

        assert "requestType" in request_body
        assert request_body["requestType"] == "agent"

        assert "request" in request_body
        assert request_body["request"] == code_assist_request


class TestModelValidation:
    """Test cases for model validation in the Antigravity connector."""

    @pytest.fixture
    def connector_with_models(self, mock_client):
        """Create a connector with pre-loaded models (simulating API-loaded models)."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        # Pre-load some models for testing (simulating API-loaded models)
        connector.available_models = [
            "claude-sonnet-4-5",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-3-pro-high",
        ]
        connector._available_models_set = set(connector.available_models)
        # Mark as loaded from API to enable validation
        connector._models_from_api = True

        # Sync state to model registry if it exists (created during __init__)
        if connector._model_registry:
            connector._model_registry._available_models = connector.available_models
            connector._model_registry._available_models_set = (
                connector._available_models_set
            )
            connector._model_registry._models_from_api = True
            connector._model_registry._loaded = True

        return connector

    def test_validate_model_accepts_valid_model(self, connector_with_models):
        """Validation should pass for models in the available list."""
        # Should not raise
        connector_with_models.validate_model("gemini-2.5-flash")
        connector_with_models.validate_model("claude-sonnet-4-5")
        connector_with_models.validate_model("gemini-3-pro-high")

    def test_validate_model_rejects_invalid_model(self, connector_with_models):
        """Validation should raise BackendError for unknown models."""
        from src.core.common.exceptions import BackendError

        with pytest.raises(BackendError) as exc_info:
            connector_with_models.validate_model("nonexistent-model")

        error = exc_info.value
        assert error.code == "model_not_found"
        assert error.status_code == 400
        assert "nonexistent-model" in str(error.message)
        assert "not available" in str(error.message)

    def test_validate_model_error_includes_available_models(
        self, connector_with_models
    ):
        """Error message should include examples of available models."""
        from src.core.common.exceptions import BackendError

        with pytest.raises(BackendError) as exc_info:
            connector_with_models.validate_model("bad-model")

        error = exc_info.value
        # Should mention at least one available model
        assert "gemini-2.5-flash" in str(error.message) or "claude-sonnet-4-5" in str(
            error.message
        )

    def test_validate_model_skipped_when_no_models_loaded(self, mock_client):
        """Validation should be skipped if models list is empty."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        # Models not loaded - should not raise
        connector.validate_model("any-model")

    def test_validate_model_skipped_when_using_hardcoded_fallback(self, mock_client):
        """Validation should be skipped when using hardcoded fallback model list."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        # Set up models from hardcoded fallback (not from API)
        connector.available_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        connector._available_models_set = set(connector.available_models)
        connector._models_from_api = False  # Simulating hardcoded fallback

        # Should NOT raise even though model is not in the list
        # because we're using hardcoded fallback which may be outdated
        connector.validate_model("gemini-3-pro-high")

    def test_validate_model_enforced_when_models_from_api(self, mock_client):
        """Validation should be enforced when models were loaded from API."""
        from src.core.common.exceptions import BackendError
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        # Set up models as if loaded from API
        connector.available_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        connector._available_models_set = set(connector.available_models)
        connector._models_from_api = True  # Simulating API-loaded models

        # Sync state to model registry if it exists (created during __init__)
        if connector._model_registry:
            connector._model_registry._available_models = connector.available_models
            connector._model_registry._available_models_set = (
                connector._available_models_set
            )
            connector._model_registry._models_from_api = True
            connector._model_registry._loaded = True

        # Should raise because models were loaded from API
        with pytest.raises(BackendError) as exc_info:
            connector.validate_model("nonexistent-model")

        assert exc_info.value.code == "model_not_found"

    def test_available_models_set_cache_built_correctly(self, connector_with_models):
        """The _available_models_set should be built from available_models."""
        assert connector_with_models._available_models_set == {
            "claude-sonnet-4-5",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-3-pro-high",
        }

    def test_get_available_models_set_builds_from_list_if_empty(self, mock_client):
        """_get_available_models_set should build set from list if not cached."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector.available_models = ["model-a", "model-b"]
        connector._available_models_set = set()  # Empty cache

        result = connector._get_available_models_set()

        assert result == {"model-a", "model-b"}
        # Cache should now be populated
        assert connector._available_models_set == {"model-a", "model-b"}

    @pytest.mark.asyncio
    async def test_models_cached_after_first_load(self, mock_client):
        """Models should be cached and not fetched on every call."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        class DummyResponse:
            status_code = 200
            text = "{}"

            def json(self):
                return {
                    "models": {
                        "gemini-2.5-flash": {"displayName": "Gemini 2.5 Flash"},
                        "gemini-2.5-pro": {"displayName": "Gemini 2.5 Pro"},
                    }
                }

        mock_get = AsyncMock(return_value=DummyResponse())
        connector.client.get = mock_get  # type: ignore[assignment]

        # First call should populate fallback list without hitting the endpoint
        await connector._ensure_models_loaded()
        assert mock_get.call_count == 0
        assert connector.available_models

        # Second call should use cache, not fetch again
        await connector._ensure_models_loaded()
        assert mock_get.call_count == 0  # Still 0, not 1

    @pytest.mark.asyncio
    async def test_chat_completions_skips_strict_model_validation(
        self, mock_client, monkeypatch
    ):
        """chat_completions should SKIP strict validation for Antigravity backend."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load specific models (simulating API-loaded models)
        connector.available_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        connector._available_models_set = set(connector.available_models)
        # Mark as loaded from API to enable validation (if it were enabled)
        connector._models_from_api = True

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector._ensure_healthy = AsyncMock()  # type: ignore[attr-defined]

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )

        # Mock the coordinator instance property
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="invalid-model-xyz",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        )

        # Should NOT raise for invalid model because validation is disabled
        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="invalid-model-xyz",
        )

        # Verify the invalid model was passed through to the coordinator
        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "invalid-model-xyz"


class TestGemini3ProModelMapping:
    """Test cases for gemini-3-pro model name mapping based on reasoning_effort."""

    @pytest.fixture
    def connector(self, mock_client):
        """Create a connector for testing model mapping."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        return AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

    def test_map_gemini_3_pro_default_to_high(self, connector):
        """Default reasoning_effort should map gemini-3-pro to gemini-3-pro-high."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.extra_body = None

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-high"

    def test_map_gemini_3_pro_high_effort(self, connector):
        """reasoning_effort=high should map gemini-3-pro to gemini-3-pro-high."""
        request_data = Mock()
        request_data.reasoning_effort = "high"
        request_data.extra_body = None

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-high"

    def test_map_gemini_3_pro_medium_effort(self, connector):
        """reasoning_effort=medium should map gemini-3-pro to gemini-3-pro-high."""
        request_data = Mock()
        request_data.reasoning_effort = "medium"
        request_data.extra_body = None

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-high"

    def test_map_gemini_3_pro_low_effort(self, connector):
        """reasoning_effort=low should map gemini-3-pro to gemini-3-pro-low."""
        request_data = Mock()
        request_data.reasoning_effort = "low"
        request_data.extra_body = None

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-low"

    def test_map_gemini_3_pro_from_extra_body(self, connector):
        """reasoning_effort in extra_body should be used for mapping."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.extra_body = {"reasoning_effort": "low"}

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-low"

    def test_map_gemini_3_pro_dict_request(self, connector):
        """Should work with dict-style request_data."""
        request_data = {"reasoning_effort": "low", "extra_body": None}

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-low"

    def test_map_gemini_3_pro_dict_extra_body(self, connector):
        """Should extract reasoning_effort from extra_body in dict request."""
        request_data = {
            "reasoning_effort": None,
            "extra_body": {"reasoning_effort": "low"},
        }

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-low"

    def test_map_gemini_3_pro_nested_reasoning_effort(self, connector):
        """Should extract reasoning.effort from nested reasoning object (Responses API)."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.reasoning = {"effort": "low"}
        request_data.extra_body = None

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-low"

    def test_map_gemini_3_pro_nested_reasoning_in_extra_body(self, connector):
        """Should extract reasoning.effort from extra_body.reasoning object."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.reasoning = None
        request_data.extra_body = {"reasoning": {"effort": "low"}}

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-low"

    def test_map_gemini_3_pro_flat_takes_precedence_over_nested(self, connector):
        """Flat reasoning_effort should take precedence over nested reasoning.effort."""
        request_data = Mock()
        request_data.reasoning_effort = "high"
        request_data.reasoning = {"effort": "low"}  # Should be ignored
        request_data.extra_body = None

        result = connector._map_gemini_3_pro_model("gemini-3-pro", request_data)

        assert result == "gemini-3-pro-high"

    def test_map_other_models_unchanged(self, connector):
        """Other model names should pass through unchanged."""
        request_data = Mock()
        request_data.reasoning_effort = "low"
        request_data.extra_body = None

        # These should all pass through unchanged
        assert (
            connector._map_gemini_3_pro_model("gemini-2.5-pro", request_data)
            == "gemini-2.5-pro"
        )
        assert (
            connector._map_gemini_3_pro_model("gemini-3-pro-high", request_data)
            == "gemini-3-pro-high"
        )
        assert (
            connector._map_gemini_3_pro_model("gemini-3-pro-low", request_data)
            == "gemini-3-pro-low"
        )
        assert (
            connector._map_gemini_3_pro_model("claude-sonnet-4-5", request_data)
            == "claude-sonnet-4-5"
        )

    def test_map_gemini_3_pro_case_insensitive(self, connector):
        """reasoning_effort values should be case-insensitive."""
        request_data = Mock()
        request_data.extra_body = None

        request_data.reasoning_effort = "LOW"
        assert (
            connector._map_gemini_3_pro_model("gemini-3-pro", request_data)
            == "gemini-3-pro-low"
        )

        request_data.reasoning_effort = "High"
        assert (
            connector._map_gemini_3_pro_model("gemini-3-pro", request_data)
            == "gemini-3-pro-high"
        )

        request_data.reasoning_effort = "MEDIUM"
        assert (
            connector._map_gemini_3_pro_model("gemini-3-pro", request_data)
            == "gemini-3-pro-high"
        )

    @pytest.mark.asyncio
    async def test_chat_completions_maps_gemini_3_pro_with_vendor_prefix(
        self, mock_client, monkeypatch
    ):
        """chat_completions should strip google/ prefix and map gemini-3-pro."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load models
        connector.available_models = ["gemini-3-pro", "gemini-2.5-flash"]
        connector._available_models_set = set(connector.available_models)

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)
        connector._ensure_healthy = AsyncMock()

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="google/gemini-3-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
            reasoning_effort=None,  # Default to high
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="google/gemini-3-pro",  # With vendor prefix
        )

        # Verify the model was mapped to gemini-3-pro-high
        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "gemini-3-pro-high"

    @pytest.mark.asyncio
    async def test_chat_completions_maps_gemini_3_pro_low_effort(
        self, mock_client, monkeypatch
    ):
        """chat_completions should map gemini-3-pro to low variant with low effort."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load models
        connector.available_models = ["gemini-3-pro", "gemini-2.5-flash"]
        connector._available_models_set = set(connector.available_models)

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)
        connector._ensure_healthy = AsyncMock()

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="gemini-3-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
            reasoning_effort="low",
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="gemini-3-pro",
        )

        # Verify the model was mapped to gemini-3-pro-low
        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "gemini-3-pro-low"


class TestClaudeOpusModelMapping:
    """Test cases for claude-opus-4.5 model name mapping (always thinking variant)."""

    @pytest.fixture
    def connector(self, mock_client):
        """Create a connector for testing model mapping."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        return AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

    def test_map_claude_opus_always_to_thinking(self, connector):
        """claude-opus-4.5 should always map to claude-opus-4-5-thinking regardless of reasoning_effort."""
        request_data = Mock()
        request_data.reasoning = None
        request_data.extra_body = None

        # Test with no reasoning_effort
        request_data.reasoning_effort = None
        assert (
            connector._map_claude_opus_model("claude-opus-4.5", request_data)
            == "claude-opus-4-5-thinking"
        )

        # Test with low - should still be thinking
        request_data.reasoning_effort = "low"
        assert (
            connector._map_claude_opus_model("claude-opus-4.5", request_data)
            == "claude-opus-4-5-thinking"
        )

        # Test with high - should be thinking
        request_data.reasoning_effort = "high"
        assert (
            connector._map_claude_opus_model("claude-opus-4.5", request_data)
            == "claude-opus-4-5-thinking"
        )

        # Test with medium - should be thinking
        request_data.reasoning_effort = "medium"
        assert (
            connector._map_claude_opus_model("claude-opus-4.5", request_data)
            == "claude-opus-4-5-thinking"
        )

    def test_map_other_models_unchanged(self, connector):
        """Other model names should pass through unchanged."""
        request_data = Mock()
        request_data.reasoning_effort = "high"
        request_data.reasoning = None
        request_data.extra_body = None

        # These should all pass through unchanged
        assert (
            connector._map_claude_opus_model("claude-sonnet-4.5", request_data)
            == "claude-sonnet-4.5"
        )
        assert (
            connector._map_claude_opus_model("claude-opus-4-5", request_data)
            == "claude-opus-4-5"
        )
        assert (
            connector._map_claude_opus_model("gemini-2.5-pro", request_data)
            == "gemini-2.5-pro"
        )


class TestClaudeSonnetModelMapping:
    """Test cases for claude-sonnet-4.5 model name mapping based on reasoning_effort."""

    @pytest.fixture
    def connector(self, mock_client):
        """Create a connector for testing model mapping."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        return AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

    def test_map_claude_sonnet_default_to_base(self, connector):
        """Default (no reasoning_effort) should map claude-sonnet-4.5 to claude-sonnet-4-5."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.reasoning = None
        request_data.extra_body = None

        result = connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)

        assert result == "claude-sonnet-4-5"

    def test_map_claude_sonnet_low_effort(self, connector):
        """reasoning_effort=low should map claude-sonnet-4.5 to claude-sonnet-4-5 (base)."""
        request_data = Mock()
        request_data.reasoning_effort = "low"
        request_data.reasoning = None
        request_data.extra_body = None

        result = connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)

        assert result == "claude-sonnet-4-5"

    def test_map_claude_sonnet_high_effort(self, connector):
        """reasoning_effort=high should map claude-sonnet-4.5 to claude-sonnet-4-5-thinking."""
        request_data = Mock()
        request_data.reasoning_effort = "high"
        request_data.reasoning = None
        request_data.extra_body = None

        result = connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)

        assert result == "claude-sonnet-4-5-thinking"

    def test_map_claude_sonnet_medium_effort(self, connector):
        """reasoning_effort=medium should map claude-sonnet-4.5 to claude-sonnet-4-5-thinking."""
        request_data = Mock()
        request_data.reasoning_effort = "medium"
        request_data.reasoning = None
        request_data.extra_body = None

        result = connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)

        assert result == "claude-sonnet-4-5-thinking"

    def test_map_claude_sonnet_from_extra_body(self, connector):
        """reasoning_effort in extra_body should be used for mapping."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.reasoning = None
        request_data.extra_body = {"reasoning_effort": "high"}

        result = connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)

        assert result == "claude-sonnet-4-5-thinking"

    def test_map_claude_sonnet_nested_reasoning_effort(self, connector):
        """Should extract reasoning.effort from nested reasoning object."""
        request_data = Mock()
        request_data.reasoning_effort = None
        request_data.reasoning = {"effort": "high"}
        request_data.extra_body = None

        result = connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)

        assert result == "claude-sonnet-4-5-thinking"

    def test_map_claude_sonnet_case_insensitive(self, connector):
        """reasoning_effort values should be case-insensitive."""
        request_data = Mock()
        request_data.reasoning = None
        request_data.extra_body = None

        request_data.reasoning_effort = "HIGH"
        assert (
            connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)
            == "claude-sonnet-4-5-thinking"
        )

        request_data.reasoning_effort = "Medium"
        assert (
            connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)
            == "claude-sonnet-4-5-thinking"
        )

        request_data.reasoning_effort = "LOW"
        assert (
            connector._map_claude_sonnet_model("claude-sonnet-4.5", request_data)
            == "claude-sonnet-4-5"
        )

    def test_map_other_models_unchanged(self, connector):
        """Other model names should pass through unchanged."""
        request_data = Mock()
        request_data.reasoning_effort = "high"
        request_data.reasoning = None
        request_data.extra_body = None

        # These should all pass through unchanged
        assert (
            connector._map_claude_sonnet_model("claude-opus-4.5", request_data)
            == "claude-opus-4.5"
        )
        assert (
            connector._map_claude_sonnet_model("gemini-2.5-pro", request_data)
            == "gemini-2.5-pro"
        )


class TestGptOssModelMapping:
    """Test cases for gpt-oss-120b model name mapping (always medium variant)."""

    @pytest.fixture
    def connector(self, mock_client):
        """Create a connector for testing model mapping."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        return AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )

    def test_map_gpt_oss_always_to_medium(self, connector):
        """gpt-oss-120b should always map to gpt-oss-120b-medium regardless of reasoning_effort."""
        request_data = Mock()
        request_data.reasoning = None
        request_data.extra_body = None

        # Test with no reasoning_effort
        request_data.reasoning_effort = None
        assert (
            connector._map_gpt_oss_model("gpt-oss-120b", request_data)
            == "gpt-oss-120b-medium"
        )

        # Test with low - should still be medium
        request_data.reasoning_effort = "low"
        assert (
            connector._map_gpt_oss_model("gpt-oss-120b", request_data)
            == "gpt-oss-120b-medium"
        )

        # Test with high - should still be medium
        request_data.reasoning_effort = "high"
        assert (
            connector._map_gpt_oss_model("gpt-oss-120b", request_data)
            == "gpt-oss-120b-medium"
        )

        # Test with medium - should be medium
        request_data.reasoning_effort = "medium"
        assert (
            connector._map_gpt_oss_model("gpt-oss-120b", request_data)
            == "gpt-oss-120b-medium"
        )

    def test_map_other_models_unchanged(self, connector):
        """Other model names should pass through unchanged."""
        request_data = Mock()
        request_data.reasoning_effort = "high"
        request_data.reasoning = None
        request_data.extra_body = None

        # These should all pass through unchanged
        assert connector._map_gpt_oss_model("gpt-4o", request_data) == "gpt-4o"
        assert (
            connector._map_gpt_oss_model("gemini-2.5-pro", request_data)
            == "gemini-2.5-pro"
        )

    @pytest.mark.asyncio
    async def test_chat_completions_maps_claude_opus_always_to_thinking(
        self, mock_client, monkeypatch
    ):
        """chat_completions should always map claude-opus-4.5 to thinking variant."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load models
        connector.available_models = [
            "anthropic/claude-opus-4.5",
            "google/gemini-2.5-flash",
        ]
        connector._available_models_set = set(connector.available_models)

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)
        connector._ensure_healthy = AsyncMock()

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="anthropic/claude-opus-4.5",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
            reasoning_effort=None,  # Should still map to thinking
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="anthropic/claude-opus-4.5",  # With vendor prefix
        )

        # Verify the model was mapped to claude-opus-4-5-thinking (always)
        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "claude-opus-4-5-thinking"

    @pytest.mark.asyncio
    async def test_chat_completions_maps_claude_opus_low_effort_still_thinking(
        self, mock_client, monkeypatch
    ):
        """chat_completions should map claude-opus-4.5 to thinking even with low effort."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load models
        connector.available_models = [
            "anthropic/claude-opus-4.5",
            "google/gemini-2.5-flash",
        ]
        connector._available_models_set = set(connector.available_models)

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)
        connector._ensure_healthy = AsyncMock()

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="anthropic/claude-opus-4.5",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
            reasoning_effort="low",  # Should still map to thinking (ignored)
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="anthropic/claude-opus-4.5",
        )

        # Verify the model was mapped to claude-opus-4-5-thinking (always, ignoring reasoning_effort)
        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "claude-opus-4-5-thinking"

    @pytest.mark.asyncio
    async def test_chat_completions_maps_claude_sonnet_with_reasoning_effort(
        self, mock_client, monkeypatch
    ):
        """chat_completions should map claude-sonnet-4.5 based on reasoning_effort."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load models
        connector.available_models = [
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-flash",
        ]
        connector._available_models_set = set(connector.available_models)

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)
        connector._ensure_healthy = AsyncMock()

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        # Test with high effort - should get thinking variant
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="anthropic/claude-sonnet-4.5",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
            reasoning_effort="high",
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="anthropic/claude-sonnet-4.5",
        )

        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "claude-sonnet-4-5-thinking"

    @pytest.mark.asyncio
    async def test_chat_completions_maps_gpt_oss_always_to_medium(
        self, mock_client, monkeypatch
    ):
        """chat_completions should always map gpt-oss-120b to medium variant."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        translation_service = TranslationService()
        connector = AntigravityOAuthConnector(
            mock_client, config, translation_service, name="antigravity-oauth"
        )
        connector._oauth_credentials = {"access_token": "test-token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT

        # Pre-load models
        connector.available_models = ["openai/gpt-oss-120b", "google/gemini-2.5-flash"]
        connector._available_models_set = set(connector.available_models)

        # Mock to prevent actual API calls
        connector._validate_runtime_credentials = AsyncMock(return_value=True)
        connector._ensure_healthy = AsyncMock()

        # Mock the coordinator since chat_completions now delegates to it
        from src.core.domain.responses import ResponseEnvelope

        mock_response = ResponseEnvelope(
            content={
                "choices": [{"message": {"content": "test", "role": "assistant"}}]
            },
            media_type="application/json",
            headers={},
        )
        mock_coordinator = AsyncMock()
        mock_coordinator.execute = AsyncMock(return_value=mock_response)
        connector._chat_completion_coordinator = mock_coordinator

        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request_data = CanonicalChatRequest(
            model="openai/gpt-oss-120b",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
            reasoning_effort="high",  # Should be ignored
        )

        await connector.chat_completions(
            request_data=request_data,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="openai/gpt-oss-120b",
        )

        # Verify the model was mapped to gpt-oss-120b-medium (always)
        assert mock_coordinator.execute.called
        call_args = mock_coordinator.execute.call_args
        assert call_args.kwargs.get("effective_model") == "gpt-oss-120b-medium"
