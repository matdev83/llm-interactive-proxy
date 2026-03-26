"""Tests for auto-append-first-prompt configuration and hydration."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.config.auto_append_first_prompt_hydration import (
    hydrate_auto_append_first_prompt,
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


def test_hydrate_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    cfg = AppConfig(auto_append_first_prompt_filename=str(missing))
    with pytest.raises(ValueError, match="file not found"):
        hydrate_auto_append_first_prompt(cfg)


def test_hydrate_reads_file(tmp_path: Path) -> None:
    p = tmp_path / "suffix.txt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))
    hydrate_auto_append_first_prompt(cfg)
    assert cfg.auto_append_first_prompt_text == "hello\nworld"


def test_hydrate_logs_load_info(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    p = tmp_path / "note.md"
    p.write_text("x", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))
    with caplog.at_level(
        logging.INFO, logger="src.core.config.auto_append_first_prompt_hydration"
    ):
        hydrate_auto_append_first_prompt(cfg)
    assert "Auto-append first prompt: loaded 1 characters" in caplog.text


def test_hydrate_empty_file_sets_text_none(tmp_path: Path) -> None:
    p = tmp_path / "empty.md"
    p.write_text("   \n", encoding="utf-8")
    cfg = AppConfig(auto_append_first_prompt_filename=str(p))
    hydrate_auto_append_first_prompt(cfg)
    assert cfg.auto_append_first_prompt_text is None


def test_hydrate_clears_when_filename_unset() -> None:
    cfg = AppConfig()
    cfg.auto_append_first_prompt_text = "stale"
    hydrate_auto_append_first_prompt(cfg)
    assert cfg.auto_append_first_prompt_text is None


def test_hydrate_skips_non_string_filename() -> None:
    cfg = AppConfig()
    cfg.auto_append_first_prompt_filename = MagicMock()  # type: ignore[assignment]
    cfg.auto_append_first_prompt_text = "stale"
    hydrate_auto_append_first_prompt(cfg)
    assert cfg.auto_append_first_prompt_text is None
