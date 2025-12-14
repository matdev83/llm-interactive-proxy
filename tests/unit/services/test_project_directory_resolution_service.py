from unittest.mock import AsyncMock

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
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
    resolution_mode: str, model_spec: str | None = "openai:gpt-4"
) -> AppConfig:
    """Helper to create AppConfig with specific resolution settings."""
    session_config = SessionConfig(
        project_dir_resolution_mode=resolution_mode,
        project_dir_resolution_model=model_spec,
    )
    return AppConfig(session=session_config)


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
            ("Use project \\\\server\\share\\folder", "\\\\server\\share\\folder"),
        ],
    )
    async def test_deterministic_finds_path(
        self, mock_backend_service, mock_session_service, session, prompt, expected_path
    ):
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == expected_path
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        mock_session_service.update_session.assert_called_once_with(session)

    async def test_deterministic_finds_longest_common_directory(
        self, mock_backend_service, mock_session_service, session
    ):
        prompt = (
            '"C:\\\\TopDir\\\\MiddleDir\\\\ProjectRoot\\\\src\\\\module1\\\\abc.py", '
            "'C:\\\\TopDir\\\\MiddleDir\\\\ProjectRoot\\\\src\\\\module2\\\\utils.py', "
            "`C:\\\\TopDir\\\\MiddleDir\\\\ProjectRoot\\\\docs\\\\README.md`, "
            "and C:\\\\TopDir\\\\MiddleDir\\\\ProjectRoot\\\\tests\\\\unit\\\\test_sample.py."
        )
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == "C:\\TopDir\\MiddleDir\\ProjectRoot"
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
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir is None
        assert session.state.project_dir_resolution_attempted is True
        mock_backend_service.call_completion.assert_not_called()
        assert "did not identify a directory (deterministic mode)" in caplog.text

    async def test_deterministic_fallbacks_to_cwd_when_candidate_has_no_dot_entries(
        self, mock_backend_service, mock_session_service, session, tmp_path, monkeypatch
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        monkeypatch.chdir(workspace)

        non_project_dir = tmp_path / "non_project_dir"
        non_project_dir.mkdir()

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content=f"Use {non_project_dir}")],
        )
        config = create_app_config("deterministic")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == str(workspace.resolve())
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
        prompt = "Path is C:\\MyProject"
        request = ChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content=prompt)]
        )
        config = create_app_config("hybrid")
        service = ProjectDirectoryResolutionService(
            config, mock_backend_service, mock_session_service
        )

        await service.maybe_resolve_project_directory(session, request)

        assert session.state.project_dir == "C:\\MyProject"
        mock_backend_service.call_completion.assert_not_called()
        assert (
            "Project directory auto-detected (deterministic): C:\\MyProject"
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
        config = create_app_config("hybrid", model_spec=None)
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
            "\\\\server\\share\\project",
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
