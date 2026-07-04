from __future__ import annotations

from pathlib import Path

from src.connectors.acp_core.workspace_policy import (
    ACP_BACKEND_TYPES,
    extract_workspace_override_from_mapping,
    first_usable_workspace_dir,
    first_workspace_hint_str,
    is_usable_workspace_directory,
    resolve_backend_init_acp_workspace,
)


def test_acp_backend_types() -> None:
    assert "gemini-cli-acp" in ACP_BACKEND_TYPES
    assert "cursor-cli-acp" in ACP_BACKEND_TYPES
    assert "agy-cli-acp" in ACP_BACKEND_TYPES
    assert "openai-codex-app-server" in ACP_BACKEND_TYPES


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


def test_first_usable_workspace_dir_require_absolute_skips_relative(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good"
    good.mkdir()
    assert (
        first_usable_workspace_dir(
            {"workspace_path": "relative-only"},
            {"workspace_path": str(good)},
            require_absolute_hint=True,
        )
        == good.resolve()
    )


def test_first_workspace_hint_str_picks_first_key() -> None:
    assert first_workspace_hint_str({"project_dir": " /x "}) == "/x"


def test_extract_workspace_override_ignores_dot() -> None:
    assert extract_workspace_override_from_mapping({"workspace_path": "."}) is None
    assert extract_workspace_override_from_mapping({"workspace_path": ".."}) is None


def test_resolve_backend_init_acp_workspace_blank_means_none(tmp_path: Path) -> None:
    path, err = resolve_backend_init_acp_workspace(
        project_dir=None,
        workspace_path=".",
        env_workspace=None,
        env_source_label="ENV",
        is_usable=is_usable_workspace_directory,
    )
    assert path is None and err is None

    good = tmp_path / "w"
    good.mkdir()
    path2, err2 = resolve_backend_init_acp_workspace(
        project_dir=str(good),
        workspace_path=None,
        env_workspace=None,
        env_source_label="ENV",
        is_usable=is_usable_workspace_directory,
    )
    assert path2 == good.resolve() and err2 is None


def test_resolve_backend_init_skips_dot_project_dir_uses_workspace(
    tmp_path: Path,
) -> None:
    good = tmp_path / "w"
    good.mkdir()
    path, err = resolve_backend_init_acp_workspace(
        project_dir=".",
        workspace_path=str(good),
        env_workspace=None,
        env_source_label="ENV",
        is_usable=is_usable_workspace_directory,
    )
    assert path == good.resolve() and err is None


def test_resolve_backend_init_acp_workspace_rejects_bad_absolute(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope"
    path, err = resolve_backend_init_acp_workspace(
        project_dir=str(missing),
        workspace_path=None,
        env_workspace=None,
        env_source_label="ENV",
        is_usable=is_usable_workspace_directory,
    )
    assert path is None
    assert err is not None and "readable" in err


def test_is_usable_workspace_directory(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    assert is_usable_workspace_directory(d) is True
    assert is_usable_workspace_directory(tmp_path / "missing") is False
