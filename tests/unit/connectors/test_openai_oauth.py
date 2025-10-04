import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.openai_oauth import (
    OpenAICredentialsFileHandler,
    OpenAIOAuthConnector,
)
from src.core.domain.chat import ChatMessage, ChatRequest


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    # Minimal auth.json with tokens.access_token
    data = {"tokens": {"access_token": "chatgpt_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="openai_oauth_backend")
async def openai_oauth_backend_fixture(auth_dir: Path):
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        # Mock the validation and file watching methods for testing
        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_oauth_path=str(auth_dir))
            # Set the credentials for the test
            backend._auth_credentials = {"tokens": {"access_token": "chatgpt_token"}}
            yield backend


@pytest.mark.asyncio
async def test_openai_oauth_uses_bearer_from_auth_json(
    openai_oauth_backend: OpenAIOAuthConnector, httpx_mock: HTTPXMock
):
    # Mock chat completion
    httpx_mock.add_response(
        url=f"{openai_oauth_backend.api_base_url}/chat/completions",
        method="POST",
        json={
            "id": "cmpl_1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        status_code=200,
        headers={"Content-Type": "application/json"},
    )

    req = ChatRequest(
        model="openai-oauth:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hi")],
        max_tokens=16,
        stream=False,
    )

    # Mock runtime validation for the test
    with patch.object(
        openai_oauth_backend, "_validate_runtime_credentials", return_value=(True, [])
    ):
        await openai_oauth_backend.chat_completions(
            request_data=req,
            processed_messages=[ChatMessage(role="user", content="hi")],
            effective_model="gpt-4o-mini",
        )

    sent = httpx_mock.get_request()
    assert sent is not None
    # Ensure Authorization header uses access token
    assert sent.headers.get("Authorization") == "Bearer chatgpt_token"


@pytest.mark.asyncio
async def test_openai_oauth_reload_scheduled_from_thread(
    openai_oauth_backend: OpenAIOAuthConnector,
):
    backend = openai_oauth_backend

    reload_event = asyncio.Event()

    async def fake_load(force_reload: bool = False) -> bool:
        reload_event.set()
        return True

    with (
        patch.object(
            backend, "_load_auth", AsyncMock(side_effect=fake_load)
        ) as load_mock,
        patch.object(
            backend, "_validate_credentials_structure", return_value=(True, [])
        ),
    ):

        def trigger() -> None:
            backend._schedule_credentials_reload()

        thread = threading.Thread(target=trigger)
        thread.start()
        thread.join()

        await asyncio.wait_for(reload_event.wait(), timeout=1.0)
        load_mock.assert_awaited()

        # Allow callbacks to run so the pending task/future clears
        await asyncio.sleep(0)
        pending = backend._pending_reload_task
        assert pending is None or pending.done()


# --------------------------------------------------------------------------------
# Tests for file watching and force reload functionality
# --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_file_watching_success(auth_dir: Path):
    """Test that file watching starts successfully."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
        ):
            await backend.initialize(openai_oauth_path=str(auth_dir))

        # Verify file observer was started
        assert backend._file_observer is not None
        assert backend._file_observer.is_alive()

        # Clean up
        backend._stop_file_watching()


@pytest.mark.asyncio
async def test_start_file_watching_no_credentials_path():
    """Test that file watching doesn't start if credentials path is not set."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        # Try to start file watching without setting credentials path
        backend._start_file_watching()

        # Verify file observer was not started
        assert backend._file_observer is None


@pytest.mark.asyncio
async def test_stop_file_watching_success(auth_dir: Path):
    """Test that file watching stops successfully."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
        ):
            await backend.initialize(openai_oauth_path=str(auth_dir))

        assert backend._file_observer is not None

        # Stop file watching
        backend._stop_file_watching()

        # Verify observer is stopped and cleaned up
        assert backend._file_observer is None


@pytest.mark.asyncio
async def test_stop_file_watching_no_observer():
    """Test that stopping file watching when no observer exists doesn't raise errors."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        # Should not raise an error
        backend._stop_file_watching()
        assert backend._file_observer is None


