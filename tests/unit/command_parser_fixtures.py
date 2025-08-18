# --- Mocks ---
from collections.abc import AsyncGenerator, Mapping
from typing import Any

import pytest
from fastapi import FastAPI
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.constants import DEFAULT_COMMAND_PREFIX
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter


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
    # Essential for CommandParser init if create_command_instances relies on it
    app.state.functional_backends = {"openrouter", "gemini"}
    app.state.config_manager = None  # Mock this if it's used during command loading
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
) -> AsyncGenerator[CommandParser, None]:
    preserve_unknown_val = request.param
    parser_config = CommandParserConfig(
        proxy_state=proxy_state,
        app=mock_app,
        preserve_unknown=preserve_unknown_val,
        functional_backends=mock_app.state.functional_backends,
    )
    parser = CommandParser(parser_config, command_prefix=DEFAULT_COMMAND_PREFIX)
    parser.handlers.clear()

    # Create fresh mocks for each parametrization to avoid state leakage
    # Pass the mock_app to the command constructor if it needs it (optional here)
    hello_cmd = MockSuccessCommand("hello", app=mock_app)
    another_cmd = MockSuccessCommand("anothercmd", app=mock_app)
    parser.register_command(hello_cmd)
    parser.register_command(another_cmd)
    yield parser
