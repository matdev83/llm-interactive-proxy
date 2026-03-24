"""Shared fixtures for OpenAI Codex connector tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.di.services import set_service_provider


@pytest.fixture(autouse=True)
def reset_di_container() -> Generator[None, None, None]:
    """Reset DI container between tests to prevent state pollution."""
    set_service_provider(None)
    yield
    set_service_provider(None)


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    data = {"tokens": {"access_token": "chatgpt_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="openai_codex_backend")
async def openai_codex_backend_fixture(auth_dir: Path):
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(
                openai_codex_path=str(auth_dir),
            )
            backend._auth_credentials = {"tokens": {"access_token": "chatgpt_token"}}
            try:
                yield backend
            finally:
                await backend.shutdown()
