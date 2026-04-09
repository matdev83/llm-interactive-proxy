from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


@pytest.fixture
def mock_backend_service() -> AsyncMock:
    """Fixture for a mocked IBackendService."""
    return AsyncMock()


@pytest.fixture
def mock_session_service() -> AsyncMock:
    """Fixture for a mocked ISessionService."""
    return AsyncMock()


@pytest.fixture
def session() -> Session:
    """Fixture for a new session."""
    return Session(session_id="test-session", state=SessionState())


def create_app_config(
    resolution_mode: str,
    model_spec: str | None = "openai:gpt-4",
    filesystem_mode: Literal["auto", "enabled", "disabled"] = "auto",
    access_mode: AccessMode = AccessMode.SINGLE_USER,
    disable_default_openrouter_fallback: bool = False,
) -> AppConfig:
    """Helper to create AppConfig with specific resolution settings."""
    session_config = SessionConfig(
        project_dir_resolution_mode=resolution_mode,
        project_dir_resolution_model=model_spec,
        project_dir_resolution_filesystem_mode=filesystem_mode,
        disable_default_openrouter_project_dir_resolution_fallback=disable_default_openrouter_fallback,
    )
    return AppConfig(
        session=session_config,
        access_mode=AccessModeConfig(mode=access_mode),
    )


