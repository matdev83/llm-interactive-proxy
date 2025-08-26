# --- Mocks ---
from collections.abc import AsyncGenerator, Mapping
from typing import Any

import pytest
from fastapi import FastAPI
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)
from src.core.services.command_service import CommandRegistry, CommandService


class MockSuccessCommand(BaseCommand):
    def __init__(self, command_name: str, app: FastAPI | None = None) -> None:
        self.name = command_name
        self._called = False
        self._called_with_args: dict[str, Any] | None = None

    @property
    def called(self) -> bool:
        return self._called

    @property
    def called_with_args(self) -> dict[str, Any] | None:
        return self._called_with_args

    def reset_mock_state(self) -> None:
        self._called = False
        self._called_with_args = None

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)  # Convert Mapping to Dict for storage
        return CommandResult(
            success=True, message=f"{self.name} executed successfully", name=self.name
        )


# --- Fixtures ---


@pytest.fixture
def mock_app() -> FastAPI:
    app = FastAPI()
    app.state.functional_backends = {"openrouter", "gemini"}
    app.state.config_manager = None
    return app


@pytest.fixture
def proxy_state() -> SessionStateAdapter:
    from src.core.domain.session import SessionState

    session_state = SessionState()
    return SessionStateAdapter(session_state)


@pytest.fixture(
    params=[True, False], ids=["preserve_unknown_True", "preserve_unknown_False"]
)
async def command_parser(
    request, mock_app: FastAPI, proxy_state: SessionStateAdapter
) -> AsyncGenerator[CoreCommandProcessor, None]:
    _preserve_unknown = bool(request.param)

    registry = CommandRegistry()
    hello_cmd = MockSuccessCommand("hello", app=mock_app)
    another_cmd = MockSuccessCommand("anothercmd", app=mock_app)
    registry.register(hello_cmd)
    registry.register(another_cmd)

    class _SessionSvc:
        async def get_session(self, session_id: str):
            return Session(session_id=session_id, state=proxy_state)

        async def update_session(self, session):
            return None

    service = CommandService(
        registry, session_service=_SessionSvc(), preserve_unknown=_preserve_unknown
    )
    processor = CoreCommandProcessor(service)
    yield processor
