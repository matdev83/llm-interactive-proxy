from __future__ import annotations

from pathlib import Path

from src.connectors.acp_core.workspace_policy import (
    ACP_BACKEND_TYPES,
    extract_workspace_override_from_mapping,
    first_usable_workspace_dir,
    first_workspace_hint_str,
    is_usable_workspace_directory,
)


def test_acp_backend_types() -> None:
    assert "gemini-cli-acp" in ACP_BACKEND_TYPES
    assert "cursor-cli-acp" in ACP_BACKEND_TYPES


def test_extract_workspace_override_from_mapping_prefers_project_dir() -> None:
    m = {"project_dir": "/first", "workspace_path": "/second"}
    assert extract_workspace_override_from_mapping(m) == "/first"


def test_first_usable_workspace_dir(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    bad = tmp_path / "bad"
    assert (
        first_usable_workspace_dir(
            {"project_dir": str(bad)},
            {"workspace_path": str(good)},
        )
        == good.resolve()
    )


def test_first_workspace_hint_str_picks_first_key() -> None:
    assert first_workspace_hint_str({"project_dir": " /x "}) == "/x"


def test_is_usable_workspace_directory(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    assert is_usable_workspace_directory(d) is True
    assert is_usable_workspace_directory(tmp_path / "missing") is False