@pytest.mark.asyncio
async def test_schedule_credentials_reload_valid_update(auth_dir: Path):
    """Test that credentials are reloaded when file changes with valid data."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_oauth_path=str(auth_dir))

        # Update credentials file with new token
        new_data = {"tokens": {"access_token": "new_token_123"}}
        (auth_dir / "auth.json").write_text(json.dumps(new_data), encoding="utf-8")

        # Mock _load_auth to return success
        with patch.object(backend, "_load_auth", return_value=True) as mock_load:
            backend._auth_credentials = new_data

            # Call the reload method
            backend._schedule_credentials_reload()

            # Wait for the task to complete
            if backend._pending_reload_task:
                await backend._pending_reload_task

            # Verify load_auth was called with force_reload=True
            mock_load.assert_called_once_with(force_reload=True)


@pytest.mark.asyncio
async def test_schedule_credentials_reload_invalid_file(auth_dir: Path):
    """Test that credentials reload degrades backend when file becomes invalid."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_oauth_path=str(auth_dir))

        # Mock validation to return failure
        with (
            patch.object(backend, "_load_auth", return_value=True),
            patch.object(
                backend,
                "_validate_credentials_structure",
                return_value=(False, ["Missing required fields"]),
            ),
        ):
            backend._auth_credentials = {}

            # Call the reload method
            backend._schedule_credentials_reload()

            # Wait for the task to complete
            if backend._pending_reload_task:
                await backend._pending_reload_task

            # Verify backend was degraded
            assert not backend.is_functional
            assert len(backend._credential_validation_errors) > 0


@pytest.mark.asyncio
async def test_schedule_credentials_reload_load_failure(auth_dir: Path):
    """Test that credentials reload degrades backend when load fails."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_oauth_path=str(auth_dir))

        # Mock _load_auth to fail
        with patch.object(backend, "_load_auth", return_value=False):
            # Call the reload method
            backend._schedule_credentials_reload()

            # Wait for the task to complete
            if backend._pending_reload_task:
                await backend._pending_reload_task

            # Verify backend was degraded
            assert not backend.is_functional
            assert "Failed to reload credentials from file" in str(
                backend._credential_validation_errors
            )


@pytest.mark.asyncio
async def test_load_auth_with_force_reload(auth_dir: Path):
    """Test that force_reload bypasses the timestamp cache."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)
        backend._oauth_dir_override = auth_dir

        # First load
        result1 = await backend._load_auth()
        assert result1 is True
        token1 = backend.api_key
        last_modified1 = backend._last_modified

        # Update the file with new token but keep same timestamp
        new_data = {"tokens": {"access_token": "force_reload_token"}}
        (auth_dir / "auth.json").write_text(json.dumps(new_data), encoding="utf-8")

        # Set the timestamp back to simulate no change
        import os

        os.utime(auth_dir / "auth.json", (last_modified1, last_modified1))

        # Load without force_reload - should use cache
        result2 = await backend._load_auth(force_reload=False)
        assert result2 is True
        token2 = backend.api_key
        assert token2 == token1  # Should be cached

        # Load with force_reload - should reload from file
        result3 = await backend._load_auth(force_reload=True)
        assert result3 is True
        token3 = backend.api_key
        assert token3 == "force_reload_token"  # Should be new token


@pytest.mark.asyncio
async def test_file_handler_on_modified_path_comparison(auth_dir: Path):
    """Test that file handler correctly compares paths across platforms."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)
        backend._oauth_dir_override = auth_dir
        await backend._load_auth()

        handler = OpenAICredentialsFileHandler(backend)

        # Create a mock event with the same path
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(auth_dir / "auth.json")

        # Mock the schedule method to verify it was called
        with patch.object(backend, "_schedule_credentials_reload") as mock_schedule:
            handler.on_modified(mock_event)
            mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_file_handler_on_modified_different_file(auth_dir: Path):
    """Test that file handler ignores changes to different files."""
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAIOAuthConnector(client, cfg, translation_service=ts)
        backend._oauth_dir_override = auth_dir
        await backend._load_auth()

        handler = OpenAICredentialsFileHandler(backend)

        # Create a mock event for a different file
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(auth_dir / "other_file.json")

        # Mock the schedule method to verify it was NOT called
        with patch.object(backend, "_schedule_credentials_reload") as mock_schedule:
            handler.on_modified(mock_event)
            mock_schedule.assert_not_called()
