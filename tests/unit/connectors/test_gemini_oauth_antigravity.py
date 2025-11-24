"""
Tests for the Gemini OAuth Antigravity connector.
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from src.connectors.gemini_oauth_antigravity import (
    ANTIGRAVITY_AUTH_KEY,
    ANTIGRAVITY_SANDBOX_ENDPOINT,
    GeminiOAuthAntigravityConnector,
)


@pytest.fixture
def mock_client():
    """Mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def connector(mock_client):
    """Create a GeminiOAuthAntigravityConnector instance."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    return GeminiOAuthAntigravityConnector(
        mock_client, config, translation_service, name="gemini-oauth-antigravity"
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


class TestGeminiOAuthAntigravityConnector:
    """Test cases for Antigravity-backed Gemini OAuth connector."""

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
    async def test_model_enumeration_uses_endpoint(self, connector, monkeypatch):
        """Enumerate models from the sandbox models endpoint."""
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT
        connector._oauth_credentials = {"access_token": "token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]

        class DummyResponse:
            def __init__(self, status_code: int, payload: dict[str, object]):
                self.status_code = status_code
                self._payload = payload
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        responses = [
            DummyResponse(404, {}),
            DummyResponse(
                200,
                {
                    "models": [
                        {"name": "models/claude-3.5-sonnet"},
                        {"name": "models/gemini-2.5-pro"},
                        "models/another-model",
                    ]
                },
            ),
        ]

        connector.client.get = AsyncMock(side_effect=responses)  # type: ignore[assignment]

        await connector._ensure_models_loaded()

        assert connector.available_models == [
            "another-model",
            "claude-3.5-sonnet",
            "gemini-2.5-pro",
        ]

    @pytest.mark.asyncio
    async def test_model_enumeration_fallback_on_failure(self, connector, monkeypatch):
        """Fall back to default list when enumeration fails."""
        connector.gemini_api_base_url = ANTIGRAVITY_SANDBOX_ENDPOINT
        connector._oauth_credentials = {"access_token": "token"}
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        connector.client.get = AsyncMock(side_effect=httpx.RequestError("boom"))  # type: ignore[assignment]

        await connector._ensure_models_loaded()

        assert connector.available_models

    @pytest.mark.asyncio
    async def test_streaming_rate_limit_yields_error_chunk(
        self, connector, monkeypatch
    ):
        """Streaming 429 should emit an error chunk immediately."""

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

        request = Mock()
        request.stream = True
        request.messages = []
        request.extra_body = {}

        envelope = await connector._chat_completions_code_assist_streaming(
            request, [], "gemini-2.5-flash"
        )

        stream = envelope.content
        first_chunk = await stream.__anext__()

        assert first_chunk.metadata.get("finish_reason") == "error"
        assert isinstance(first_chunk.content, dict)
        assert first_chunk.content["error"]["code"] == 503
        assert first_chunk.content["error"]["type"] == "quota_exceeded"
        assert "exhausted your capacity" in first_chunk.content["error"]["message"]