@pytest.mark.asyncio
class TestProjectDirectoryResolutionService:

    # Deterministic Tests
    @pytest.mark.parametrize(
        "prompt, expected_path",
        [
            ("Work on C:\\Users\\Test\\Project", "C:\\Users\\Test\\Project"),
            (
                "My project is at /home/user/dev/project-x, please help",
                "/home/user/dev/project-x",
            ),
            (
                "Use project \\\\server\\share\\folder\\src\\main",
                "\\\\server\\share\\folder\\src\\main",
            ),
        ],
    )
    async def test_deterministic_finds_path(
        self, mock_backend_service, mock_session_service, session, prompt, expected_path
    ):
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )
        config = create_app_config(
            "deterministic",
            disable_default_openrouter_fallback=True,
        )
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == expected_path
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_called_once_with(session)

    async def test_deterministic_uses_marker_backed_root_for_file_mentions(
        self, mock_backend_service, mock_session_service, session, tmp_path: Path
    ):
        project_root = tmp_path / "project-root"
        module_a = project_root / "src" / "module1"
        module_b = project_root / "src" / "module2"
        docs_dir = project_root / "docs"
        tests_dir = project_root / "tests" / "unit"
        module_a.mkdir(parents=True)
        module_b.mkdir(parents=True)
        docs_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)
        (project_root / ".git").mkdir()
        (module_a / "abc.py").write_text("pass\n")
        (module_b / "utils.py").write_text("pass\n")
        (docs_dir / "README.md").write_text("docs\n")
        (tests_dir / "test_sample.py").write_text("pass\n")

        prompt = (
            f'"{module_a / "abc.py"}", '
            f"'{module_b / 'utils.py'}', "
            f"`{docs_dir / 'README.md'}`, "
            f"and {tests_dir / 'test_sample.py'}."
        )
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )
        config = create_app_config("deterministic", filesystem_mode="enabled")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == str(project_root.resolve())
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_called_once_with(session)

    async def test_deterministic_uses_developer_metadata_cwd_hint(
        self, mock_backend_service, mock_session_service, session, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project-root"
        project_root.mkdir(parents=True)

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="system",
                    content="Generic startup instructions only.",
                ),
                ChatMessage(
                    role="developer",
                    content="Session metadata",
                    metadata={"cwd": str(project_root)},
                ),
                ChatMessage(
                    role="user",
                    content="Please inspect the project root.",
                ),
            ],
        )
        config = create_app_config(
            "deterministic",
            filesystem_mode="disabled",
            access_mode=AccessMode.MULTI_USER,
        )
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == str(project_root)
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_called_once_with(session)

    async def test_deterministic_uses_request_metadata_cwd_hint(
        self, mock_backend_service, mock_session_service, session, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project-root"
        project_root.mkdir(parents=True)

        request = ChatRequest(
            model="test-model",
            request_metadata={"cwd": str(project_root)},
            messages=[
                ChatMessage(
                    role="system",
                    content="Generic startup instructions only.",
                ),
                ChatMessage(
                    role="user",
                    content="Please inspect the project root.",
                ),
            ],
        )
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == str(project_root)
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_called_once_with(session)

    async def test_deterministic_uses_tool_call_arguments_cwd_hint(
        self, mock_backend_service, mock_session_service, session, tmp_path: Path
    ) -> None:
        project_root = tmp_path / "project-root"
        project_root.mkdir(parents=True)

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="system",
                    content="Generic startup instructions only.",
                ),
                ChatMessage(
                    role="assistant",
                    tool_calls=[
                        ToolCall(
                            function=FunctionCall(
                                name="bash",
                                arguments=f"cwd: {project_root}",
                            )
                        )
                    ],
                ),
                ChatMessage(
                    role="user",
                    content="Please inspect the project root.",
                ),
            ],
        )
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == str(project_root)
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_called_once_with(session)

    async def test_deterministic_no_path(
        self,
        mock_backend_service,
        mock_session_service,
        session,
        caplog,
        tmp_path,
        monkeypatch,
    ):
        # Ensure we don't accidentally set project_dir via deterministic fallback-to-cwd.
        # The fallback is dot-based, so use an empty temp directory without dot entries.
        monkeypatch.chdir(tmp_path)
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello world")],
        )
        config = create_app_config(
            "deterministic",
            disable_default_openrouter_fallback=True,
        )
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        assert "did not identify a directory (deterministic mode)" in caplog.text

    async def test_deterministic_does_not_auto_fallback_to_llm(
        self, mock_backend_service, mock_session_service, session
    ) -> None:
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello world")],
        )
        config = create_app_config("deterministic", model_spec=None)
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        service._openrouter_api_key_available = True

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()

    async def test_deterministic_does_not_fallback_to_cwd_when_candidate_is_ambiguous(
        self, mock_backend_service, mock_session_service, session, tmp_path, monkeypatch
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        monkeypatch.chdir(workspace)

        non_project_dir = tmp_path / "non_project_dir"
        non_project_dir.mkdir()

        file_a = non_project_dir / "a.py"
        file_b = non_project_dir / "b.py"
        file_a.write_text("print('a')\n")
        file_b.write_text("print('b')\n")

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user", content=f"Use {file_a} and also inspect {file_b}"
                )
            ],
        )
        config = create_app_config(
            "deterministic",
            disable_default_openrouter_fallback=True,
        )
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()

    # LLM Mode Tests
    async def test_llm_mode_success(
        self, mock_backend_service, mock_session_service, session, caplog
    ):
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="I want to work on my project")],
        )
        config = create_app_config("llm")

        llm_response = ResponseEnvelope(
            content="<directory-resolution-response><project-absolute-directory>/home/user/Desktop</project-absolute-directory></directory-resolution-response>"
        )
        mock_backend_service.call_completion.return_value = llm_response

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == "/home/user/Desktop"
        mock_backend_service.call_completion.assert_called_once()
        assert (
            "Project directory auto-detected (LLM): /home/user/Desktop" in caplog.text
        )

    async def test_llm_mode_llm_fails(
        self, mock_backend_service, mock_session_service, session, caplog
    ):
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="my project is on the desktop")],
        )
        config = create_app_config("llm")

        llm_response = ResponseEnvelope(
            content="<directory-resolution-response><error>Cannot determine</error></directory-resolution-response>"
        )
        mock_backend_service.call_completion.return_value = llm_response

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        mock_backend_service.call_completion.assert_called_once()
        assert "did not identify a directory (Cannot determine)" in caplog.text

    # Hybrid Mode Tests
    async def test_hybrid_mode_deterministic_wins(
        self, mock_backend_service, mock_session_service, session, caplog
    ):
        prompt = "Path is C:\\Users\\Test\\MyProject"
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )
        config = create_app_config("hybrid")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == "C:\\Users\\Test\\MyProject"
        mock_backend_service.call_completion.assert_not_called()
        assert (
            "Project directory auto-detected (deterministic/user): C:\\Users\\Test\\MyProject"
            in caplog.text
        )

    async def test_hybrid_mode_fallback_to_llm(
        self, mock_backend_service, mock_session_service, session, caplog
    ):
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="my project is on the desktop")],
        )
        config = create_app_config("hybrid")

        llm_response = ResponseEnvelope(
            content="<directory-resolution-response><project-absolute-directory>/home/user/Desktop</project-absolute-directory></directory-resolution-response>"
        )
        mock_backend_service.call_completion.return_value = llm_response

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == "/home/user/Desktop"
        mock_backend_service.call_completion.assert_called_once()
        assert (
            "Project directory auto-detected (LLM): /home/user/Desktop" in caplog.text
        )

    async def test_hybrid_mode_fallback_to_llm_when_filesystem_probe_disabled(
        self, mock_backend_service, mock_session_service, session, tmp_path, caplog
    ):
        project_root = tmp_path / "project-root"
        component_dir = project_root / "src" / "feature" / "component"
        component_dir.mkdir(parents=True)
        (project_root / ".git").mkdir()
        file_a = component_dir / "a.py"
        file_b = component_dir / "b.py"
        file_a.write_text("print('a')\n")
        file_b.write_text("print('b')\n")

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content=f"Inspect {file_a} and {file_b}")
            ],
        )
        config = create_app_config(
            "hybrid",
            filesystem_mode="disabled",
            access_mode=AccessMode.MULTI_USER,
        )

        llm_response = ResponseEnvelope(
            content="<directory-resolution-response><project-absolute-directory>/home/user/Desktop</project-absolute-directory></directory-resolution-response>"
        )
        mock_backend_service.call_completion.return_value = llm_response

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == "/home/user/Desktop"
        mock_backend_service.call_completion.assert_called_once()
        assert (
            "Project directory auto-detected (LLM): /home/user/Desktop" in caplog.text
        )

    async def test_deterministic_mode_does_not_auto_fallback_to_openrouter_in_single_user_mode(
        self,
        mock_backend_service,
        mock_session_service,
        session,
        monkeypatch,
        caplog,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="my project is on the desktop")],
        )
        config = create_app_config("deterministic", model_spec=None)

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        assert "did not identify a directory (deterministic mode)" in caplog.text

    async def test_deterministic_mode_ignores_user_override_model_in_deterministic_mode(
        self,
        mock_backend_service,
        mock_session_service,
        session,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="my project is on the desktop")],
        )
        config = create_app_config(
            "deterministic",
            model_spec="openai:gpt-4.1-mini",
        )

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()

    async def test_deterministic_mode_does_not_fallback_when_disable_flag_is_set(
        self,
        mock_backend_service,
        mock_session_service,
        session,
        monkeypatch,
        caplog,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="my project is on the desktop")],
        )
        config = create_app_config(
            "deterministic",
            model_spec=None,
            disable_default_openrouter_fallback=True,
        )

        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        assert "did not identify a directory (deterministic mode)" in caplog.text

    # Edge cases
    async def test_skips_if_dir_already_set(
        self, mock_backend_service, mock_session_service, caplog
    ):
        session = Session(
            session_id="test", state=SessionState().with_project_dir("/already/set")
        )
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="...")]
        )
        config = create_app_config("hybrid")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        mock_backend_service.call_completion.assert_not_called()
        assert "skipped: directory already set" in caplog.text

    async def test_skips_if_history_not_empty(
        self, mock_backend_service, mock_session_service, session
    ):
        session.history.append(ChatMessage(role="user", content="previous message"))
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="current message")],
        )
        config = create_app_config("hybrid")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_not_called()

    async def test_llm_mode_no_model_configured(
        self, mock_backend_service, mock_session_service, session, caplog
    ):
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="some prompt")],
        )
        config = create_app_config("llm", model_spec=None)
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        mock_backend_service.call_completion.assert_not_called()
        assert (
            "LLM project directory resolution is enabled but no model is configured"
            in caplog.text
        )

    async def test_hybrid_mode_no_model_configured_fallback(
        self, mock_backend_service, mock_session_service, session, caplog
    ):
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="some prompt without a path")],
        )
        config = create_app_config(
            "hybrid",
            model_spec=None,
            disable_default_openrouter_fallback=True,
        )
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        mock_backend_service.call_completion.assert_not_called()
        assert (
            "did not identify a directory (hybrid mode, no LLM configured)"
            in caplog.text
        )

    async def test_no_call_when_feature_disabled(
        self, mock_backend_service, mock_session_service, session
    ) -> None:
        config = create_app_config("disabled")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="some prompt")],
        )

        await service.maybe_resolve_project_directory(session, request)

        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_not_called()


