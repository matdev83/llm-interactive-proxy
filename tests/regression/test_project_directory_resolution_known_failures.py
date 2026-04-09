from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


def _build_service() -> ProjectDirectoryResolutionService:
    config = AppConfig(
        session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4",
        )
    )
    return ProjectDirectoryResolutionService(config, AsyncMock(), AsyncMock())


def test_repro_unix_path_parser_consumes_trailing_prose() -> None:
    service = _build_service()

    prompt = "The project root is /path/to/project/ and the file is foo/bar."

    assert service._find_absolute_path_in_prompt(prompt) == "/path/to/project"


def test_repro_deep_subdirectory_wins_over_actual_repo_root(tmp_path: Path) -> None:
    service = _build_service()

    project_root = tmp_path / "example-project"
    component_dir = project_root / "src" / "feature" / "component"
    component_dir.mkdir(parents=True)
    (project_root / ".git").mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='example'\n")
    (component_dir / "parser.py").write_text("print('parser')\n")
    (component_dir / "helpers.py").write_text("print('helpers')\n")

    prompt = (
        f"Investigate {component_dir / 'parser.py'} and "
        f"{component_dir / 'helpers.py'}."
    )

    assert service._find_absolute_path_in_prompt(prompt) == str(project_root)


def test_repro_prompt_extraction_separates_user_text_from_startup_hints(
    tmp_path: Path,
) -> None:
    service = _build_service()

    project_root = tmp_path / "example-project"
    component_file = project_root / "src" / "feature" / "component" / "parser.py"
    component_file.parent.mkdir(parents=True)
    component_file.write_text("print('parser')\n")

    request = ChatRequest(
        model="test-model",
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "You are opencode, an interactive CLI agent.\n"
                    "For example, /path/to/project and the file is foo/bar.\n"
                    f"workspace: {project_root}"
                ),
            ),
            ChatMessage(role="user", content=f"Please inspect {component_file}."),
            ChatMessage(
                role="assistant",
                content=f"I already looked at {component_file} for you.",
            ),
        ],
    )

    assert service._extract_user_prompt(request) == f"Please inspect {component_file}."
    assert service._extract_trusted_startup_prompt(request) == str(project_root)
