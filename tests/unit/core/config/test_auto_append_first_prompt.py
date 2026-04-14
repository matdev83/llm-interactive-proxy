"""Tests for auto-append-first-prompt configuration resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from src.anthropic_server import create_anthropic_app_async
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.config.auto_append_first_prompt_hydration import (
    resolve_app_config,
    resolve_auto_append_first_prompt_text,
)
from src.core.config.models.app_config_model import AppConfigModel


def test_app_config_model_rejects_non_txt_md_extension() -> None:
    with pytest.raises(ValueError, match=r"\.txt or \.md"):
        AppConfigModel(auto_append_first_prompt_filename="notes.json")


def test_app_config_model_accepts_txt_and_md() -> None:
    m1 = AppConfigModel(auto_append_first_prompt_filename="a.TXT")
    assert m1.auto_append_first_prompt_filename == "a.TXT"
    m2 = AppConfigModel(auto_append_first_prompt_filename="b.md")
    assert m2.auto_append_first_prompt_filename == "b.md"


def test_resolve_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    cfg = AppConfig(auto_append_first_prompt_filename=str(missing))
    with pytest.raises(ValueError, match="file not found"):
        resolve_auto_append_first_prompt_text(cfg)


def test_resolve_reads_file(tmp_path: Path) -> None:
    p = tmp_path / "suffix.txt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))
    assert resolve_auto_append_first_prompt_text(cfg) == "hello\nworld"


def test_resolve_logs_load_info(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    p = tmp_path / "note.md"
    p.write_text("x", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))
    with caplog.at_level(
        logging.INFO, logger="src.core.config.auto_append_first_prompt_hydration"
    ):
        resolve_auto_append_first_prompt_text(cfg)
    assert "Auto-append first prompt: loaded 1 characters" in caplog.text


def test_resolve_empty_file_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "empty.md"
    p.write_text("   \n", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))
    assert resolve_auto_append_first_prompt_text(cfg) is None


def test_resolve_returns_none_when_filename_unset() -> None:
    cfg = AppConfig()
    assert resolve_auto_append_first_prompt_text(cfg) is None


def test_resolve_skips_non_string_filename() -> None:
    cfg = AppConfig()
    cfg.auto_append_first_prompt_filename = MagicMock()  # type: ignore[assignment]
    assert resolve_auto_append_first_prompt_text(cfg) is None


def test_resolve_app_config_returns_immutable_resolved_model(tmp_path: Path) -> None:
    p = tmp_path / "suffix.txt"
    p.write_text("tail", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))

    resolved = resolve_app_config(cfg)

    assert resolved.auto_append_first_prompt_text == "tail"
    with pytest.raises((TypeError, ValueError)):
        resolved.auto_append_first_prompt_text = "other"  # type: ignore[misc]


def test_application_builder_propagates_invalid_auto_append_prompt_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.md"
    cfg = AppConfig(auto_append_first_prompt_filename=str(missing))

    with pytest.raises(ValueError, match="file not found"):
        ApplicationBuilder()._create_fastapi_app(cfg, MagicMock())


@pytest.mark.asyncio
async def test_anthropic_app_propagates_invalid_auto_append_prompt_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.md"
    cfg = AppConfig(auto_append_first_prompt_filename=str(missing))
    built_app = FastAPI()
    built_app.state.service_provider = MagicMock()

    with pytest.raises(ValueError, match="file not found"):
        await create_anthropic_app_async(cfg, built_app=built_app)