@pytest.mark.asyncio
class TestProjectDirectoryValidation:
    @pytest.mark.parametrize(
        "invalid_path",
        [
            "C:\\",
            "D:\\",
            "/",
            "C:\\Users",
            "/home",
            "C:\\Windows\\System32",
            "/usr/bin",
            "\\\\server\\share",  # Shallow UNC
        ],
    )
    def test_rejects_invalid_paths(
        self, invalid_path, mock_backend_service, mock_session_service
    ):
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        path_type = service._detect_path_type(invalid_path)
        assert path_type is not None, f"Path type for {invalid_path} should be detected"
        assert not service._is_valid_project_directory_candidate(
            invalid_path, path_type
        )

    @pytest.mark.parametrize(
        "valid_path",
        [
            "C:\\Users\\test\\project",
            "/home/user/project",
            "\\\\server\\share\\team\\project\\src",
            "C:\\Users\\some-user\\Desktop\\my-project",
        ],
    )
    def test_accepts_valid_paths(
        self, valid_path, mock_backend_service, mock_session_service
    ):
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )
        path_type = service._detect_path_type(valid_path)
        assert path_type is not None, f"Path type for {valid_path} should be detected"
        assert service._is_valid_project_directory_candidate(valid_path, path_type)


@pytest.mark.asyncio
async def test_deterministic_scoring_prefers_deeper_paths(
    mock_backend_service, mock_session_service, session
):
    prompt = (
        "We have C:\\Users\\Test and also C:\\Users\\Test\\ProjectA. "
        "And another one at C:\\Users\\Test\\ProjectA\\src"
    )
    request = ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content=prompt)]
    )
    config = create_app_config("deterministic")
    service = ProjectDirectoryResolutionService(
        config, mock_backend_service, mock_session_service
    )

    await service.maybe_resolve_project_directory(session, request)

    # The deepest common path should be preferred
    assert session.state.project_dir == "C:\\Users\\Test\\ProjectA"


