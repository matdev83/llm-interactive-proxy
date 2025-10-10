from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


@pytest.fixture()
def app_config() -> AppConfig:
    cfg = AppConfig()
    cfg.session = cfg.session.model_copy(
        update={"project_dir_resolution_model": "openai:gpt-4o-mini"}
    )
    return cfg


@pytest.mark.asyncio()
async def test_resolves_directory_and_updates_session(app_config: AppConfig) -> None:
    backend_service = MagicMock()
    backend_service.call_completion = AsyncMock(
        return_value=ResponseEnvelope(
            content={
                "choices": [
                    {
                        "message": {
                            "content": """
<directory-resolution-response>
<project-absolute-directory>/workspace/project-alpha</project-absolute-directory>
</directory-resolution-response>
""".strip()
                        }
                    }
                ]
            }
        )
    )
    session_service = MagicMock()
    session_service.update_session = AsyncMock()

    service = ProjectDirectoryResolutionService(
        app_config, backend_service, session_service
    )

    session = Session(session_id="session-123")
    request = ChatRequest(
        model="unused",
        messages=[
            ChatMessage(
                role="user", content="Project lives at /workspace/project-alpha"
            )
        ],
    )

    await service.maybe_resolve_project_directory(session, request)

    assert session.state.project_dir == "/workspace/project-alpha"
    assert session.state.project_dir_resolution_attempted is True
    session_service.update_session.assert_awaited_once()
    backend_service.call_completion.assert_awaited_once()


@pytest.mark.asyncio()
async def test_handles_invalid_directory_response(app_config: AppConfig) -> None:
    backend_service = MagicMock()
    backend_service.call_completion = AsyncMock(
        return_value=ResponseEnvelope(
            content={
                "choices": [
                    {
                        "message": {
                            "content": """
<directory-resolution-response>
<project-absolute-directory>relative/path</project-absolute-directory>
</directory-resolution-response>
""".strip()
                        }
                    }
                ]
            }
        )
    )
    session_service = MagicMock()
    session_service.update_session = AsyncMock()

    service = ProjectDirectoryResolutionService(
        app_config, backend_service, session_service
    )

    session = Session(session_id="session-456")
    request = ChatRequest(
        model="unused",
        messages=[
            ChatMessage(role="user", content="Some context without absolute dir")
        ],
    )

    await service.maybe_resolve_project_directory(session, request)

    assert session.state.project_dir is None
    assert session.state.project_dir_resolution_attempted is True
    session_service.update_session.assert_awaited_once()


@pytest.mark.asyncio()
async def test_no_call_when_feature_disabled() -> None:
    cfg = AppConfig()
    cfg.session = cfg.session.model_copy(update={"project_dir_resolution_model": None})

    backend_service = MagicMock()
    backend_service.call_completion = AsyncMock()
    session_service = MagicMock()
    session_service.update_session = AsyncMock()

    service = ProjectDirectoryResolutionService(cfg, backend_service, session_service)

    session = Session(session_id="session-789")
    request = ChatRequest(
        model="unused",
        messages=[ChatMessage(role="user", content="Project at C:/workspaces/demo")],
    )

    await service.maybe_resolve_project_directory(session, request)

    backend_service.call_completion.assert_not_called()
    session_service.update_session.assert_not_called()
    assert session.state.project_dir is None
    assert session.state.project_dir_resolution_attempted is False