@pytest.mark.asyncio
async def test_deterministic_ignores_system_and_root_paths(
    mock_backend_service, mock_session_service, session
):
    prompt = (
        "My project is at C:\\Users\\Test\\Project, but I also have "
        "C:\\Windows and /etc/hosts mentioned."
    )
    request = ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content=prompt)]
    )
    config = create_app_config("deterministic")
    service = ProjectDirectoryResolutionService(
        config, mock_backend_service, mock_session_service
    )

    await service.maybe_resolve_project_directory(session, request)

    assert session.state.project_dir == "C:\\Users\\Test\\Project"


class TestExtractXmlFromResponse:
    def _build_service(self) -> ProjectDirectoryResolutionService:
        config = create_app_config("deterministic")
        mock = AsyncMock()
        mock.update_session = AsyncMock()
        return ProjectDirectoryResolutionService(config, AsyncMock(), mock)

    def test_strips_thinking_tags(self) -> None:
        service = self._build_service()
        response = (
            "I need to think about this.\n"
            "</think>\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )
        result = service._extract_xml_from_response(response)
        assert result.startswith("<directory-resolution-response>")
        assert "/home/user/project" in result

    def test_strips_thinking_tags_before_xml(self) -> None:
        service = self._build_service()
        response = (
            "Let me reason.\n"
            "The path is probably /somewhere.\n"
            "</think>\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )
        result = service._extract_xml_from_response(response)
        assert result.startswith("<directory-resolution-response>")

    def test_strips_reasoning_tags(self) -> None:
        service = self._build_service()
        response = (
            "<reasoning>The user wants a path.</reasoning>\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )
        result = service._extract_xml_from_response(response)
        assert result.startswith("<directory-resolution-response>")

    def test_extracts_from_xml_code_block(self) -> None:
        service = self._build_service()
        response = (
            "Here is the response:\n\n"
            "```xml\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>\n"
            "```\n\n"
            "Let me know if this helps."
        )
        result = service._extract_xml_from_response(response)
        assert result == (
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )

    def test_extracts_from_plain_code_block(self) -> None:
        service = self._build_service()
        response = (
            "```\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>\n"
            "```"
        )
        result = service._extract_xml_from_response(response)
        assert result == (
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )

    def test_extracts_xml_from_surrounding_prose(self) -> None:
        service = self._build_service()
        response = (
            "Based on your instructions, the project directory is:\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>\n"
            "Hope that helps!"
        )
        result = service._extract_xml_from_response(response)
        assert result.startswith("<directory-resolution-response>")
        assert "/home/user/project" in result

    def test_returns_original_when_no_xml_found(self) -> None:
        service = self._build_service()
        response = "I don't know what directory you mean."
        result = service._extract_xml_from_response(response)
        assert result == response

    def test_returns_clean_xml_when_already_correct(self) -> None:
        service = self._build_service()
        response = (
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )
        result = service._extract_xml_from_response(response)
        assert result == response


class TestParseDirectoryResponseWithNoisyInput:
    def _build_service(self) -> ProjectDirectoryResolutionService:
        config = create_app_config("deterministic")
        mock = AsyncMock()
        mock.update_session = AsyncMock()
        return ProjectDirectoryResolutionService(config, AsyncMock(), mock)

    def test_parses_xml_with_thinking_block(self) -> None:
        service = self._build_service()
        response = (
            "</think>\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>"
        )
        directory, error = service._parse_directory_response(response)
        assert directory == "/home/user/project"
        assert error is None

    def test_parses_xml_from_markdown_code_block(self) -> None:
        service = self._build_service()
        response = (
            "```xml\n"
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>\n"
            "```"
        )
        directory, error = service._parse_directory_response(response)
        assert directory == "/home/user/project"
        assert error is None

    def test_parses_error_response_with_thinking_block(self) -> None:
        service = self._build_service()
        response = (
            "I'm not sure about this.\n"
            "</think>\n"
            "<directory-resolution-response>"
            "<error>Cannot determine the project directory from the prompt.</error>"
            "</directory-resolution-response>"
        )
        directory, error = service._parse_directory_response(response)
        assert directory is None
        assert error is not None
        assert "Cannot determine" in error

    def test_parses_xml_with_trailing_prose_after_block(self) -> None:
        service = self._build_service()
        response = (
            "<directory-resolution-response>"
            "<project-absolute-directory>/home/user/project</project-absolute-directory>"
            "</directory-resolution-response>\n"
            "Extra prose that should be ignored."
        )
        directory, error = service._parse_directory_response(response)
        assert directory == "/home/user/project"
        assert error is None

    def test_rejects_non_xml_response(self) -> None:
        service = self._build_service()
        response = "Sorry, I cannot help with that."
        directory, error = service._parse_directory_response(response)
        assert directory is None
        assert error is not None
        assert "invalid XML" in error
